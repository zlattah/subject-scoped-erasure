"""Tiny logistic models for SeqCDC skip and Tmax-rescue.

This is not DeepSketch and not a learned rolling hash. SeqCDC still finds
monotonic runs. At two published decision points a frozen logistic model
answers:

- skip: jump SkipSize, or refuse the jump and keep scanning
- Tmax: emit Tmax, or take the weak (SeqLength-2) cut nearest Tavg

Train on one corpus seed; test on another. Labels are myopic store oracles
built while ingesting the train timeline with *vanilla* SeqCDC (always jump,
never rescue), so the model is not trained on its own cuts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from cascade_dedup.chunking import CDCParams, fingerprint, sketch
from cascade_dedup.delta import effective_unique_size
from cascade_dedup.entropy import bigram_entropy, max_eq_run_frac, printable_ratio, unigram_entropy
from cascade_dedup.seqcdc import SeqCDC, SeqParams
from cascade_dedup.store import ChunkStore


def _sigmoid(z: float) -> float:
    if z >= 30.0:
        return 1.0
    if z <= -30.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def fit_logreg(
    x: list[tuple[float, ...]],
    y: list[int],
    *,
    lr: float = 0.4,
    epochs: int = 250,
    l2: float = 1e-2,
) -> tuple[tuple[float, ...], float]:
    """Binary logistic regression with intercept and class-balanced loss."""
    if not x:
        raise ValueError("no rows")
    n = len(x)
    k = len(x[0]) + 1
    n_pos = sum(1 for yi in y if yi)
    n_neg = n - n_pos
    w_pos = n / (2.0 * n_pos) if n_pos else 1.0
    w_neg = n / (2.0 * n_neg) if n_neg else 1.0
    w = [0.0] * k
    for _ in range(epochs):
        grad = [0.0] * k
        for row, yi in zip(x, y):
            xr = (1.0, *row)
            z = sum(a * b for a, b in zip(w, xr))
            err = _sigmoid(z) - yi
            scale = (w_pos if yi else w_neg) * err
            for i in range(k):
                grad[i] += scale * xr[i]
        inv_n = 1.0 / n
        for i in range(k):
            w[i] -= lr * (grad[i] * inv_n + l2 * w[i])
    return tuple(w[1:]), w[0]


def _window(data: bytes, pos: int, start: int, n: int = 64) -> bytes:
    lo = max(start, pos - n)
    return data[lo:pos]


def skip_features(data: bytes, start: int, pos: int, skips: int, params: CDCParams) -> tuple[float, ...]:
    win = _window(data, pos, start)
    return (
        min(bigram_entropy(win) / 6.0, 1.0),
        min(unigram_entropy(win) / 8.0, 1.0),
        min((pos - start) / params.max_size, 1.0),
        printable_ratio(win),
        max_eq_run_frac(win),
        min(skips / 8.0, 1.0),
    )


def tmax_features(
    data: bytes,
    start: int,
    weak: int,
    max_end: int,
    skips: int,
    params: CDCParams,
) -> tuple[float, ...]:
    win = _window(data, weak, start)
    span = max(params.max_size - params.min_size, 1)
    weak_len = weak - start
    return (
        min(bigram_entropy(win) / 6.0, 1.0),
        min(unigram_entropy(win) / 8.0, 1.0),
        min(weak_len / params.avg_size, 2.0) / 2.0,
        min(abs(weak_len - params.avg_size) / span, 1.0),
        min((max_end - start) / params.max_size, 1.0),
        printable_ratio(win),
        max_eq_run_frac(win),
        min(skips / 8.0, 1.0),
    )


def _chunk_cost(chunk: bytes, store: ChunkStore) -> int:
    if not chunk:
        return 0
    if store.lookup(fingerprint(chunk)) is not None:
        return 0
    base, sim = store.best_similar(sketch(chunk))
    return effective_unique_size(chunk, None if base is None or sim <= 0 else base.data)


def _look_ahead_seq_cut(
    data: bytes,
    lo: int,
    hi: int,
    seq_length: int,
    increasing: bool,
) -> int | None:
    if hi - lo < 2:
        return None
    run = 0
    i = lo + 1
    while i < hi:
        diff = data[i] - data[i - 1]
        if diff == 0:
            i += 1
            continue
        if (diff > 0) == increasing:
            run += 1
            if run >= seq_length:
                return i + 1
        else:
            run = 0
        i += 1
    return None


def _oracle_skip(
    data: bytes,
    start: int,
    pos: int,
    skip: int,
    max_end: int,
    seq: SeqParams,
    store: ChunkStore,
) -> int:
    """1 = jump is safe; 0 = hold, a cut in the skipped span would hit the store."""
    hi = min(pos + skip, max_end, len(data))
    cut = _look_ahead_seq_cut(data, pos, hi, seq.seq_length, seq.increasing)
    if cut is None or cut <= start:
        return 1
    chunk = data[start:cut]
    if store.lookup(fingerprint(chunk)) is not None:
        return 0
    _, sim = store.best_similar(sketch(chunk))
    return 0 if sim >= 0.5 else 1


def _oracle_tmax(weak_chunk: bytes, tmax_chunk: bytes, store: ChunkStore) -> int:
    """1 = take the weak cut; 0 = keep Tmax."""
    cw = _chunk_cost(weak_chunk, store)
    ct = _chunk_cost(tmax_chunk, store)
    if cw == 0 and ct > 0:
        return 1
    if ct == 0 and cw > 0:
        return 0
    if ct == 0 and cw == 0:
        return 0
    wl = max(len(weak_chunk), 1)
    tl = max(len(tmax_chunk), 1)
    return 1 if (cw / wl) < (ct / tl) - 0.02 else 0


def _calibrate_threshold(xs: list[tuple[float, ...]], ys: list[int], weights: tuple[float, ...], intercept: float) -> float:
    scores = [intercept + sum(w * f for w, f in zip(weights, row)) for row in xs]
    probs = [_sigmoid(s) for s in scores]
    n_pos = sum(ys)
    n_neg = len(ys) - n_pos
    if n_pos == 0:
        return 1.1
    if n_neg == 0:
        return 0.0
    best_t = 0.5
    best = -1.0
    for t in (i / 20.0 for i in range(1, 20)):
        tp = fp = tn = fn = 0
        for p, yi in zip(probs, ys):
            pred = p >= t
            if pred and yi:
                tp += 1
            elif pred and not yi:
                fp += 1
            elif (not pred) and yi:
                fn += 1
            else:
                tn += 1
        acc = (tp + tn) / len(ys)
        # Prefer a threshold that uses both classes if accuracy ties.
        both = 1.0 if (tp + fp) > 0 and (tn + fn) > 0 else 0.0
        score = acc + 0.01 * both
        if score > best:
            best = score
            best_t = t
    return best_t


@dataclass
class LogisticHead:
    weights: tuple[float, ...]
    intercept: float
    threshold: float
    n_train: int = 0
    n_pos: int = 0
    source: str = "logistic"

    def prob(self, feats: tuple[float, ...]) -> float:
        z = self.intercept + sum(w * f for w, f in zip(self.weights, feats))
        return _sigmoid(z)

    def predict(self, feats: tuple[float, ...]) -> bool:
        return self.prob(feats) >= self.threshold

    @classmethod
    def constant(cls, value: bool, n_train: int = 0, n_pos: int = 0) -> LogisticHead:
        return cls(
            weights=(0.0,),
            intercept=10.0 if value else -10.0,
            threshold=0.5,
            n_train=n_train,
            n_pos=n_pos,
            source=f"constant({int(value)})",
        )


def _fit_head(xs: list[tuple[float, ...]], ys: list[int], min_examples: int) -> LogisticHead:
    n_pos = sum(ys)
    n_neg = len(ys) - n_pos
    if len(xs) < min_examples or n_pos == 0 or n_neg == 0:
        # No contrast: fall back to the hand rule that already moved SeqCDC (always rescue)
        # for Tmax, and to published SeqCDC (always jump) for skip — caller chooses.
        return LogisticHead.constant(n_pos >= n_neg, n_train=len(xs), n_pos=n_pos)
    weights, intercept = fit_logreg(xs, ys)
    thresh = _calibrate_threshold(xs, ys, weights, intercept)
    return LogisticHead(
        weights=weights,
        intercept=intercept,
        threshold=thresh,
        n_train=len(xs),
        n_pos=n_pos,
        source="logistic",
    )


@dataclass
class LearnedSeqPolicy:
    """Frozen skip + Tmax heads. Byte-local features only at inference."""

    skip_head: LogisticHead
    tmax_head: LogisticHead
    params: CDCParams = field(default_factory=CDCParams)
    seq: SeqParams = field(default_factory=SeqParams)
    skip_jumps: int = 0
    skip_holds: int = 0
    rescues: int = 0
    tmax_keeps: int = 0

    def reset_counts(self) -> None:
        self.skip_jumps = 0
        self.skip_holds = 0
        self.rescues = 0
        self.tmax_keeps = 0

    def jump_size(self, data: bytes, start: int, pos: int, skips: int, default: int) -> int:
        if self.skip_head.source.startswith("constant"):
            take = self.skip_head.intercept > 0
        else:
            take = self.skip_head.predict(skip_features(data, start, pos, skips, self.params))
        if take:
            self.skip_jumps += 1
            return default
        self.skip_holds += 1
        return 0

    def use_weak(self, data: bytes, start: int, weak: int, max_end: int, skips: int) -> bool:
        if self.tmax_head.source.startswith("constant"):
            take = self.tmax_head.intercept > 0
        else:
            take = self.tmax_head.predict(tmax_features(data, start, weak, max_end, skips, self.params))
        if take:
            self.rescues += 1
        else:
            self.tmax_keeps += 1
        return take


class _CollectPolicy:
    """Vanilla SeqCDC behaviour while recording oracles against the current store."""

    def __init__(self, store: ChunkStore, params: CDCParams, seq: SeqParams) -> None:
        self.store = store
        self.params = params
        self.seq = seq
        self.skip_x: list[tuple[float, ...]] = []
        self.skip_y: list[int] = []
        self.tmax_x: list[tuple[float, ...]] = []
        self.tmax_y: list[int] = []

    def jump_size(self, data: bytes, start: int, pos: int, skips: int, default: int) -> int:
        max_end = start + min(len(data) - start, self.params.max_size)
        self.skip_x.append(skip_features(data, start, pos, skips, self.params))
        self.skip_y.append(
            _oracle_skip(data, start, pos, default, max_end, self.seq, self.store)
        )
        return default

    def use_weak(self, data: bytes, start: int, weak: int, max_end: int, skips: int) -> bool:
        self.tmax_x.append(tmax_features(data, start, weak, max_end, skips, self.params))
        weak_chunk = data[start:weak]
        tmax_chunk = data[start:max_end]
        self.tmax_y.append(_oracle_tmax(weak_chunk, tmax_chunk, self.store))
        return False


def train_seq_policy(
    versions: list[bytes],
    *,
    params: CDCParams | None = None,
    seq: SeqParams | None = None,
    min_examples: int = 12,
) -> LearnedSeqPolicy:
    params = params or CDCParams()
    seq = seq or SeqParams()
    store = ChunkStore()
    collector = _CollectPolicy(store, params, seq)
    cdc = SeqCDC(params, seq, policy=collector)
    for blob in versions:
        start = 0
        n = len(blob)
        while start < n:
            end = cdc.next_cut(blob, start)
            chunk = blob[start:end]
            if store.lookup(fingerprint(chunk)) is None:
                store.put_unique(chunk)
            start = end
    skip_head = _fit_head(collector.skip_x, collector.skip_y, min_examples)
    # Tmax: if no contrast, prefer always-rescue (the hand tweak that helped SeqCDC).
    if collector.tmax_x and sum(collector.tmax_y) == len(collector.tmax_y):
        tmax_head = LogisticHead.constant(True, n_train=len(collector.tmax_x), n_pos=len(collector.tmax_y))
    elif collector.tmax_x and sum(collector.tmax_y) == 0:
        tmax_head = LogisticHead.constant(False, n_train=len(collector.tmax_x), n_pos=0)
    else:
        tmax_head = _fit_head(collector.tmax_x, collector.tmax_y, min_examples)
        if tmax_head.source.startswith("constant") and collector.tmax_y:
            tmax_head = LogisticHead.constant(
                sum(collector.tmax_y) >= len(collector.tmax_y) / 2,
                n_train=len(collector.tmax_x),
                n_pos=sum(collector.tmax_y),
            )
    # Skip: if no contrast, keep published always-jump.
    if skip_head.source.startswith("constant"):
        skip_head = LogisticHead.constant(
            True if not collector.skip_y or sum(collector.skip_y) >= len(collector.skip_y) / 2 else False,
            n_train=len(collector.skip_x),
            n_pos=sum(collector.skip_y),
        )
        skip_head.source = f"constant({1 if skip_head.intercept > 0 else 0})"
    return LearnedSeqPolicy(skip_head=skip_head, tmax_head=tmax_head, params=params, seq=seq)
