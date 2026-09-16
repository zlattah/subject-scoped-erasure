"""RAD-CDC: FastCDC with store-informed cut migration and exact-stability.

This is an improvement on FastCDC, not a new chunking family:

1. Compute the natural FastCDC cut.
2. If that chunk is already in the store, keep it (exact-stability).
3. Otherwise score a few nearby legal cuts for exact hits, sketch
   similarity, restore fragmentation, and size, then maybe migrate.
"""

from __future__ import annotations

from dataclasses import dataclass

from cascade_dedup.chunking import CDCParams, FastCDC, fingerprint, sketch
from cascade_dedup.store import ChunkStore


@dataclass(frozen=True)
class RADWeights:
    exact: float = 1.0
    delta: float = 0.6
    frag: float = 0.4
    size: float = 0.2


class RADCDC:
    def __init__(
        self,
        params: CDCParams | None = None,
        weights: RADWeights | None = None,
        max_candidates: int = 8,
    ) -> None:
        self.fast = FastCDC(params)
        self.params = self.fast.params
        self.weights = weights or RADWeights()
        self.max_candidates = max_candidates

    def cuts(self, data: bytes, store: ChunkStore) -> list[int]:
        ends: list[int] = []
        start = 0
        recent_containers: list[int] = []
        n = len(data)
        while start < n:
            end = self.next_cut(data, start, store, recent_containers)
            ends.append(end)
            fp = fingerprint(data[start:end])
            hit = store.lookup(fp)
            if hit is not None:
                recent_containers.append(hit.container_id)
                if len(recent_containers) > 8:
                    recent_containers = recent_containers[-8:]
            start = end
        return ends

    def chunks(self, data: bytes, store: ChunkStore) -> list[bytes]:
        ends = self.cuts(data, store)
        out: list[bytes] = []
        prev = 0
        for end in ends:
            out.append(data[prev:end])
            prev = end
        return out

    def next_cut(
        self,
        data: bytes,
        start: int,
        store: ChunkStore,
        recent_containers: list[int] | None = None,
    ) -> int:
        recent = recent_containers or []
        p = self.params
        n = len(data)
        remaining = n - start
        if remaining <= p.min_size:
            return n

        natural, backups = self.fast.next_cut_with_backups(data, start, limit=self.max_candidates)
        if not store.exact:
            return natural
        natural_chunk = data[start:natural]
        if store.lookup(fingerprint(natural_chunk)) is not None:
            return natural

        candidates = self._candidates(data, start, natural, backups, store)
        best = natural
        best_score = self._score(natural_chunk, natural - start, store, recent)
        for end in candidates:
            if end == natural:
                continue
            chunk = data[start:end]
            hit = store.lookup(fingerprint(chunk))
            if hit is None:
                _, sim = store.best_similar(sketch(chunk))
                if sim < 0.25:
                    continue
            score = self._score(chunk, end - start, store, recent)
            if score > best_score:
                best_score = score
                best = end
        return best

    def _candidates(
        self,
        data: bytes,
        start: int,
        natural: int,
        backups: list[int],
        store: ChunkStore,
    ) -> list[int]:
        p = self.params
        n = len(data)
        max_end = min(n, start + p.max_size)
        min_end = min(n, start + p.min_size)
        found: list[int] = []
        seen: set[int] = set()

        def add(end: int) -> None:
            if end <= start or end > n:
                return
            if end < min_end and end != n:
                return
            if end > max_end and end != n:
                return
            if end not in seen:
                seen.add(end)
                found.append(end)

        add(natural)
        for b in backups:
            add(b)
        for delta in (256, 1024, 4096, -256, -1024, -4096):
            add(natural + delta)

        prefix_len = min(p.min_size, n - start)
        prefix_sk = sketch(data[start : start + prefix_len])
        for length in store.similar_lengths(prefix_sk):
            add(start + length)

        if len(found) > self.max_candidates:
            # Keep natural, then backups, then the rest up to the cap.
            head = [natural]
            rest = [c for c in found if c != natural]
            found = head + rest[: self.max_candidates - 1]
        return found

    def _score(
        self,
        chunk: bytes,
        length: int,
        store: ChunkStore,
        recent_containers: list[int],
    ) -> float:
        w = self.weights
        p = self.params
        fp = fingerprint(chunk)
        hit = store.lookup(fp)
        exact_gain = 1.0 if hit is not None else 0.0

        sk = sketch(chunk)
        _, sim = store.best_similar(sk)
        delta_gain = 0.0 if exact_gain >= 1.0 else sim

        if hit is not None:
            frag = 0.0 if hit.container_id in recent_containers else 1.0
        else:
            frag = 0.0

        span = p.max_size - p.min_size
        size_pen = abs(length - p.avg_size) / span if span else 0.0
        return w.exact * exact_gain + w.delta * delta_gain - w.frag * frag - w.size * size_pen
