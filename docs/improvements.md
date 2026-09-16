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
| **Learned SeqCDC skip/Tmax** | Frozen logistic at SkipTrigger (jump vs hold) and at Tmax-with-weak (rescue vs keep Tmax). Train seed 101; labels from vanilla SeqCDC store oracles | Keep the SeqCDC+Tmax ratio lift without always-rescue, or beat always-rescue by refusing bad weak cuts | DeepSketch learns *which base*. SmartChunker samples CDC *parameters*. Byte-local skip/Tmax scoring on SeqCDC is the leftover. |

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

`python3 -m pytest`: **29 passed**.

The bar is a **small tweak to FastCDC or SeqCDC**, not a new algorithm.

Ablation (same 3.03 MiB timelines, encode-then-filter): **adaptive SkipSize does not change cuts** on these files. The SeqCDC knob that moved ratio is **Tmax rescue**. FastCDC Tmax rescue (easy-mask hit closest to Tavg, only if Gear would emit Tmax) is almost a no-op here.

### Tmax rescue vs the published method

| corpus | tweak | exact | after delta | chunk MB/s |
|---|---|---:|---:|---:|
| mixed seed 0 | FastCDC | 1.236 | 5.594 | 9.20 |
| mixed seed 0 | FastCDC + Tmax rescue | 1.236 | 5.594 | 7.83 |
| mixed seed 0 | SeqCDC | 1.145 | 4.324 | 12.66 |
| mixed seed 0 | SeqCDC + Tmax rescue | **1.150** | **4.648** | 9.48 |
| mixed seed 11 | FastCDC | 1.205 | 4.673 | 9.17 |
| mixed seed 11 | FastCDC + Tmax rescue | 1.205 | 4.674 | 7.57 |
| mixed seed 11 | SeqCDC | 1.177 | 4.599 | 12.56 |
| mixed seed 11 | SeqCDC + Tmax rescue | **1.203** | 4.569 | 9.84 |
| random seed 0 | FastCDC | 1.742 | 4.795 | 9.55 |
| random seed 0 | FastCDC + Tmax rescue | 1.744 | 4.795 | 8.11 |
| random seed 0 | SeqCDC / +Tmax | 1.608 / 1.608 | 4.114 / 4.114 | 12.78 / 12.44 |

**SeqCDC Tmax rescue** is the only leftover knob that consistently acts like a small published-method tweak: on mixed data it adds a bit of SeqCDC space savings (seed 0 post-delta **+7.5% relative**; seed 11 exact **+2.2% relative**, almost FastCDC’s 1.205). Cost: ~25% slower chunking in this Python loop. On uniform random data it does nothing. It does **not** overtake FastCDC.

**FastCDC Tmax rescue** does not help FastCDC on these files (FastCDC rarely dies at Tmax / the rescue cut matches the old one) and it slows the scan.

**Adaptive skip** vs SeqCDC: mixed seed 0 exact 1.145 → 1.140 (slightly worse); other seeds identical.

### Learned SeqCDC skip / Tmax (`seqcdc-learn`)

Frozen logistic, train seed 101, same 6×512 KiB mixed/random protocol as the other knobs. Labels come from vanilla SeqCDC store oracles (always jump, never rescue). Inference only at SkipTrigger and at Tmax-with-weak.

| corpus | tweak | exact | after delta | chunk MB/s | notes |
|---|---|---:|---:|---:|---|
| mixed seed 0 | SeqCDC | 1.145 | 4.324 | 12.99 | published |
| mixed seed 0 | SeqCDC + Tmax rescue | **1.150** | **4.648** | 9.93 | 34 rescues |
| mixed seed 0 | SeqCDC + learned | **1.150** | **4.648** | 9.95 | copies always-rescue: skip `constant(1)` n=1035/1035, Tmax `constant(1)` n=7 pos=5 |
| mixed seed 11 | SeqCDC | 1.177 | 4.599 | 12.96 | published |
| mixed seed 11 | SeqCDC + Tmax rescue | **1.203** | 4.569 | 10.35 | 25 rescues |
| mixed seed 11 | SeqCDC + learned | **1.203** | 4.569 | 10.31 | same collapse |
| random seed 0 | SeqCDC / +Tmax / learned | 1.608 / 1.608 / 1.608 | 4.114 | ~13.1 | Tmax 8 rescues, learned 0; stored bytes unchanged |

**The results are not good as an ML tweak.** On this train set the skip oracle has **zero hold labels** (a SeqLength=6 increasing run almost never appears inside a 256-byte skip after 50 opposing pairs). Tmax has only 7 rows (5 rescue), below `min_examples=12`, so the Tmax head falls back to always-rescue — the hand rule that already helped. `seqcdc-learn` therefore matches `seqcdc-tmax` on mixed data and matches published SeqCDC on random (where the two Tmax train labels were both “keep Tmax”).

A diagnostic with a richer train (seed 101, 6×2 MiB mixed) does fit a Tmax logistic (18 rows, 8 positive, threshold 0.60). On the frozen 6×512 KiB tests it **under-rescues and loses the hand-tweak lift**: mixed seed 0 exact 1.150 → 1.122 and post-delta 4.648 → 4.321 (8 rescues vs 34); mixed seed 11 exact 1.203 → 1.176 (1 rescue vs 25). Skip stays `constant(1)`. Default `bench` does **not** use that larger train.

FastCDC still wins both ratios. The small SeqCDC tweak that moved space savings remains **always-rescue at Tmax**, not a learned gate.

### Other knobs (unchanged conclusion)

Mux, fused fingerprint, RAD similar-migrate, the encode-free predictor, and the learned SeqCDC skip/Tmax scorer still do not give a small, reliable lift beyond SeqCDC Tmax rescue. Predictor: fewer zlib encodes, worse stored bytes.

Laptop-scale synthetic timelines only. A C inner loop could still change the throughput column; it would not change which tweak moved ratio.
