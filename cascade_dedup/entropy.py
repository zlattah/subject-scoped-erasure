"""Cheap local entropy used by adaptive SeqCDC skip and the CDC mux."""

from __future__ import annotations

import math


def bigram_entropy(data: bytes) -> float:
    """Shannon entropy of adjacent-byte pairs, in bits (0 .. ~16)."""
    n = len(data)
    if n < 2:
        return 0.0
    counts: dict[int, int] = {}
    total = n - 1
    for i in range(total):
        key = (data[i] << 8) | data[i + 1]
        counts[key] = counts.get(key, 0) + 1
    h = 0.0
    inv = 1.0 / total
    for c in counts.values():
        p = c * inv
        h -= p * math.log2(p)
    return h


def unigram_entropy(data: bytes) -> float:
    """Shannon entropy of bytes, in bits (0 .. 8)."""
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    h = 0.0
    n = len(data)
    for c in counts:
        if c:
            p = c / n
            h -= p * math.log2(p)
    return h
