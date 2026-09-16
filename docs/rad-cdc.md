# RAD-CDC: what is actually novel (and what is not)

**Short answer:** RAD-CDC is not a new primitive. I oversold it. The rolling hash, candidate cuts, exact index, sketches, delta, and restore rewrite are all published. What is left is a **narrow hypothesis**, not a named invention.

---

## What is not novel

| Piece of “RAD-CDC” | Already published |
|---|---|
| Content-defined cuts from local bytes | Rabin, FastCDC, SeqCDC, VectorCDC, Chonkers |
| Pick among several legal cuts | TTTD; Bimodal CDC (FAST 2010) |
| **Query the store while chunking** | Bimodal: “always emit an already-existing big chunk.” Frequency-based chunking (Lu et al., MASCOTS 2010) uses global chunk frequency to choose cuts |
| Jump using previous duplicate’s next size | RapidCDC (SoCC 2019) — for **speed**, same cuts |
| Find similar chunks and delta-encode | Palantir, DeepSketch, Odess, Finesse, BePro |
| Refuse a duplicate/delta that wrecks restore | HAR, Capping, SDC, LoopDelta, Hybrid-Rewrite |
| Weighted sum of ratio vs restore vs size | Implicit in every rewrite/capping paper |

A staged pipeline **Bimodal/FastCDC → Palantir → LoopDelta** already does “exact, then similar, then restore.” Calling that stack RAD-CDC does not make it new.

---

## The only leftover question

Standard CDC is a function of the **bytes only**:

`cut = f(data, Tmin, Tavg, Tmax)`

Store-informed chunkers (Bimodal, FBC) already break that for **exact** hits: they ask “does this candidate already exist?” and prefer yes.

Nobody I found asks, **at cut time**:

> Among legal nearby offsets, should I *move* the boundary because a **similar** (not identical) stored chunk would delta-compress better, without blowing restore I/O?

That is the whole residue:

- Bimodal/FBC move or choose cuts for **exact** presence/frequency.
- Palantir/LoopDelta use **similarity and restore** only **after** the chunk is already cut.
- RapidCDC uses the index to **skip to** the content-defined cut, not to **replace** it.

So the claim is not “a new hash.” It is:

**Delta-aware, restore-penalized cut *migration*, with an exact-stability rule.**

The stability rule is the part that could be interesting: if the same bytes are ingested twice, you must still emit the same cuts (otherwise you destroy CDC). A shifted cut is allowed only when the natural CDC chunk is **not** an exact hit and a nearby offset is a better delta/restore trade. Identical files stay aligned; near-duplicates may be re-cut toward the store.

That rule is what stops this from being “just Bimodal with extra scores.” Bimodal already prefers exact hits. The new bet is that **similarity should be allowed to move a cut that would otherwise be unique.**

---

## Why a reviewer can still reject it

1. **It is a composition.** Weighted `ExactGain + DeltaGain − FragCost` is three known metrics at a new decision point.
2. **It may be wrong.** CDC exists so similar files share boundaries *without* looking at the store. Store-conditioned shifts can help file B match A, then **hurt** file C matching A (order dependence). If experiments show that, the idea is a negative result.
3. **Laptop eval** (tens of GB) will not convince a FAST/ATC reviewer you beat LoopDelta. It can still be a course project: measure the hypothesis on kernel/GCC tarballs.

---

## How to talk about it honestly

Do **not** say: “I invented a novel CDC algorithm called RAD-CDC.”

Do say: “I test whether **moving** CDC cuts using resemblance and restore cost beats the published staged pipeline (FastCDC/Bimodal + Palantir + rewrite). The new mechanism is similarity-driven cut migration under exact-stability. If it loses, that supports keeping chunking content-only.”

That is a measurement thesis with a small algorithmic knob. It is not a new family of chunking.

---

## If you need something stronger than this residue

Then do not implement RAD-CDC as the contribution. Stronger (harder) leftovers: a **proof** that similarity-driven migration cannot break exact-stability; or a **learned byte-level cut scorer** with frozen train/test corpora vs FastCDC/SeqCDC. Both are still “obvious next steps,” but they are not a relabeling of Palantir.

The rest of this file is a prototype design for the residue, not a claim that the components are new.

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

Related work already covers each *stage*. The remaining claim is only that they do not share a cut-time utility:

| Work | What it already does | Why it is not RAD-CDC |
|---|---|---|
| FastCDC / Gear / SeqCDC / VectorCDC | Local-byte CDC, speed and size | No index, delta, or restore in the cut |
| TTTD / Bimodal CDC | Pick among backup cuts | Objective is size / avoid max-chunk, not restore or delta |
| **RapidCDC (SoCC 2019)** | After a duplicate, jump to the historically next boundary | Goal is *throughput*; validation tries to accept the *same* CDC cut, not a better one |
| Palantir / DeepSketch / BePro | Find a delta base | After the chunk already exists |
| HAR / Capping / Hybrid-Rewrite / **SDC** / **LoopDelta** | Restore-aware rewrite or “only delta if base is in cache” | After chunking; they do not move the boundary |
| **SuperDelta (DCC 2024)** | Multiple base chunks + rebase for restore | Post-dedup delta, not CDC |

RAD-CDC is therefore **not a new primitive**. It is a composition: allow a few legal candidate offsets (Bimodal-style), score them with RapidCDC-like index locality **plus** Palantir-like sketches **plus** LoopDelta-like fragmentation, and *accept a different cut* if the score says so.

That is only worth implementing if a staged baseline (FastCDC → exact index → Palantir delta → LoopDelta-style rewrite) loses on the joint metric. If it does not, RAD-CDC is a refactor, not a better algorithm.

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

## Honest novelty claim

Fu et al. still ask for adaptive partitioning, but **restore-aware delta and multi-base delta are already implemented** (LoopDelta, SuperDelta). RAD-CDC is only interesting if moving the cut beats applying those methods *after* FastCDC. Cite RapidCDC, Palantir, and LoopDelta as the papers a reviewer will say you combined.
