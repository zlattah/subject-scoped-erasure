"""Local-entropy CDC multiplexer.

SeqCDC and FastCDC are both published. The leftover is a *per-chunk switch*
using only a short local 2-gram entropy window: low entropy → FastCDC (SeqCDC
pathologically over-cuts on ramps / long monotonic runs), otherwise SeqCDC.

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

    def next_cut(self, data: bytes, start: int) -> int:
        n = len(data)
        remaining = n - start
        if remaining <= self.params.min_size:
            return n
        wend = min(n, start + self.window)
        h = bigram_entropy(data[start:wend])
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
