# CascadeDedup / RAD-CDC

Research prototype for **novel data deduplication algorithms**, not a self-hosted personal cloud.

The project studies the same problem family as Fu et al., *Distributed Data Deduplication for Big Data: A Survey* (ACM Computing Surveys, 2025, [10.1145/3735508](https://doi.org/10.1145/3735508)): how to partition, fingerprint, index, and (optionally) route data so duplicate and *near-duplicate* content is removed without destroying restore performance. The contribution is **not** a new chunking family. It is a test of **similarity-driven cut migration** (store-informed CDC already exists for *exact* hits: Bimodal, FBC). See [docs/rad-cdc.md](docs/rad-cdc.md).

- Topic menu (ranked): [docs/research-topics.md](docs/research-topics.md)
- Algorithm design: [docs/rad-cdc.md](docs/rad-cdc.md)

---

## Why this is not the old project

The previous plan (“Parallel Deduplication for Self-Hosted Cloud Storage”) was a product demo: MacBook + iPhone uploads, SHA-256 whole-file hashing, multiprocessing vs serial, SQLite, dashboard. That does not engage this literature. The survey’s open problems are **adaptive partitioning, resemblance/delta, restore vs ratio, similarity-aware routing, and AI-corpus dedup** — not LAN file upload.

What we keep from the old plan: Python, parallel CPU hashing, a measurement harness, and a simple UI *if* it is used to inspect algorithm metrics (chunk-size histograms, ratio, restore estimate). What we drop: private-cloud hosting, iPhone clients, and “parallel vs serial” as the main scientific claim.

---

## Core idea (one paragraph)

Modern CDC (FastCDC, SeqCDC, Chonkers) picks cut points from local bytes only. Delta compression and restore rewriting run later, as separate stages. **RAD-CDC** generates a few legal content-defined candidate cuts, then chooses the cut that best scores expected exact-hash hits, expected delta savings, and predicted restore fragmentation. Unique chunks may be stored as deltas against a sketch-matched base. An optional last gate applies MinHash-style fuzzy dedup for text/JSONL. A simulator can add sketch-affinity *routing* so the work still addresses the survey’s distributed setting without a real cluster.

---

## Objectives

1. Implement baselines: whole-file, fixed-size, FastCDC (and hashless CDC if time).
2. Implement **RAD-CDC** with a dual exact/sketch index and container packing.
3. Measure dedup ratio, post-delta ratio, restore cost, throughput, metadata overhead on public versioned datasets.
4. (Stretch) Simulate similarity-aware routing across N nodes.
5. (Stretch) Text/JSONL fuzzy gate for mixed storage+AI data.
6. Write an evaluation report that can *falsify* the algorithm (when it loses, say so).

---

## Scope

**In scope**

- Chunk-level and CDC-based deduplication (the thing the old plan listed as out of scope).
- Near-duplicate / delta compression as a first-class metric.
- Restore-cost modeling via containers.
- Parallel fingerprinting as an implementation detail, not the thesis.
**Datasets:** tens of GB of public versioned archives on the MacBook, not TB-class LoopDelta/FastCDC traces. See the hardware budget in [docs/research-topics.md](docs/research-topics.md).

**Out of scope**

- Self-hosted cloud, mobile clients, multi-user auth.
- Silent deletion of user files.
- Production Ceph/HYDRAstor integration.
- SGX/blockchain secure dedup as the main topic.
- CXL hardware.

---

## Stack (prototype)

| Layer | Choice |
|---|---|
| Language | Python (NumPy; optional Numba later) |
| Fingerprints | xxHash / BLAKE3 for candidates; SHA-256 confirm |
| Delta | zstd or a small byte-delta |
| Metadata | SQLite or a simple on-disk hash map |
| Parallelism | `ProcessPoolExecutor` for hashing/chunking files |
| Eval | scripts + tables/plots in the report |

---

## Success criteria

- RAD-CDC is specified, implemented, and compared to FastCDC on at least two public datasets.
- Metrics include **ratio and restore**, not only wall-clock vs serial hashing.
- The report maps results back to Fu et al.’s taxonomy (partitioning, fingerprinting, index, restore; routing if simulated).
- Negative results are allowed: a well-measured loss is better than a dashboard that only shows speedup.

---

## Suggested schedule

| Phase | Focus |
|---|---|
| A | Read survey §2–3 and §6; freeze topic (RAD-CDC default) |
| B | Dataset scripts + baselines (fixed, FastCDC) |
| C | Containers + exact index + restore-cost metric |
| D | RAD scorer + sketch cache + delta |
| E | Parallel throughput + ablations (weights, C candidates) |
| F | Optional: routing simulator and/or text fuzzy gate |
| G | Evaluation report and plots |

---

## Run the prototype

CDC cuts stay content-only except in RAD-CDC. SeqCDC, adaptive skip, fused fingerprinting, the entropy mux, the encode-free delta-gain predictor, and the tiny learned SeqCDC skip/Tmax scorer are leftover **knobs**, not a new algorithm family. See [docs/improvements.md](docs/improvements.md).

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m cascade_dedup bench --versions 6 --base-size 524288 --seed 0
python3 -m cascade_dedup bench --versions 6 --base-size 524288 --seed 11
python3 -m cascade_dedup bench --versions 6 --base-size 524288 --seed 0 --profile random
python3 -m cascade_dedup video-bench
```

`bench` compares FastCDC, FastCDC Tmax-rescue, SeqCDC, SeqCDC Tmax-rescue, learned SeqCDC skip/Tmax (`seqcdc-learn`, train seed 101), adaptive-skip SeqCDC, fused-fingerprint SeqCDC, the entropy mux, and RAD-CDC. Default `--profile mixed` is a structured+random timeline; `--profile random` is the original uniform-byte corpus.

On these files the only leftover knob that acts like a **small published-method tweak** is SeqCDC Tmax rescue (weaker cut only when SeqCDC would emit Tmax): mixed seed 0 post-delta 4.324 → 4.648; mixed seed 11 exact 1.177 → 1.203. It costs chunking speed and does not overtake FastCDC. Adaptive skip, FastCDC Tmax rescue, and the learned SeqCDC skip/Tmax scorer do not help: `seqcdc-learn` copies always-rescue on the mixed 6×512 KiB train (no skip-hold labels; too few Tmax rows) and a larger-train Tmax logistic under-rescues and loses that lift. A loss is an allowed result.

- Cut migration: [docs/rad-cdc.md](docs/rad-cdc.md)
- Leftover knobs and measurements: [docs/improvements.md](docs/improvements.md)
- Remux-stable video units: [docs/video-au.md](docs/video-au.md)
