"""Gear-hash FastCDC (content-only cuts).

This follows the FastCDC normalized-chunking pattern (Xia et al., ATC 2016):
Gear rolling hash, skip judgment until Tmin, use a harder mask until Tavg and
a softer mask until Tmax.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass


def _gear_table(seed: int = 2016) -> tuple[int, ...]:
    rng = random.Random(seed)
    return tuple(rng.getrandbits(64) for _ in range(256))


GEAR = _gear_table()


def fingerprint(data: bytes) -> bytes:
    return hashlib.blake2s(data, digest_size=16).digest()


def sketch(data: bytes, k: int = 4) -> tuple[int, ...]:
    """Positional superfeature: k windows spread across the chunk."""
    if not data:
        return (0,) * k
    features: list[int] = []
    n = len(data)
    win = min(32, n)
    for i in range(k):
        pos = 0 if n == win else (i * (n - win)) // max(k - 1, 1)
        window = data[pos : pos + win]
        features.append(int.from_bytes(hashlib.blake2s(window, digest_size=8).digest(), "little"))
    return tuple(features)


def sketch_similarity(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    if not a:
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


def mask_bits_for_avg(avg_size: int) -> int:
    bits = max(int(avg_size).bit_length() - 1, 4)
    return bits


@dataclass(frozen=True)
class CDCParams:
    min_size: int = 2048
    avg_size: int = 8192
    max_size: int = 65536

    def __post_init__(self) -> None:
        if not (0 < self.min_size <= self.avg_size <= self.max_size):
            raise ValueError("require 0 < min_size <= avg_size <= max_size")


class FastCDC:
    """Content-only Gear CDC with normalized masks."""

    def __init__(self, params: CDCParams | None = None) -> None:
        self.params = params or CDCParams()
        bits = mask_bits_for_avg(self.params.avg_size)
        self.mask_hard = (1 << bits) - 1
        self.mask_easy = (1 << max(bits - 1, 1)) - 1

    def next_cut(self, data: bytes, start: int) -> int:
        return self._scan(data, start, collect_backups=False)[0]

    def next_cut_with_backups(self, data: bytes, start: int, limit: int = 8) -> tuple[int, list[int]]:
        return self._scan(data, start, collect_backups=True, backup_limit=limit)

    def cuts(self, data: bytes) -> list[int]:
        """Return exclusive end offsets of each chunk."""
        ends: list[int] = []
        start = 0
        n = len(data)
        while start < n:
            end = self.next_cut(data, start)
            ends.append(end)
            start = end
        return ends

    def chunks(self, data: bytes) -> list[bytes]:
        ends = self.cuts(data)
        out: list[bytes] = []
        prev = 0
        for end in ends:
            out.append(data[prev:end])
            prev = end
        return out

    def _scan(
        self,
        data: bytes,
        start: int,
        *,
        collect_backups: bool,
        backup_limit: int = 8,
    ) -> tuple[int, list[int]]:
        n = len(data)
        remaining = n - start
        if remaining <= 0:
            return n, []
        p = self.params
        if remaining <= p.min_size:
            return n, []

        max_end = start + min(remaining, p.max_size)
        avg_end = start + min(remaining, p.avg_size)
        min_end = start + p.min_size

        h = 0
        natural = max_end
        backups: list[int] = []
        i = start
        while i < max_end:
            h = ((h << 1) & ((1 << 64) - 1)) + GEAR[data[i]]
            i += 1
            if i < min_end:
                continue
            mask = self.mask_hard if i < avg_end else self.mask_easy
            if (h & mask) == 0:
                if natural == max_end:
                    natural = i
                    if not collect_backups:
                        return natural, backups
                elif collect_backups and len(backups) < backup_limit and i != natural:
                    backups.append(i)
        if natural == max_end:
            natural = max_end
        return natural, backups
