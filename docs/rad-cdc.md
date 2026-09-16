# RAD-CDC: a novel algorithm to beat stage-by-stage dedup

**RAD-CDC** (Restore-And-Delta-aware Content-Defined Chunking) is the original algorithm this project should implement. It is designed to do **better than “run FastCDC, then hash, then maybe delta, then maybe rewrite”** by folding those later concerns into the cut decision itself.

This is not another rolling-hash variant. FastCDC, SeqCDC, and Chonkers still answer only: *“does this local byte window look like a boundary?”* RAD-CDC answers: *“among legal boundaries, which cut is best for exact hits, delta, and future restore?”*

---

## Problem the survey leaves on the table

Fu et al. (ACM CSUR 2025) separate:

- **Partitioning** — maximize duplicate detection.
- **Resemblance / delta** — after unique chunks exist, find similar chunks (they say resemblance detection is now the bottleneck, and one-base delta wastes other similar chunks).
- **Restore** — better dedup causes fragmentation; rewriting is a *post-hoc* fix.

Those stages do not share a utility function. A cut that is “content-defined and average-sized” can still:

1. miss a nearby boundary that would have matched an already-stored chunk;
2. produce a unique chunk that is *almost* like a stored chunk but a bad delta source because the cut split a repeated motif;
3. sprinkle a file’s chunks across many containers, so restore reads explode.

Related work stays in one stage:

| Work | What it optimizes | What it ignores at cut time |
|---|---|---|
| FastCDC / Gear | speed + size normalization | restore, delta |
| SeqCDC / VectorCDC | hashless SIMD throughput | restore, delta |
| Chonkers | size + edit-locality proofs | throughput, delta, restore I/O |
| RapidCDC | skip hashing using dup locality | *which* cut to choose |
| Palantir / DeepSketch | finding a delta base | chunk boundaries |
| HAR / Capping / Hybrid-Rewrite | rewrite after the fact | never re-cuts the stream |

RAD-CDC’s claim: **a cheap online score over a handful of candidate cuts can improve bytes-after-dedup+delta and restore I/O, with only a small throughput tax.**

---

## Pipeline: CascadeDedup

```
stream
  │
  ▼
cheap candidate CDC (hashless extrema or gear)  →  {b in [Tmin, Tmax]}
  │
  ▼
RAD scorer (exact / delta / fragmentation / size)
  │
  ▼
emit chunk
  │
  ├─ exact fingerprint hit?  →  store reference, update locality stats
  ├─ else sketch-similar?    →  store delta against best base (if compression pays)
  └─ else                    →  store unique chunk in current container
  │
  ▼
optional text gate: MinHash fuzzy at record/document granularity
```

Layer 3 is optional and only for JSONL/text. The novel core is the scorer + the dual index.

---

## Data structures (keep them small)

All of these must fit in RAM on a laptop for the prototype:

1. **Exact index** `fp → (container_id, offset, length)`  
   Fingerprint: BLAKE3 or xxHash64 + confirm SHA-256 on collision (hybrid fingerprinting from the survey, used as a baseline technique, not as the contribution).

2. **Sketch cache** of the last `S` *unique* chunks (e.g. 4k–64k):  
   each entry is `k` min-hashes or a tiny superfeature (4–8 sampled fingerprints). This is resemblance, not a DNN.

3. **Recent-file locality**  
   For the current stream: last `W` chunk placements `(container_id, was_duplicate)`. Used to estimate restore cost.

4. **Open container**  
   Append-only buffer of unique bytes, sealed at ~4 MiB (classic Data Domain style). Needed so fragmentation is measurable.

---

## Candidate generation (not novel; keep it fast)

Do **not** invent a new rolling hash. Reuse a modern hashless or gear splitter only to propose cuts:

- Scan with an Asymmetric Extremum / SeqCDC-style local-max rule, or gear hashing like FastCDC.
- Enforce `Tmin`, `Tmax`, and a target `Tavg`.
- Collect up to `C` legal cut offsets in the current window (C = 4 to 16 is enough). If the algorithm only emits one cut, **perturb**: also score `b ± {256, 1KiB, 4KiB}` when those offsets stay inside `[Tmin, Tmax]`.

The perturbation step is important: standard CDC never even *considers* a nearby cut that would have hit an existing chunk.

---

## Scoring function (this is the novel part)

For each candidate cut `b`, let `chunk = data[start:b]`.

```
Score(b) = we * ExactGain(b)
         + wd * DeltaGain(b)
         - wr * FragCost(b)
         - wm * SizePenalty(b)
```

### ExactGain(b) ∈ [0, 1]

- Compute a cheap fingerprint of `chunk` (xxHash64).
- `1.0` if it hits the exact index.
- `0.5` if a *prefix/suffix* of length ≥ Tmin hits (duplicate locality; RapidCDC-like signal, but used for selection not skipping).
- `0.0` otherwise.

### DeltaGain(b) ∈ [0, 1]

- Compute sketch(chunk).
- Let `sim` be max Jaccard (or Hamming on superfeatures) against the sketch cache.
- `DeltaGain = 0` if `sim < τ_low`.
- Else `DeltaGain = (sim - τ_low) / (1 - τ_low)`, optionally multiplied by `1 - ExactGain` so exact hits are not double-counted.

### FragCost(b) ∈ [0, 1]

Predicted extra random reads if this file is restored later.

