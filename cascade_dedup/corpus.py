"""Synthetic versioned corpora for FastCDC vs RAD-CDC."""

from __future__ import annotations

import random

# 32-byte prefix used by mixed-profile "header" pages so positional sketches
# can match while the tails (and zlib-dict gain) do not.
HEADER_MAGIC = b"CASCADE-DEDUP-HDR\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
assert len(HEADER_MAGIC) == 32


def _mixed_base(rng: random.Random, size: int) -> bytearray:
    """Mix structured records, random pages, descending ramps, and shared headers."""
    buf = bytearray(size)
    pos = 0
    page = 4096
    while pos < size:
        span = min(page, size - pos)
        roll = rng.randrange(100)
        if roll < 25:
            # Low-entropy repeats so the mux has a FastCDC side (2-gram H ≪ 3.5).
            rec_len = rng.choice((1, 2, 4, 8))
            rec = bytes(rng.randrange(256) for _ in range(rec_len))
            for i in range(span):
                buf[pos + i] = rec[i % rec_len]
        elif roll < 50:
            rec_len = rng.choice((64, 96, 128))
            rec = bytes(rng.randrange(32, 126) for _ in range(rec_len))
            for i in range(span):
                buf[pos + i] = rec[i % rec_len]
        elif roll < 75:
            buf[pos : pos + span] = rng.randbytes(span)
        elif roll < 85:
            start_v = rng.randrange(256)
            for i in range(span):
                buf[pos + i] = (start_v - i) & 0xFF
        else:
            chunk = HEADER_MAGIC + rng.randbytes(max(span - len(HEADER_MAGIC), 0))
            buf[pos : pos + span] = chunk[:span]
        pos += span
    return buf


def _mutate(
    data: bytearray,
    rng: random.Random,
    *,
    mutate_frac: float,
    inserts_per_version: int,
    insert_bytes: int,
    boundary_noise: bool,
    avg_hint: int,
    profile: str,
) -> None:
    page = 4096
    n_pages = max(len(data) // page, 1)
    n_mut = max(int(n_pages * mutate_frac), 1)
    for _m in range(n_mut):
        pg = rng.randrange(n_pages)
        off = pg * page
        span = min(page, len(data) - off)
        data[off : off + span] = rng.randbytes(span)
    if profile == "mixed":
        # Keep a 32-byte prefix and scramble the tail → sketch hit, weak delta.
        for _ in range(4):
            if len(data) < 64:
                break
            off = rng.randrange(len(data) - 48)
            span = min(2048, len(data) - off)
            if span > 40:
                data[off + 32 : off + span] = rng.randbytes(span - 32)
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
    profile: str = "random",
) -> list[bytes]:
    """Build a small backup-like timeline.

    Each version keeps most bytes, mutates some pages, inserts a few records,
    and optionally perturbs bytes near likely CDC boundaries so FastCDC cuts
    can drift on near-duplicates (the case cut-migration targets).

    ``profile="random"`` is uniform bytes (the original RAD-CDC corpus).
    ``profile="mixed"`` adds records, descending ramps, and shared headers so
    skip / mux / encode-filter have something to do.
    """
    if profile not in {"random", "mixed"}:
        raise ValueError(f"unknown profile {profile!r}")
    rng = random.Random(seed)
    current = _mixed_base(rng, base_size) if profile == "mixed" else bytearray(rng.randbytes(base_size))
    versions = [bytes(current)]
    for _ in range(1, n_versions):
        data = bytearray(current)
        _mutate(
            data,
            rng,
            mutate_frac=mutate_frac,
            inserts_per_version=inserts_per_version,
            insert_bytes=insert_bytes,
            boundary_noise=boundary_noise,
            avg_hint=avg_hint,
            profile=profile,
        )
        current = data
        versions.append(bytes(current))
    return versions


def duplicate_pair(size: int = 200_000, seed: int = 1) -> tuple[bytes, bytes]:
    rng = random.Random(seed)
    blob = rng.randbytes(size)
    return blob, blob
