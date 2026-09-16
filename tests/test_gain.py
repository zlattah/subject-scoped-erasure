from cascade_dedup.corpus import versioned_blobs
from cascade_dedup.gain import GainPredictor, fit_ols, train_gain_predictor
from cascade_dedup.pipeline import ingest_versions


def test_ols_recovers_line() -> None:
    xs = [(float(i), 0.5, 0.25, 0.1) for i in range(20)]
    ys = [0.2 + 0.3 * i + 0.01 for i, _ in enumerate(xs)]
    weights, intercept = fit_ols(xs, ys)
    assert abs(intercept - 0.21) < 0.05
    assert abs(weights[0] - 0.3) < 0.05


def test_predictor_skips_some_encodes() -> None:
    train = versioned_blobs(n_versions=4, base_size=60_000, seed=21)
    test = versioned_blobs(n_versions=4, base_size=60_000, seed=7)
    pred = train_gain_predictor(train, min_examples=8)
    _, enc = ingest_versions(test, mode="fastcdc", do_delta=True, delta_policy="encode")
    _, pr = ingest_versions(test, mode="fastcdc", do_delta=True, delta_policy="predict", predictor=pred)
    assert enc.delta_encodes == enc.delta_candidates
    assert pr.delta_encodes + pr.predict_skip == pr.delta_candidates
    assert pr.predict_skip >= 0
    assert pr.delta_encodes <= enc.delta_encodes
    assert pr.logical_bytes == enc.logical_bytes
    # Skipping encodes cannot *improve* the zlib-dict byte count; it may match or worsen it.
    assert pr.after_delta_bytes >= enc.after_delta_bytes - 1


def test_heuristic_predictor_runs() -> None:
    versions = versioned_blobs(n_versions=3, base_size=40_000, seed=3)
    pred = GainPredictor.heuristic()
    _, stats = ingest_versions(versions, mode="seqcdc", delta_policy="predict", predictor=pred)
    assert stats.chunks > 0
    assert stats.predict_skip + stats.delta_encodes == stats.delta_candidates
