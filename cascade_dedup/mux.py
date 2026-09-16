"""Local-entropy CDC multiplexer.

SeqCDC and FastCDC are both published. The leftover is a *per-chunk switch* using only local 2-gram entropy of the
upcoming Tmin span: low entropy → FastCDC (SeqCDC pathologically over-cuts on
ramps / long monotonic runs), otherwise SeqCDC.

The switch is a function of local bytes only, so identical files still agree.
"""

from __future__ import annotations

from cascade_dedup.chunking import CDCParams, FastCDC
from cascade_dedup.entropy import bigram_entropy
from cascade_dedup.seqcdc import SeqCDC, SeqParams


class EntropyMux:
    def __init__(
        self,
        params: CDCParams | None = None,
        *,
        threshold: float = 3.5,
        window: int = 64,
    ) -> None:
        self.params = params or CDCParams()
        self.threshold = threshold
        self.window = window
        self.fast = FastCDC(self.params)
        self.seq = SeqCDC(self.params, SeqParams())
        self.seq_cuts = 0
        self.fast_cuts = 0

    def _local_entropy(self, data: bytes, start: int) -> float:
        """Min 2-gram entropy of 64-byte windows in the upcoming Tmin span."""
        look = min(len(data), start + self.params.min_size)
        best = 99.0
        pos = start
        while pos < look:
            h = bigram_entropy(data[pos : pos + self.window])
            if h < best:
                best = h
            pos += self.window
        return 0.0 if best == 99.0 else best

    def next_cut(self, data: bytes, start: int) -> int:
        n = len(data)
        remaining = n - start
        if remaining <= self.params.min_size:
            return n
        h = self._local_entropy(data, start)
        if h < self.threshold:
            self.fast_cuts += 1
            return self.fast.next_cut(data, start)
        self.seq_cuts += 1
        return self.seq.next_cut(data, start)

    def cuts(self, data: bytes) -> list[int]:
        self.seq_cuts = 0
        self.fast_cuts = 0
        self.seq.skip_count = 0
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
