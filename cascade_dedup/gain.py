"""Encode-free delta-gain predictor.

Palantir / BePro *encode then filter*: they pay a full delta encode and throw
the result away if the gain is below a threshold. The leftover is to *predict*
that gain from sketches and length, and skip the encode when the prediction is
below the same threshold.

This is a tiny OLS model (plus a frozen heuristic fallback). It is not DeepSketch.
Train on one corpus seed and test on another.
"""

from __future__ import annotations

from dataclasses import dataclass

from cascade_dedup.chunking import FastCDC, finesse_sketch, fingerprint, sketch, sketch_similarity
from cascade_dedup.delta import compressed_size, delta_size
from cascade_dedup.entropy import unigram_entropy
from cascade_dedup.store import ChunkStore


def _length_sim(a: int, b: int) -> float:
    m = max(a, b, 1)
    return 1.0 - abs(a - b) / m


def _entropy_sim(a: bytes, b: bytes) -> float:
    ha = unigram_entropy(a)
    hb = unigram_entropy(b)
    return 1.0 - abs(ha - hb) / 8.0


def feature_vector(chunk: bytes, base: bytes, pos_sim: float, finesse_sim: float) -> tuple[float, ...]:
    return (
        pos_sim,
        finesse_sim,
        _length_sim(len(chunk), len(base)),
        _entropy_sim(chunk, base),
    )


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(n):
        pivot = i
        for r in range(i + 1, n):
            if abs(m[r][i]) > abs(m[pivot][i]):
                pivot = r
        m[i], m[pivot] = m[pivot], m[i]
        diag = m[i][i]
        if abs(diag) < 1e-12:
            diag = 1e-12
            m[i][i] = diag
        inv = 1.0 / diag
        for c in range(i, n + 1):
            m[i][c] *= inv
        for r in range(n):
            if r == i:
                continue
            f = m[r][i]
            if f == 0.0:
                continue
            for c in range(i, n + 1):
                m[r][c] -= f * m[i][c]
    return [m[i][n] for i in range(n)]


def fit_ols(x: list[tuple[float, ...]], y: list[float], ridge: float = 1e-2) -> tuple[tuple[float, ...], float]:
    if not x:
        raise ValueError("no rows")
    k = len(x[0]) + 1
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for row, yi in zip(x, y):
        xr = (1.0, *row)
        for i in range(k):
            xty[i] += xr[i] * yi
            for j in range(k):
                xtx[i][j] += xr[i] * xr[j]
    for i in range(k):
        xtx[i][i] += ridge
    w = _solve_linear(xtx, xty)
    return tuple(w[1:]), w[0]


@dataclass
class GainPredictor:
    """Predict (1 - delta_size/raw_size). Encode only if prediction >= threshold."""

    weights: tuple[float, ...] = (0.55, 0.35, 0.15, 0.05)
    intercept: float = -0.12
    threshold: float = 0.10
    n_train: int = 0
    source: str = "heuristic"

    def predict(self, chunk: bytes, base: bytes, pos_sim: float, finesse_sim: float) -> float:
        feats = feature_vector(chunk, base, pos_sim, finesse_sim)
        acc = self.intercept
        for w, f in zip(self.weights, feats):
            acc += w * f
        if acc < 0.0:
            return 0.0
        if acc > 1.0:
            return 1.0
        return acc

    def should_encode(self, chunk: bytes, base: bytes, pos_sim: float, finesse_sim: float) -> bool:
        return self.predict(chunk, base, pos_sim, finesse_sim) >= self.threshold

    @classmethod
    def heuristic(cls, threshold: float = 0.10) -> GainPredictor:
        return cls(threshold=threshold, source="heuristic")


def collect_delta_examples(versions: list[bytes]) -> tuple[list[tuple[float, ...]], list[float]]:
    """Walk a timeline with FastCDC; record actual zlib-dict gain vs features."""
    store = ChunkStore()
    chunker = FastCDC()
    xs: list[tuple[float, ...]] = []
    ys: list[float] = []
    for blob in versions:
        prev = 0
        for end in chunker.cuts(blob):
            chunk = blob[prev:end]
            prev = end
            fp = fingerprint(chunk)
            if store.lookup(fp) is not None:
                continue
            pos_sk = sketch(chunk)
            fin_sk = finesse_sketch(chunk)
            base, pos_sim = store.best_similar(pos_sk)
            store.put_unique(chunk)
            if base is None or pos_sim <= 0:
                continue
            raw = compressed_size(chunk)
            if raw <= 0:
                continue
            d = delta_size(chunk, base.data)
            gain = max(0.0, 1.0 - d / raw)
            fin_sim = sketch_similarity(fin_sk, finesse_sketch(base.data))
            xs.append(feature_vector(chunk, base.data, pos_sim, fin_sim))
            ys.append(gain)
    return xs, ys


def train_gain_predictor(
    versions: list[bytes],
    *,
    threshold: float = 0.10,
    min_examples: int = 12,
) -> GainPredictor:
    xs, ys = collect_delta_examples(versions)
    if len(xs) < min_examples:
        pred = GainPredictor.heuristic(threshold=threshold)
        pred.n_train = len(xs)
        pred.source = f"heuristic(n={len(xs)})"
        return pred
    weights, intercept = fit_ols(xs, ys)
    return GainPredictor(
        weights=weights,
        intercept=intercept,
        threshold=threshold,
        n_train=len(xs),
        source="ols",
    )
