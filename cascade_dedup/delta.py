"""Cheap delta size using zlib's preset dictionary (the similar base chunk)."""

from __future__ import annotations

import zlib


def compressed_size(data: bytes) -> int:
    return len(zlib.compress(data, 6))


def delta_size(chunk: bytes, base: bytes) -> int:
    """Bytes needed to store chunk given base, using zlib+zdict as a delta proxy."""
    if not chunk:
        return 0
    if not base:
        return compressed_size(chunk)
    compressor = zlib.compressobj(6, zlib.DEFLATED, 15, 8, zlib.Z_DEFAULT_STRATEGY, zdict=base)
    payload = compressor.compress(chunk) + compressor.flush()
    return len(payload)


def effective_unique_size(chunk: bytes, base: bytes | None, min_gain: float = 0.10) -> int:
    raw = compressed_size(chunk)
    if base is None:
        return raw
    d = delta_size(chunk, base)
    if d <= raw * (1.0 - min_gain):
        return d
    return raw
