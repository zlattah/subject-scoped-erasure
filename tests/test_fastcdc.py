from cascade_dedup.chunking import CDCParams, FastCDC, fingerprint


def test_fastcdc_respects_min_max() -> None:
    params = CDCParams(min_size=64, avg_size=256, max_size=1024)
    cdc = FastCDC(params)
    data = bytes(range(256)) * 40
    prev = 0
    for end in cdc.cuts(data):
        size = end - prev
        if end != len(data):
            assert size >= params.min_size
            assert size <= params.max_size
        prev = end
    assert prev == len(data)


def test_fastcdc_deterministic() -> None:
    cdc = FastCDC()
    data = b"abc" * 50_000
    assert cdc.cuts(data) == cdc.cuts(data)


def test_identical_content_same_cuts() -> None:
    cdc = FastCDC()
    a = bytes([7]) * 80_000
    assert cdc.cuts(a) == cdc.cuts(bytes(a))


def test_chunks_reconstruct() -> None:
    cdc = FastCDC()
    data = bytes(range(256)) * 100
    assert b"".join(cdc.chunks(data)) == data


def test_fingerprint_changes_with_bytes() -> None:
    assert fingerprint(b"aaaa") != fingerprint(b"aaab")
