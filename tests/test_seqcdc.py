from cascade_dedup.chunking import CDCParams, fingerprint
from cascade_dedup.corpus import versioned_blobs
from cascade_dedup.seqcdc import SeqCDC, SeqParams
from cascade_dedup.mux import EntropyMux


def test_seqcdc_respects_min_max() -> None:
    params = CDCParams(min_size=64, avg_size=256, max_size=1024)
    seq = SeqParams(seq_length=3, skip_trigger=20, skip_size=32)
    cdc = SeqCDC(params, seq)
    data = bytes(range(256)) * 40
    prev = 0
    for end in cdc.cuts(data):
        size = end - prev
        if end != len(data):
            assert size >= params.min_size
            assert size <= params.max_size
        prev = end
    assert prev == len(data)


def test_seqcdc_deterministic_and_reconstructs() -> None:
    cdc = SeqCDC()
    data = b"abc" * 50_000 + bytes(range(256)) * 200
    assert cdc.cuts(data) == cdc.cuts(data)
    assert b"".join(cdc.chunks(data)) == data


def test_adaptive_skip_tiles() -> None:
    data = versioned_blobs(n_versions=1, base_size=90_000, seed=6)[0]
    cdc = SeqCDC(adaptive_skip=True, tmax_rescue=True)
    assert b"".join(cdc.chunks(data)) == data


def test_fused_fingerprint_matches_blake2s() -> None:
    data = versioned_blobs(n_versions=1, base_size=80_000, seed=4)[0]
    fused = SeqCDC(fuse_fingerprint=True)
    plain = SeqCDC()
    ends, fps = fused.cuts_with_fps(data)
    assert ends == plain.cuts(data)
    prev = 0
    for end, fp in zip(ends, fps):
        assert fp == fingerprint(data[prev:end])
        prev = end


def test_tmax_rescue_never_emits_past_max() -> None:
    params = CDCParams(min_size=32, avg_size=64, max_size=128)
    # Decreasing sawtooth is hostile to increasing-mode SeqCDC → many Tmax spans.
    data = bytes([255 - (i % 200) for i in range(8_000)])
    cdc = SeqCDC(params, SeqParams(seq_length=8, skip_trigger=8, skip_size=16, tmax_rescue=True))
    prev = 0
    for end in cdc.cuts(data):
        if end != len(data):
            assert end - prev <= params.max_size
        prev = end
    assert prev == len(data)


def test_mux_reconstructs() -> None:
    data = versioned_blobs(n_versions=1, base_size=70_000, seed=1)[0]
    mux = EntropyMux()
    chunks = mux.chunks(data)
    assert b"".join(chunks) == data
    # The file tail (<= Tmin) is not classified as FastCDC or SeqCDC.
    classified = mux.fast_cuts + mux.seq_cuts
    assert classified in {len(chunks) - 1, len(chunks)}
    assert classified >= 1


def test_skip_fires_on_descending_ramp() -> None:
    data = bytes([(255 - (i % 256)) for i in range(40_000)])
    cdc = SeqCDC(seq=SeqParams(seq_length=8, skip_trigger=8, skip_size=64))
    cdc.cuts(data)
    assert cdc.skip_count > 0
    data = versioned_blobs(n_versions=1, base_size=80_000, seed=2, profile="mixed")[0]
    assert b"".join(SeqCDC().chunks(data)) == data
    mux = EntropyMux()
    assert b"".join(mux.chunks(data)) == data
    assert mux.fast_cuts >= 1 or mux.seq_cuts >= 1
