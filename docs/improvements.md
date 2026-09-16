# Leftover CDC / delta knobs (not a new algorithm family)

These are the improvements that survived the novelty audit: they are **knobs on
published algorithms**, not new chunking families. SeqCDC, FastCDC, Finesse, and
encode-then-filter delta are prior work. RapidCDC+SeqCDC, ZERO/RLE, historical
recipe reuse, dual Rabin, and VectorCDC are **not** claimed here.

Train the gain predictor on `--train-seed` (default 101). Report test corpora
`--seed` 0 and 11, the same seeds used for the RAD-CDC runs.

| Knob | What it changes | Hypothesis | Already published? |
|---|---|---|---|
| **SeqCDC baseline** | Hashless monotonic-sequence CDC (SeqLength=6 here, SkipTrigger=50, SkipSize=256) | Match FastCDC ratio at higher chunk-only throughput | **Yes** (Middleware 2024). Baseline, not a contribution. Paper Table 1 uses SeqLength=5. |
| **Adaptive SkipSize** | On a skip, map 64-byte 2-gram entropy → SkipSize in [64, 1024]; Tmax rescue on the same mode | Higher chunk-only MB/s than fixed-256 SeqCDC, small ratio tax | SeqCDC already scales SkipSize with *target avg chunk*. It does **not** scale it from *local entropy*. |
| **Tmax rescue** | If no SeqLength run before Tmax, emit the SeqLength-2 cut closest to Tavg | Fewer hard-Tmax chunks, slightly better ratio | **Not Chonkers.** Chonkers is a priority-merge of proto-chunks. This only spends a weak cut on spans that would have been Tmax. |
| **Fused fingerprint** | blake2s the emitted chunk during the SeqCDC scan (skipped spans included) | Same cuts and same fingerprints as SeqCDC; fewer extra memory passes | Hash-during-CDC exists (IBM dual Rabin). Fusing a *confirm* fingerprint onto *hashless* SeqCDC, including skipped bytes, is the leftover. Python may still lose: `hashlib.update` in the scan can be slower than one shot over the slice. |
| **Entropy mux** | Min 2-gram entropy over the upcoming Tmin span &lt; 3.5 → FastCDC, else SeqCDC | Beat either CDC alone on mixed-entropy streams | SmartChunker samples *global* CDC parameters. This is a *local* switch. Mixing families can still hurt exact-dedup. |
| **Encode-free gain predictor** | OLS on (positional sim, Finesse sim, length sim, entropy sim), threshold calibrated on train to keep recall ≥ 0.8 of true pays | Cut `delta_encodes` with little `ratio_with_delta` loss vs encode-then-filter | Palantir/BePro encode then drop. DeepSketch learns *which base*, not *whether to encode*. Train/test seeds are frozen. |

