"""Synthetic versioned corpora for FastCDC vs RAD-CDC."""

from __future__ import annotations

import random


def versioned_blobs(
    *,
    n_versions: int = 8,
    base_size: int = 1_048_576,
    seed: int = 0,
    mutate_frac: float = 0.04,
    inserts_per_version: int = 3,
    insert_bytes: int = 700,
    boundary_noise: bool = True,
    avg_hint: int = 8192,
) -> list[bytes]:
    """Build a small backup-like timeline.

    Each version keeps most bytes, mutates some pages, inserts a few records,
    and optionally perturbs bytes near likely CDC boundaries so FastCDC cuts
    can drift on near-duplicates (the case cut-migration targets).
    """
    rng = random.Random(seed)
    current = bytearray(rng.randbytes(base_size))
    versions = [bytes(current)]
    for _ in range(1, n_versions):
        data = bytearray(current)
        page = 4096
        n_pages = max(len(data) // page, 1)
        n_mut = max(int(n_pages * mutate_frac), 1)
        for _m in range(n_mut):
            pg = rng.randrange(n_pages)
            off = pg * page
            span = min(page, len(data) - off)
            data[off : off + span] = rng.randbytes(span)
        if boundary_noise:
            pos = avg_hint
            while pos < len(data) - 64:
                if rng.random() < 0.35:
                    jitter = rng.randbytes(24)
                    data[pos - 12 : pos + 12] = jitter
                pos += avg_hint
        for _ins in range(inserts_per_version):
            at = rng.randrange(len(data))
            data[at:at] = rng.randbytes(insert_bytes)
        current = data
        versions.append(bytes(current))
    return versions


def duplicate_pair(size: int = 200_000, seed: int = 1) -> tuple[bytes, bytes]:
    rng = random.Random(seed)
    blob = rng.randbytes(size)
    return blob, blob
