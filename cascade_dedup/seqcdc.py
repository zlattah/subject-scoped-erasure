"""SeqCDC (Udayashankar et al., Middleware 2024) plus two leftover knobs.

Baseline SeqCDC is published: cut on a monotonic byte run of SeqLength, skip the
sub-minimum region, and jump SkipSize bytes after SkipTrigger opposing pairs.

Leftover knobs (not in the paper):

- ``adaptive_skip``: map local 2-gram entropy to SkipSize in [skip_min, skip_max]
  instead of a fixed SkipSize.
- ``fuse_fingerprint``: blake2s the emitted chunk during the scan (including
  skipped spans) so ingest does not re-read the chunk to fingerprint it.
- ``tmax_rescue``: if no SeqLength run appears before Tmax, keep the weak
  (SeqLength-2) cut closest to Tavg.
- ``policy``: optional learned skip / Tmax scorer (``cascade_dedup.learn``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cascade_dedup.chunking import CDCParams, fingerprint
from cascade_dedup.entropy import bigram_entropy


@dataclass(frozen=True)
class SeqParams:
    seq_length: int = 6
    skip_trigger: int = 50
    skip_size: int = 256
    increasing: bool = True
    adaptive_skip: bool = False
    skip_min: int = 64
    skip_max: int = 1024
    fuse_fingerprint: bool = False
    tmax_rescue: bool = False
    entropy_window: int = 64


class SeqCDC:
    """Hashless monotonic-sequence CDC.

    Paper Table 1 uses SeqLength=5 for 8 KiB on their datasets. On uniform
    random bytes SeqLength=5 cuts near Tmin (~2.8 KiB). SeqLength=6 matches
    FastCDC's ~8 KiB average on the synthetic corpora in this repo.
    """

    def __init__(
        self,
        params: CDCParams | None = None,
        seq: SeqParams | None = None,
        *,
        adaptive_skip: bool | None = None,
        fuse_fingerprint: bool | None = None,
        tmax_rescue: bool | None = None,
        policy: object | None = None,
    ) -> None:
        self.params = params or CDCParams()
        seq = seq or SeqParams()
        if adaptive_skip is not None or fuse_fingerprint is not None or tmax_rescue is not None:
            seq = SeqParams(
                seq_length=seq.seq_length,
                skip_trigger=seq.skip_trigger,
                skip_size=seq.skip_size,
                increasing=seq.increasing,
                adaptive_skip=seq.adaptive_skip if adaptive_skip is None else adaptive_skip,
                skip_min=seq.skip_min,
                skip_max=seq.skip_max,
                fuse_fingerprint=seq.fuse_fingerprint if fuse_fingerprint is None else fuse_fingerprint,
                tmax_rescue=seq.tmax_rescue if tmax_rescue is None else tmax_rescue,
                entropy_window=seq.entropy_window,
            )
        self.seq = seq
        self.policy = policy
        if self.seq.seq_length < 1:
            raise ValueError("seq_length must be >= 1")
        if self.seq.skip_min < 1 or self.seq.skip_max < self.seq.skip_min:
            raise ValueError("require 0 < skip_min <= skip_max")
        self.skip_count = 0
        self.rescue_count = 0
        self.skip_hold_count = 0

    def next_cut(self, data: bytes, start: int) -> int:
        return self._scan(data, start)[0]

    def next_cut_with_fp(self, data: bytes, start: int) -> tuple[int, bytes]:
        end, fp = self._scan(data, start)
        if fp is None:
            fp = fingerprint(data[start:end])
        return end, fp

    def cuts(self, data: bytes) -> list[int]:
        self.skip_count = 0
        self.rescue_count = 0
        self.skip_hold_count = 0
        if self.policy is not None and hasattr(self.policy, "reset_counts"):
            self.policy.reset_counts()
        ends: list[int] = []
        start = 0
        n = len(data)
        while start < n:
            end = self.next_cut(data, start)
            ends.append(end)
            start = end
        return ends

    def cuts_with_fps(self, data: bytes) -> tuple[list[int], list[bytes]]:
        self.skip_count = 0
        self.rescue_count = 0
        self.skip_hold_count = 0
        if self.policy is not None and hasattr(self.policy, "reset_counts"):
            self.policy.reset_counts()
        ends: list[int] = []
        fps: list[bytes] = []
        start = 0
        n = len(data)
        while start < n:
            end, fp = self.next_cut_with_fp(data, start)
            ends.append(end)
            fps.append(fp)
            start = end
        return ends, fps

    def chunks(self, data: bytes) -> list[bytes]:
        ends = self.cuts(data)
        out: list[bytes] = []
        prev = 0
        for end in ends:
            out.append(data[prev:end])
            prev = end
        return out

    def _adaptive_skip_size(self, data: bytes, start: int, pos: int) -> int:
        win = self.seq.entropy_window
        lo = max(start, pos - win)
        h = bigram_entropy(data[lo:pos])
        # 64-byte window, all-unique 2-grams → log2(63) ≈ 6 bits.
        frac = min(max(h / 6.0, 0.0), 1.0)
        span = self.seq.skip_max - self.seq.skip_min
        return self.seq.skip_min + int(frac * span)

    def _scan(self, data: bytes, start: int) -> tuple[int, bytes | None]:
        n = len(data)
        remaining = n - start
        p = self.params
        s = self.seq
        hasher = hashlib.blake2s(digest_size=16) if s.fuse_fingerprint else None
        hashed = start

        def catch_up(pos: int) -> None:
            nonlocal hashed
            if hasher is None or pos <= hashed:
                return
            hasher.update(data[hashed:pos])
            hashed = pos

        def finish(end: int) -> tuple[int, bytes | None]:
            catch_up(end)
            return end, (hasher.digest() if hasher is not None else None)

        if remaining <= 0:
            return n, (hasher.digest() if hasher is not None else None)
        if remaining <= p.min_size:
            return finish(n)

        max_end = start + min(remaining, p.max_size)
        min_end = start + p.min_size
        avg_pos = start + p.avg_size
        # Paper: skip (Tmin - SeqLength) so a run can complete exactly at Tmin.
        i = start + max(p.min_size - s.seq_length, 1)
        if i <= start:
            i = start + 1
        catch_up(i)

        opposing = 0
        run = 0
        skips_this = 0
        weak_len = max(2, s.seq_length - 2)
        weak_best: int | None = None
        weak_dist = 10**9
        increasing = s.increasing

        while i < max_end:
            diff = data[i] - data[i - 1]
            if diff == 0:
                # Equal bytes do not form a strict monotonic run (DedupBench-style).
                i += 1
                if hasher is not None and i - hashed >= 256:
                    catch_up(i)
                continue
            is_inc = diff > 0
            if is_inc == increasing:
                run += 1
                opposing = 0
                # Exclusive end is i+1 so the completing byte is inside the chunk.
                end = i + 1
                if run >= weak_len and end >= min_end:
                    dist = abs(end - avg_pos)
                    if dist < weak_dist:
                        weak_dist = dist
                        weak_best = end
                if run >= s.seq_length and end >= min_end:
                    return finish(min(end, max_end))
            else:
                run = 0
                opposing += 1
                if opposing >= s.skip_trigger:
                    skip = self._adaptive_skip_size(data, start, i) if s.adaptive_skip else s.skip_size
                    if self.policy is not None:
                        skip = self.policy.jump_size(data, start, i, skips_this, skip)
                    if skip <= 0:
                        self.skip_hold_count += 1
                        opposing = 0
                        run = 0
                        i += 1
                        continue
                    self.skip_count += 1
                    skips_this += 1
                    i += skip
                    opposing = 0
                    run = 0
                    catch_up(min(i, max_end))
                    if i >= max_end:
                        break
                    continue
            i += 1
            if hasher is not None and i - hashed >= 256:
                catch_up(i)

        if weak_best is not None:
            take_weak = False
            if self.policy is not None:
                take_weak = bool(self.policy.use_weak(data, start, weak_best, max_end, skips_this))
            elif s.tmax_rescue:
                take_weak = True
            if take_weak:
                self.rescue_count += 1
                return finish(min(weak_best, max_end))
        return finish(max_end)
