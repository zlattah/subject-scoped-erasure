# Leftover CDC / delta knobs (not a new algorithm family)

These are the improvements that survived the novelty audit: they are **knobs on
published algorithms**, not new chunking families. SeqCDC, FastCDC, Finesse, and
encode-then-filter delta are prior work. RapidCDC+SeqCDC, ZERO/RLE, historical
recipe reuse, dual Rabin, and VectorCDC are **not** claimed here.

Train the gain predictor on `--train-seed` (default 101). Report test corpora
`--seed` 0 and 11, the same seeds used for the RAD-CDC runs.

| Knob | What it changes | Hypothesis | Already published? |
|---|---|---|---|
| **SeqCDC baseline** | Hashless monotonic-sequence CDC (SeqLength=5, SkipTrigger=50, SkipSize=256) | Match FastCDC ratio at higher chunk-only throughput | **Yes** (Middleware 2024). Baseline, not a contribution. |
| **Adaptive SkipSize** | On a skip, map 64-byte 2-gram entropy → SkipSize in [64, 1024] | Higher chunk-only MB/s than fixed-256 SeqCDC, small ratio tax | SeqCDC already scales SkipSize with *target avg chunk*. It does **not** scale it from *local entropy*. |
| **Tmax rescue** | If no SeqLength=5 run before Tmax, emit the SeqLength=3 cut closest to Tavg | Fewer hard-Tmax chunks, slightly better ratio | **Not Chonkers.** Chonkers is a priority-merge of proto-chunks. This only spends a weak cut on spans that would have been Tmax. |
| **Fused fingerprint** | blake2s the emitted chunk during the SeqCDC scan (skipped spans included) | Same cuts and same fingerprints as SeqCDC; fewer extra memory passes | Hash-during-CDC exists (IBM dual Rabin). Fusing a *confirm* fingerprint onto *hashless* SeqCDC, including skipped bytes, is the leftover. Python may still lose: `hashlib.update` in the scan can be slower than one shot over the slice. |
| **Entropy mux** | Per chunk, 64-byte 2-gram entropy &lt; 3.5 → FastCDC, else SeqCDC | Beat either CDC alone on mixed-entropy streams | SmartChunker samples *global* CDC parameters. This is a *local* switch. Mixing families can still hurt exact-dedup. |
| **Encode-free gain predictor** | OLS on (positional sim, Finesse sim, length sim, entropy sim) → skip zlib-dict encode if predicted gain &lt; 0.10 | Cut `delta_encodes` with little `ratio_with_delta` loss vs encode-then-filter | Palantir/BePro encode then drop. DeepSketch learns *which base*, not *whether to encode*. Train/test seeds are frozen. |

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

Filled in after the measurement run. Negative results are allowed.
