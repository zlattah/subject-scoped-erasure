"""Ingest a byte stream: chunk, exact-dedup, optional post-chunk delta."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from cascade_dedup.chunking import FastCDC, finesse_sketch, fingerprint, sketch, sketch_similarity
from cascade_dedup.delta import compressed_size, effective_unique_size
from cascade_dedup.gain import GainPredictor
from cascade_dedup.mux import EntropyMux
from cascade_dedup.radcdc import RADCDC
from cascade_dedup.seqcdc import SeqCDC
from cascade_dedup.store import CONTAINER_TARGET, ChunkStore


ALL_MODES = (
    "fastcdc",
    "radcdc-exact",
    "radcdc",
    "seqcdc",
    "seqcdc-adapt",
    "seqcdc-fused",
    "mux",
)


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
    chunk_elapsed_s: float = 0.0
    chunk_size_sum: int = 0
    delta_candidates: int = 0
    delta_encodes: int = 0
    delta_kept: int = 0
    predict_skip: int = 0
    mux_fast_cuts: int = 0
    mux_seq_cuts: int = 0

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
        chunk_mib = self.logical_bytes / (1024 * 1024)
        return {
            "name": self.name,
            "logical_MiB": round(chunk_mib, 3),
            "unique_MiB": round(self.unique_bytes / (1024 * 1024), 3),
            "delta_MiB": round(self.after_delta_bytes / (1024 * 1024), 3),
            "dedup_ratio": round(self.dedup_ratio, 3),
            "ratio_with_delta": round(self.reduction_with_delta, 3),
            "chunks": self.chunks,
            "exact_hits": self.exact_hits,
            "migrated_cuts": self.migrated_cuts,
            "delta_encodes": self.delta_encodes,
            "predict_skip": self.predict_skip,
            "avg_chunk": round(self.avg_chunk, 1),
            "chunk_MB_s": round(chunk_mib / self.chunk_elapsed_s, 2) if self.chunk_elapsed_s else 0.0,
            "MB_s": round(chunk_mib / self.elapsed_s, 2) if self.elapsed_s else 0.0,
        }


def _cuts_for_mode(
    mode: str,
    data: bytes,
    store: ChunkStore,
) -> tuple[list[int], list[bytes] | None, EntropyMux | None]:
    if mode == "fastcdc":
        return FastCDC().cuts(data), None, None
    if mode == "seqcdc":
        return SeqCDC().cuts(data), None, None
    if mode == "seqcdc-adapt":
        return SeqCDC(adaptive_skip=True, tmax_rescue=True).cuts(data), None, None
    if mode == "seqcdc-fused":
        ends, fps = SeqCDC(fuse_fingerprint=True).cuts_with_fps(data)
        return ends, fps, None
    if mode == "mux":
        mux = EntropyMux()
        return mux.cuts(data), None, mux
    if mode in {"radcdc", "radcdc-exact"}:
        chunker = RADCDC(migrate="exact" if mode == "radcdc-exact" else "similar")
        return chunker.cuts(data, store), None, None
    raise ValueError(f"unknown mode {mode!r}")


def ingest_stream(
    data: bytes,
    *,
    mode: str,
    store: ChunkStore | None = None,
    do_delta: bool = True,
    delta_policy: str = "encode",
    predictor: GainPredictor | None = None,
) -> tuple[ChunkStore, IngestStats, list[int]]:
    if delta_policy not in {"encode", "predict", "none"}:
        raise ValueError(f"unknown delta_policy {delta_policy!r}")
    store = store or ChunkStore()
    t0 = perf_counter()
    t_chunk = perf_counter()
    ends, fps, mux = _cuts_for_mode(mode, data, store)
    chunk_elapsed = perf_counter() - t_chunk
    natural_tracker = FastCDC() if mode in {"radcdc", "radcdc-exact"} else None
    pred = predictor or GainPredictor.heuristic()

    stats = IngestStats(name=f"{mode}/{delta_policy}" if delta_policy != "encode" else mode)
    if mux is not None:
        stats.mux_fast_cuts = mux.fast_cuts
        stats.mux_seq_cuts = mux.seq_cuts
    recipe_ids: set[int] = set()
    prev = 0
    for idx, end in enumerate(ends):
        chunk = data[prev:end]
        stats.chunks += 1
        stats.chunk_size_sum += len(chunk)
        if natural_tracker is not None:
            natural_end = natural_tracker.next_cut(data, prev)
            if end != natural_end:
                stats.migrated_cuts += 1
        fp = fps[idx] if fps is not None else fingerprint(chunk)
        hit = store.lookup(fp)
        if hit is not None:
            stats.exact_hits += 1
            recipe_ids.add(hit.container_id)
        else:
            pos_sk = sketch(chunk)
            base, pos_sim = store.best_similar(pos_sk)
            stored = store.put_unique(chunk, fp=fp)
            recipe_ids.add(stored.container_id)
            if not do_delta or delta_policy == "none" or base is None or pos_sim <= 0:
                stats.after_delta_bytes += effective_unique_size(chunk, None)
            else:
                stats.delta_candidates += 1
                finesse_sim = sketch_similarity(finesse_sketch(chunk), finesse_sketch(base.data))
                encode = True
                if delta_policy == "predict":
                    encode = pred.should_encode(chunk, base.data, pos_sim, finesse_sim)
                    if not encode:
                        stats.predict_skip += 1
                        stats.after_delta_bytes += compressed_size(chunk)
                if encode:
                    stats.delta_encodes += 1
                    raw = compressed_size(chunk)
                    stored_sz = effective_unique_size(chunk, base.data)
                    if stored_sz < raw:
                        stats.delta_kept += 1
                    stats.after_delta_bytes += stored_sz
        prev = end

    stats.logical_bytes = len(data)
    stats.unique_bytes = store.unique_bytes
    stats.restore_containers = len(recipe_ids)
    stats.chunk_elapsed_s = chunk_elapsed
    stats.elapsed_s = perf_counter() - t0
    return store, stats, ends


def ingest_versions(
    versions: list[bytes],
    *,
    mode: str,
    do_delta: bool = True,
    delta_policy: str = "encode",
    predictor: GainPredictor | None = None,
) -> tuple[ChunkStore, IngestStats]:
    store = ChunkStore()
    label = f"{mode}/{delta_policy}" if delta_policy != "encode" else mode
    acc = IngestStats(name=label)
    t0 = perf_counter()
    for blob in versions:
        store, one, _ = ingest_stream(
            blob,
            mode=mode,
            store=store,
            do_delta=do_delta,
            delta_policy=delta_policy,
            predictor=predictor,
        )
        acc.logical_bytes += one.logical_bytes
        acc.chunks += one.chunks
        acc.exact_hits += one.exact_hits
        acc.migrated_cuts += one.migrated_cuts
        acc.chunk_size_sum += one.chunk_size_sum
        acc.after_delta_bytes += one.after_delta_bytes
        acc.delta_candidates += one.delta_candidates
        acc.delta_encodes += one.delta_encodes
        acc.delta_kept += one.delta_kept
        acc.predict_skip += one.predict_skip
        acc.mux_fast_cuts += one.mux_fast_cuts
        acc.mux_seq_cuts += one.mux_seq_cuts
        acc.chunk_elapsed_s += one.chunk_elapsed_s
        acc.restore_containers = max(acc.restore_containers, one.restore_containers)
    acc.unique_bytes = store.unique_bytes
    acc.elapsed_s = perf_counter() - t0
    acc.restore_containers = len(store.containers)
    return store, acc
