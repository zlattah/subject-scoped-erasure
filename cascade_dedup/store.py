"""In-memory chunk store: exact index, sketches, and 256 KiB containers."""

from __future__ import annotations

from dataclasses import dataclass, field

from cascade_dedup.chunking import fingerprint, sketch, sketch_similarity


CONTAINER_TARGET = 256 * 1024


@dataclass
class StoredChunk:
    fp: bytes
    length: int
    container_id: int
    sketch: tuple[int, ...]
    data: bytes


@dataclass
class ChunkStore:
    exact: dict[bytes, StoredChunk] = field(default_factory=dict)
    sketch_cache: list[StoredChunk] = field(default_factory=list)
    sketch_limit: int = 4096
    containers: list[bytearray] = field(default_factory=list)
    open_used: int = 0
    unique_bytes: int = 0

    def __post_init__(self) -> None:
        if not self.containers:
            self.containers.append(bytearray())
            self.open_used = 0

    @property
    def open_container_id(self) -> int:
        return len(self.containers) - 1

    def lookup(self, fp: bytes) -> StoredChunk | None:
        return self.exact.get(fp)

    def best_similar(self, sk: tuple[int, ...], min_sim: float = 0.25) -> tuple[StoredChunk | None, float]:
        best: StoredChunk | None = None
        best_sim = 0.0
        for item in self.sketch_cache:
            sim = sketch_similarity(sk, item.sketch)
            if sim > best_sim:
                best_sim = sim
                best = item
        if best is None or best_sim < min_sim:
            return None, 0.0
        return best, best_sim

    def similar_lengths(self, sk: tuple[int, ...], min_sim: float = 0.25, limit: int = 6) -> list[int]:
        scored: list[tuple[float, int]] = []
        seen: set[int] = set()
        for item in self.sketch_cache:
            sim = sketch_similarity(sk, item.sketch)
            if sim >= min_sim and item.length not in seen:
                scored.append((sim, item.length))
                seen.add(item.length)
        scored.sort(reverse=True)
        return [length for _, length in scored[:limit]]

    def put_unique(self, data: bytes, *, fp: bytes | None = None) -> StoredChunk:
        fp = fp or fingerprint(data)
        existing = self.exact.get(fp)
        if existing is not None:
            return existing
        if self.open_used + len(data) > CONTAINER_TARGET and self.open_used > 0:
            self.containers.append(bytearray())
            self.open_used = 0
        cid = self.open_container_id
        self.containers[cid].extend(data)
        self.open_used += len(data)
        stored = StoredChunk(
            fp=fp,
            length=len(data),
            container_id=cid,
            sketch=sketch(data),
            data=data,
        )
        self.exact[fp] = stored
        self.sketch_cache.append(stored)
        if len(self.sketch_cache) > self.sketch_limit:
            self.sketch_cache = self.sketch_cache[-self.sketch_limit :]
        self.unique_bytes += len(data)
        return stored
