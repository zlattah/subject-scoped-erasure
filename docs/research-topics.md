# Novel Data Deduplication Topics

This note is the topic menu for the project pivot. It is grounded in Fu et al., *Distributed Data Deduplication for Big Data: A Survey* (ACM Computing Surveys 58(3), Article 66, 2025, DOI [10.1145/3735508](https://doi.org/10.1145/3735508)), then pushed past that survey into 2025–2026 work and into one original algorithm.

**Recommended pick:** Topic 1, **RAD-CDC** (Restore-And-Delta-aware Content-Defined Chunking) inside a **CascadeDedup** pipeline. Details and pseudocode are in [rad-cdc.md](rad-cdc.md).

---

## What the survey actually studies

The paper is not about personal/self-hosted clouds. It is a systems survey of **distributed, chunk-based storage deduplication** for big data. The pipeline is:

1. Split data into chunks (partitioning).
2. Fingerprint chunks (usually hashes).
3. **Route** data to storage nodes so similar bytes land together.
4. Look up fingerprints in a chunk index.
5. Restore files later (often hurt by fragmentation).
6. Garbage-collect unreferenced chunks.
7. Keep the system reliable and (if needed) secure while still deduplicating.

Three design principles they keep repeating: high throughput, capacity saving, load balance. The hard tradeoff is that **better dedup often makes restore and GC worse**, and **stateless routing scales but misses cross-node duplicates**.

Their Section 6 future-work buckets are the right place to look for novelty:

| Survey bucket | What they say is still open |
|---|---|
| Algorithm optimization | Multi-base delta compression; cheaper resemblance detection; **AI/ML routing that actually sees application features** |
| Advanced architecture | NVM / hybrid memory; cross-tier dedup; **CXL/GenZ memory-pool dedup** |
| Secure deduplication | Drop trusted third parties; SGX; blockchain auditing; **decentralized cross-domain** dedup |
| Application for AI | Dedup training corpora; memory dedup in distributed training; dedup-aware indexes |

**Do not treat “file-level SHA-256 + multiprocessing on a laptop cloud” as a contribution in this literature.** That is an engineering demo. The novel questions live in *how* chunks are cut, *how* near-duplicates are found, *where* they are placed, and *what restore/GC/AI quality you get*.

---

## What is already crowded (weak topics)

Skip these as the *main* thesis idea. They are either solved, incremental, or too hardware-heavy for this project:

- Whole-file hashing vs serial hashing (the old README).
- Another Rabin/FastCDC variant with a slightly different divisor.
- “Use Bloom filters for the index” without a new lookup/restore story.
- Blockchain + SGX secure dedup as the core idea (crowded, hard to evaluate honestly).
- CXL memory-pool dedup (needs hardware you will not have).
- Re-implementing Extreme Binning / EMC stateful routing as-is.

Use those only as **baselines**.

---

## Ranked topics

Each topic has: the gap, why it can beat current methods, how hard it is to prototype in Python, and how “survey-like” vs “2026-hot” it is.

### 1. RAD-CDC + CascadeDedup — **recommended**

**Gap.** CDC (FastCDC, SeqCDC, VectorCDC, Chonkers) chooses cut points from *local bytes only*. Restore rewriting (HAR, Capping, Hybrid-Rewrite) and delta/resemblance (Palantir, DeepSketch, MeGA) run *later*, as separate stages. RapidCDC uses duplicate locality only to *skip work*, not to pick better cuts.

**Idea.** Treat cut-point choice as a tiny online optimization: among legal content-defined candidates in `[Tmin, Tmax]`, pick the cut that jointly scores expected exact-hit, expected delta savings, and predicted restore fragmentation. Then cascade: exact hash → optional delta against a sketch-matched base → optional document-level fuzzy (MinHash) for text/JSONL.

**Why it can be better.** You spend a few extra comparisons per chunk to avoid (a) missing a nearby exact/similar boundary and (b) packing unique bytes in a way that later restore has to jump across containers. That is the survey’s “algorithm optimization” gap, made concrete.

**Feasibility.** High. Python + NumPy is enough. Compare against fixed-size, FastCDC, and a SeqCDC-style hashless splitter on public versioned corpora (Linux kernel tarballs, Wikipedia dumps, source releases).

**Risk.** Gains may be workload-specific. You must report cases where it *loses* on throughput, not only where it wins on ratio.

---

### 2. Sketch-affinity routing (distributed, simulated)

**Gap.** Fu et al. say existing routing still cannot see application-layer feature differences, and they explicitly call **AI/ML / similarity-aware routing** a good direction. Extreme Binning and EMC superchunk routing use sampled fingerprints aimed at *exact* dups. Palantir’s hierarchical sketches are for *intra-node* delta, not for *which node* should receive the superchunk.

**Idea.** Route superchunks by a cheap hierarchical sketch (coarse → fine), so a node receives both exact duplicates *and* delta-compressible neighbors. Add a load-balance penalty so hot nodes do not eat every popular cluster. Evaluate with a **simulator** of N nodes (no real cluster required): dedup ratio vs imbalance vs cross-node residual redundancy.

**Why it can be better.** Stateless DHT routing is fast but ratio collapses as node count grows (the survey states this). Sketch routing should keep ratio flatter as N increases, which is the actual distributed problem in the paper.

**Feasibility.** Medium. The novel part is the routing policy and the metrics, not a production Ceph plugin.

**Risk.** Without a real network, reviewers will ask whether simulated assignment overhead is honest. Keep the cost model explicit (bytes of sketch, probes per superchunk).

---

### 3. Hashless CDC that is also restore-local (SeqCDC × Chonkers)

**Gap.** 2025–2026 chunking split into two camps: **fast** (SeqCDC / VectorCDC: SIMD, skip, hashless) and **principled** (Chonkers: simultaneous proofs on chunk-size bounds *and* edit locality). Nobody has a practical algorithm that is both fast and has Chonkers-style locality under inserts.

**Idea.** Use SeqCDC/AE extrema as the bottom layer, then a *bounded* priority-merge (Chonkers-like) only when an edit would otherwise cascade. Prove a weaker but useful bound: “an insert of k bytes moves at most m boundaries,” while staying within a small factor of SeqCDC throughput.

**Why it can be better.** FastCDC/SeqCDC can still re-chunk far from an edit. Chonkers is stronger theoretically but not the throughput winner. A hybrid is a real algorithm paper.

**Feasibility.** Medium–hard. The theory has to be correct; experiments need versioned files with known edits (git histories are perfect).

**Risk.** Easy to accidentally reimplement Chonkers poorly. The contribution must be the *throughput vs proof* tradeoff, with measurements on DedupBench-style workloads.

---

### 4. Hybrid exact + fuzzy cascade for mixed storage and AI corpora

**Gap.** Storage dedup is exact chunk hashes. LLM corpus dedup is MinHash-LSH / HNSW fuzzy (SEDD/FED, FOLD, PUFFER, 2025–2026). Fu et al. flag “application for AI” as future work but do not give a unified system. These two literatures still barely talk.

**Idea.** One ingest pipeline with a **gate**: high-entropy binary → CDC exact; low-entropy / natural language → MinHash or embedding fuzzy; JSONL/Parquet records → record-boundary chunking then both. The novel knob is the gate (entropy + mime + cheap language-id) and a single report: bytes saved vs tokens removed vs downstream model-quality proxy (e.g. duplicate-induced n-gram overlap).

**Why it can be better.** Exact CDC under-dedups paraphrases and boilerplate HTML. Pure MinHash wrecks binary backups and cannot pack containers. A gate should dominate either method on a *mixed* corpus.

**Feasibility.** High for the systems part; model-quality eval should stay a proxy unless you have GPU budget.

**Risk.** FOLD/PUFFER are very new and strong on the fuzzy-only problem. Do not claim to beat them on Common Crawl. Claim to beat them on **mixed** data, which they do not target.

---

### 5. Lightweight learned skip / learned cut scoring (not a deep sketch)

**Gap.** DeepSketch (FAST 2022) uses a DNN for *delta reference search*. SeqCDC uses hand-designed skip rules. SmartChunker samples to pick CDC *parameters*. There is still no tiny, trained **cut scorer** (logistic / GBDT on ~20 byte-level features) that decides skip distance or which candidate cut to keep.

**Idea.** Features: local entropy, byte-run length, printable ratio, gear/AE extremum strength, distance to last cut, recent duplicate-hit bit. Train on labeled “this cut participated in a later exact or delta match” from a train corpus; test on a different corpus. Compare to FastCDC and SeqCDC.

**Why it can be better.** Hand-designed CDC is workload-blind. A 10 kB model can adapt to source code vs VM images vs JSONL without a GPU at inference.

**Feasibility.** High. scikit-learn is enough.

**Risk.** Overfitting to the train distribution. You must freeze the model before test corpora and report negative transfer.

---

### 6. Generation-colored containers for cheaper GC + restore

**Gap.** The survey calls distributed GC cumbersome because invalid chunks scatter across containers/nodes. Restore papers rewrite sparse containers; GC papers mark-and-sweep. Few student-scale systems **place** chunks so that a backup generation is physically clustered even when some chunks are shared.

**Idea.** Each unique chunk lives in a container tagged with the *oldest live generation* that references it. When generation G expires, most of G’s unique containers die with sequential reclaim; shared chunks are copied forward only if they would otherwise pin a huge dead container (copy-on-expire). Measure GC I/O and restore speed vs greedy container packing.

**Why it can be better.** Classic append-only containers maximize write throughput and destroy GC. This is a placement policy with a clear metric.

**Feasibility.** Medium. Needs a synthetic backup timeline (N weekly snapshots).

**Risk.** Looks like “just another layout.” The novelty has to be the coloring rule + a proof/argument that copy-forward is bounded.

---

### 7. Multi-base delta with a restore SLO (only if you want compression as the core)

**Gap.** Fu et al. note that classic delta uses **one** base chunk and wastes compressibility against other similar chunks; Palantir / MeGA / Hybrid-Rewrite (2024–2025) started to close this. Still open: pick *k* bases under an explicit restore budget (“this file must restore in ≤ R container reads”).

**Idea.** Formulate base selection as a small set cover / greedy: add a second base only if extra compression ≥ λ × extra predicted restore I/O.

**Feasibility.** Medium. Need a delta encoder (xdelta/zstd-patch) and a fragmentation model.

**Risk.** Closest to existing FAST/ASPLOS papers. Only take this if you can state a restore SLO they do not have.

---

## How the topics map to the survey’s taxonomy

| Survey chapter | Strongest matching topics |
|---|---|
| 3.1 Data partitioning | 1, 3, 5 |
| 3.2 Fingerprinting | 1 (hybrid exact + sketch), 5 |
| 3.3 Routing | 2 |
| 3.4 Index lookup | 1 (dual exact/sketch index), 4 |
| Data restore | 1, 3, 6, 7 |
| GC | 6 |
| Security / reliability | *not recommended as primary* |
| §6 Application for AI | 4 |

---

## Suggested reading order (short)

1. Fu et al. 2025 survey — architecture + taxonomy + §6.
2. FastCDC (USENIX ATC 2016) and SeqCDC / VectorCDC (2025–2026) — modern chunking.
3. Palantir (ASPLOS 2024) and DeepSketch (FAST 2022) — resemblance / delta.
4. Hybrid-Rewrite (ICCD 2025) or MeGA (TPDS 2025) — restore + delta together.
5. Only if you pick Topic 4: SEDD/FED, FOLD, PUFFER — LLM fuzzy dedup.

---

## Recommendation

Pick **Topic 1 (RAD-CDC)** as the novel algorithm, keep **Topic 2** as the “distributed” chapter (simulator, so the project still speaks the survey’s language), and treat **Topic 4** as an optional extra experiment if time remains.

That combination is:

- not a self-hosted cloud product;
- aligned with the paper’s hardest open problems (adaptive partitioning, resemblance, restore, routing);
- implementable without a 100-node cluster;
- has a clear “even better than SOTA chunkers” hypothesis you can falsify with measurements.
