"""Ingest a byte stream: chunk, exact-dedup, optional post-chunk delta."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from cascade_dedup.chunking import FastCDC, fingerprint, sketch
from cascade_dedup.delta import effective_unique_size
from cascade_dedup.radcdc import RADCDC
from cascade_dedup.store import CONTAINER_TARGET, ChunkStore


@dataclass
class IngestStats:
    name: str
    logical_bytes: int = 0
    unique_bytes: int = 0
    after_delta_bytes: int = 0
    chunks: int = 0
    exact_hits: int = 0
    migrated_cuts: int = 0
    restore_containers: int = 0
    elapsed_s: float = 0.0
    chunk_size_sum: int = 0

    @property
    def dedup_ratio(self) -> float:
        if self.unique_bytes == 0:
            return float("inf") if self.logical_bytes else 1.0
        return self.logical_bytes / self.unique_bytes

    @property
    def reduction_with_delta(self) -> float:
        if self.after_delta_bytes == 0:
            return float("inf") if self.logical_bytes else 1.0
        return self.logical_bytes / self.after_delta_bytes

    @property
    def avg_chunk(self) -> float:
        return self.chunk_size_sum / self.chunks if self.chunks else 0.0

    @property
    def restore_speed_factor(self) -> float:
        if self.restore_containers == 0:
            return 0.0
        return self.logical_bytes / (self.restore_containers * CONTAINER_TARGET)

    def as_row(self) -> dict[str, float | int | str]:
        return {
            "name": self.name,
            "logical_MiB": round(self.logical_bytes / (1024 * 1024), 3),
            "unique_MiB": round(self.unique_bytes / (1024 * 1024), 3),
            "delta_MiB": round(self.after_delta_bytes / (1024 * 1024), 3),
            "dedup_ratio": round(self.dedup_ratio, 3),
            "ratio_with_delta": round(self.reduction_with_delta, 3),
            "chunks": self.chunks,
            "exact_hits": self.exact_hits,
            "migrated_cuts": self.migrated_cuts,
            "restore_containers": self.restore_containers,
            "avg_chunk": round(self.avg_chunk, 1),
            "MB_s": round((self.logical_bytes / (1024 * 1024)) / self.elapsed_s, 2)
            if self.elapsed_s
            else 0.0,
        }


def _fastcdc_cuts(chunker: FastCDC, data: bytes, store: ChunkStore | None = None) -> list[int]:
    return chunker.cuts(data)


def ingest_stream(
    data: bytes,
    *,
    mode: str,
    store: ChunkStore | None = None,
    do_delta: bool = True,
) -> tuple[ChunkStore, IngestStats, list[int]]:
    store = store or ChunkStore()
    t0 = perf_counter()
    if mode == "fastcdc":
        chunker = FastCDC()
        natural_tracker = FastCDC()
        ends = chunker.cuts(data)
    elif mode == "radcdc":
        chunker = RADCDC()
        natural_tracker = FastCDC()
        ends = chunker.cuts(data, store)
    else:
        raise ValueError(f"unknown mode {mode!r}")

    stats = IngestStats(name=mode)
    recipe_ids: set[int] = set()
    prev = 0
    for end in ends:
        chunk = data[prev:end]
        stats.chunks += 1
        stats.chunk_size_sum += len(chunk)
        if mode == "radcdc":
            natural_end = natural_tracker.next_cut(data, prev)
            if end != natural_end:
                stats.migrated_cuts += 1
        fp = fingerprint(chunk)
        hit = store.lookup(fp)
        if hit is not None:
            stats.exact_hits += 1
            recipe_ids.add(hit.container_id)
        else:
            sk = sketch(chunk)
            base, sim = store.best_similar(sk)
            stored = store.put_unique(chunk)
            recipe_ids.add(stored.container_id)
            if do_delta and base is not None and sim > 0:
                stats.after_delta_bytes += effective_unique_size(chunk, base.data)
            else:
                stats.after_delta_bytes += effective_unique_size(chunk, None)
        prev = end

    stats.logical_bytes = len(data)
    stats.unique_bytes = store.unique_bytes
    # Exact hits contribute 0 new unique payload; after_delta only counted uniques.
    stats.restore_containers = len(recipe_ids)
    stats.elapsed_s = perf_counter() - t0
    return store, stats, ends


def ingest_versions(
    versions: list[bytes],
    *,
    mode: str,
    do_delta: bool = True,
) -> tuple[ChunkStore, IngestStats]:
    store = ChunkStore()
    acc = IngestStats(name=mode)
    t0 = perf_counter()
    for blob in versions:
        store, one, _ = ingest_stream(blob, mode=mode, store=store, do_delta=do_delta)
        acc.logical_bytes += one.logical_bytes
        acc.chunks += one.chunks
        acc.exact_hits += one.exact_hits
        acc.migrated_cuts += one.migrated_cuts
        acc.chunk_size_sum += one.chunk_size_sum
        acc.after_delta_bytes += one.after_delta_bytes
        acc.restore_containers = max(acc.restore_containers, one.restore_containers)
    acc.unique_bytes = store.unique_bytes
    acc.elapsed_s = perf_counter() - t0
    acc.restore_containers = len({c for c in range(len(store.containers))})
    return store, acc