- If ExactGain is high and the matched chunk’s `container_id` is among the last `W` containers this file already touched: **FragCost ≈ 0** (good locality).
- If ExactGain is high but the match lives in a cold container that this file has not touched: **FragCost ≈ 1** (this is the HAR/Capping situation — you might even prefer to *not* take the duplicate and rewrite, i.e. store a local copy; model that as a choice: `take_dup` vs `rewrite`).
- If the chunk is unique: FragCost = 0 if it appends to the current open container, else 1.

The **rewrite option** is how RAD-CDC absorbs post-hoc rewriting into the cut/index decision: for a duplicate with high FragCost, compare `Score(take_dup)` vs `Score(store_local_copy)`. That is a known restore trick, but here it is applied *while choosing the cut*, so a slightly different boundary might turn a high-frag duplicate into a low-frag duplicate.

### SizePenalty(b)

Penalize chunks near Tmin (metadata blow-up) and near Tmax (byte-shift sensitivity):

```
SizePenalty = |len(chunk) - Tavg| / (Tmax - Tmin)
```

### Weights

Start with `we=1.0, wd=0.6, wr=0.4, wm=0.2` and sweep. The project’s experimental contribution includes showing the Pareto front: ratio vs restore vs throughput.

---

## Dual decision after the winning cut

```
fp = strong_hash(chunk)          # only for the winning cut, not every candidate
if fp in exact_index:
    if FragCost low: reference it
    else: maybe rewrite into open container (restore-aware)
elif best_sim >= τ_delta and estimated_delta_bits < len(chunk) * ρ:
    store delta(chunk, base)     # base from sketch cache, then confirm
else:
    append unique chunk to open container
    insert fp and sketch
```

Delta encoding in the prototype can be `zstd` with a trained dict, or a simple byte-level xor+RLE for speed. Fidelity matters less than measuring *whether the scorer picked a better base/cut*.

---

## Distributed chapter (optional, survey-aligned)

If you want the project to still speak to Fu et al.’s *distributed* setting without a cluster:

**Sketch-affinity routing.** Hash the coarse sketch into a node id, with a small probe of `p` nodes, and send the superchunk to the node with the best sketch overlap unless that node is above a load watermark. Simulate `N = 2..32` nodes. Metrics: global dedup ratio, residual cross-node duplicates, load CV, probes per superchunk.

This is Topic 2 in [research-topics.md](research-topics.md). It is the “even better routing” counterpart to RAD-CDC’s “even better chunking.”

---

## Hypotheses (write these in the evaluation report)

1. On versioned datasets (kernel tarballs, successive software releases), RAD-CDC matches or beats FastCDC **exact** dedup ratio and **beats it after delta**, because cuts can align to similar—not only identical—regions.
2. Restore speed factor (bytes restored / unique container bytes read) improves vs FastCDC+greedy containers, approaching rewrite-based methods without a separate rewrite pass.
3. Throughput stays within ~0.5–0.8× of the candidate CDC alone, because only `C` cheap fingerprints are computed per emitted chunk.
4. Naive “always perturb ±1KiB” without the score will *hurt* ratio (negative control).

If (1) or (2) fails, that is still a result: it shows the joint objective is not worth the tax, which the survey’s staged design implicitly assumes.

---

## Baselines and metrics

**Baselines**

- Whole-file hashing (old project; keep as a weak baseline).
- Fixed-size chunking (Venti-style).
- FastCDC (required).
- One hashless CDC (SeqCDC or AE), if you have time.
- FastCDC + greedy one-base delta (Palantir-style *without* RAD cuts) — this isolates whether the *cut scorer* matters.

**Metrics**

- Dedup ratio and post-delta reduction ratio.
- Chunk-size mean/variance.
- Restore speed factor / estimated container reads.
- Chunking+index throughput (MB/s), serial vs process-pool.
- Metadata overhead (bytes of index + sketches / unique payload).

**Datasets (public, no personal cloud)**

- Linux kernel release tarballs (survey’s “source codes” class).
- A Wikipedia dump slice (survey lists Wikimedia dumps).
- Two software archives (e.g. GCC or MySQL releases — also in the survey).
- Optional: a small JSONL text slice for the fuzzy gate.

Fu et al. note there is still no standard benchmark. Use a fixed script and record versions. DedupBench is useful for *chunking-only* comparisons; RAD-CDC needs restore/delta metrics on top.

---

## Complexity (so the idea is not “just score everything”)

Let `n` be stream bytes, `C` candidates per chunk, `S` sketch-cache size, `k` hashes per sketch.

- Candidate CDC: `O(n)` (same as FastCDC/SeqCDC).
- Extra per emitted chunk: `O(C)` cheap hashes + `O(C · k · probe)` sketch compares. Keep `probe ≪ S` with a MinHash LSH or a simple inverted table on the first min-hash.
- Strong hash: **once per winning cut**, not per candidate.

That is the difference between a toy and a serious algorithm.

---

## Why this is a legitimate “better than the paper’s methods” claim

The survey’s best partitioning methods are CDC and application-aware chunking. RAD-CDC is **content-defined and workload-adaptive without parsing file formats**, and it is **restore- and delta-aware without waiting for a later pass**. That sits exactly on their open problem: *“find an adaptive data partitioning method to match various application characteristics… to improve global data deduplication efficiency”* — with a concrete utility function they do not provide.