## How to run

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m cascade_dedup bench --versions 6 --base-size 524288 --seed 0 --profile mixed
python3 -m cascade_dedup bench --versions 6 --base-size 524288 --seed 11 --profile mixed
python3 -m cascade_dedup bench --versions 6 --base-size 524288 --seed 0 --profile random
```

`bench` prints every mode under `--delta-policy encode,predict`. `chunk_MB_s` is
cut-finding only; `MB_s` is the full ingest (index + optional zlib-dict).

SeqLength is **6** in this prototype so average chunk size matches FastCDC on
these synthetic files. Paper Table 1 uses SeqLength=5; on uniform random bytes
that setting degenerates to ~Tmin chunks and inflates exact-dedup by size, not
by a better cut rule.

## Results

`python3 -m pytest`: **23 passed**.

Corpus: 6 versions, 3.03 MiB logical. Predictor always trained on seed 101 of the
same profile. Negative results are allowed; **none of the leftover knobs beat
FastCDC on exact-dedup or post-delta ratio**.

### Mixed profile, seed 0 (encode-then-filter)

Predictor (train seed 101): OLS n=115, n_neg=16, threshold=0.355.

| mode | dedup | with delta | encodes (kept) | predict skip | seq skips | avg chunk | chunk MB/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| fastcdc | **1.236** | **5.594** | 124 (99) | 0 | 0 | 13294 | 9.62 |
| radcdc-exact | 1.236 | 5.594 | 124 (99) | 0 | 0 | 13294 | 1.85 |
| radcdc | 1.173 | 4.480 | 105 (77) | 0 | 0 | 16548 | 2.20 |
| seqcdc | 1.145 | 4.324 | 96 (67) | 0 | 1255 | 17362 | **12.65** |
| seqcdc-adapt | 1.145 | 4.651 | 106 (80) | 0 | 428 | 15275 | 9.52 |
| seqcdc-fused | 1.145 | 4.324 | 96 (67) | 0 | 1255 | 17362 | 11.22 |
| mux | 1.161 | 4.490 | 96 (70) | 0 | 1115 | 16900 | 9.90 |

Mux split: 17 FastCDC cuts / 171 SeqCDC cuts.

### Mixed profile, seed 11 (encode-then-filter)

| mode | dedup | with delta | encodes (kept) | seq skips | avg chunk | chunk MB/s |
|---|---:|---:|---:|---:|---:|---:|
| fastcdc | **1.205** | **4.673** | 101 (84) | 0 | 15729 | 9.60 |
| radcdc | 1.185 | 4.491 | 93 (74) | 0 | 17268 | 2.37 |
| seqcdc | 1.177 | 4.599 | 111 (86) | 884 | 15651 | **12.54** |
| seqcdc-adapt | 1.203 | 4.569 | 112 (87) | 279 | 14248 | 9.83 |
| mux | 1.159 | 4.339 | 107 (82) | 857 | 15966 | 9.70 |

Mux split: 16 FastCDC / 183 SeqCDC. Adaptive skip almost matches FastCDC exact
(1.203 vs 1.205) and beats SeqCDC exact; it still loses the delta column.

### Predict vs encode-then-filter (mixed, seed 0)

| mode | encodes | skipped | with delta (encode) | with delta (predict) |
|---|---:|---:|---:|---:|
| fastcdc | 124 → 92 | 32 | **5.594** | 4.854 |
| seqcdc | 96 → 73 | 23 | 4.324 | 4.005 |

The predictor does cut zlib-dict work. It also skips pairs encode-then-filter
would have kept, so stored bytes get worse.

### Random profile, seed 0 (the original RAD-CDC corpus)

FastCDC exact **1.742** / delta 4.795 matches the earlier RAD-CDC writeup.
`radcdc` is still worse (1.684 / 4.743). SeqLength=6 SeqCDC is size-matched
(avg 8105 vs FastCDC 8023) and **loses** on both ratios (1.608 / 4.114). Skip
never fires (`seq_skips=0`), so adaptive skip is a no-op. Mux classifies every
cut as SeqCDC. The predictor finds only 2 negative train examples and skips 4
FastCDC encodes; delta ratio 4.754 vs 4.795.

### What actually improved

- **SeqCDC chunk-only throughput** vs FastCDC (~12.6 vs ~9.6 MB/s in this Python
  loop). Ratio does not follow.
- **Adaptive skip vs SeqCDC** on mixed seed 11: exact 1.177 → 1.203. On mixed
  seed 0: post-delta 4.324 → 4.651. Both still behind FastCDC. Throughput **drops**
  vs fixed-skip SeqCDC (entropy + Tmax rescue).
- **Fused fingerprint**: bit-identical cuts and blake2s vs SeqCDC; **slower**
  chunk_MB_s in Python (11.2 vs 12.6).
- **Mux**: does switch on mixed data; lands *between* FastCDC and SeqCDC; does
  not beat FastCDC.
- **Predictor**: fewer `delta_encodes`, worse `ratio_with_delta`. Encode-then-filter
  remains the better byte policy on these files.
- **RAD-CDC similar migrate**: still hurts vs FastCDC on both profiles.

Laptop-scale synthetic timelines only. A C inner loop could still change the
throughput column for fused fingerprint and adaptive skip; it would not change
the ratio column.
