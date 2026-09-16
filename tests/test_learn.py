from cascade_dedup.corpus import versioned_blobs
from cascade_dedup.learn import LogisticHead, LearnedSeqPolicy, fit_logreg, train_seq_policy
from cascade_dedup.pipeline import ingest_versions
from cascade_dedup.seqcdc import SeqCDC, SeqParams


def test_logreg_separates_and() -> None:
    xs = [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)] * 15
    ys = [0, 0, 0, 1] * 15
    weights, intercept = fit_logreg(xs, ys, epochs=400, lr=0.5, l2=1e-4)

    def pred(a: float, b: float) -> float:
        z = intercept + weights[0] * a + weights[1] * b
        import math

        return 1.0 / (1.0 + math.exp(-z))

    assert pred(1.0, 1.0) > 0.5
    assert pred(0.0, 0.0) < 0.5
    assert pred(1.0, 0.0) < 0.6


def test_learned_policy_tiles() -> None:
    train = versioned_blobs(n_versions=4, base_size=60_000, seed=21, profile="mixed")
    test = versioned_blobs(n_versions=1, base_size=60_000, seed=7, profile="mixed")[0]
    policy = train_seq_policy(train, min_examples=4)
    cdc = SeqCDC(policy=policy)
    assert b"".join(cdc.chunks(test)) == test
    assert policy.tmax_head.n_train >= 0
    assert policy.skip_head.n_train >= 0


def test_learned_ingest_runs() -> None:
    train = versioned_blobs(n_versions=3, base_size=40_000, seed=5, profile="mixed")
    test = versioned_blobs(n_versions=3, base_size=40_000, seed=8, profile="mixed")
    policy = train_seq_policy(train, min_examples=4)
    _, stats = ingest_versions(test, mode="seqcdc-learn", do_delta=True, seq_policy=policy)
    assert stats.chunks > 0
    assert stats.unique_bytes <= stats.logical_bytes


def test_constant_heads_match_hand_rules() -> None:
    data = versioned_blobs(n_versions=1, base_size=80_000, seed=3, profile="mixed")[0]
    always_tmax = LearnedSeqPolicy(
        skip_head=LogisticHead.constant(True),
        tmax_head=LogisticHead.constant(True),
    )
    never_rescue = LearnedSeqPolicy(
        skip_head=LogisticHead.constant(True),
        tmax_head=LogisticHead.constant(False),
    )
    assert SeqCDC(policy=always_tmax).cuts(data) == SeqCDC(tmax_rescue=True).cuts(data)
    assert SeqCDC(policy=never_rescue).cuts(data) == SeqCDC().cuts(data)


class _HoldAll:
    def jump_size(self, data, start, pos, skips, default) -> int:  # noqa: ANN001
        return 0

    def use_weak(self, data, start, weak, max_end, skips) -> bool:  # noqa: ANN001
        return False


def test_skip_hold_policy_refuses_jumps() -> None:
    data = bytes([(255 - (i % 256)) for i in range(40_000)])
    seq = SeqParams(seq_length=8, skip_trigger=8, skip_size=64)
    held = SeqCDC(seq=seq, policy=_HoldAll())
    vanilla = SeqCDC(seq=seq)
    held.cuts(data)
    vanilla.cuts(data)
    assert held.skip_hold_count > 0
    assert held.skip_count == 0
    assert vanilla.skip_count > 0
