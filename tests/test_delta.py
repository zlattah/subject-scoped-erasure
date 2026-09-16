from cascade_dedup.delta import compressed_size, delta_size, effective_unique_size


def test_delta_beats_plain_compress_on_similar_bytes() -> None:
    base = b"X" * 4000 + b"payload-base-line"
    chunk = b"X" * 4000 + b"payload-base-lite"
    assert delta_size(chunk, base) < compressed_size(chunk)
    assert effective_unique_size(chunk, base) <= compressed_size(chunk)
