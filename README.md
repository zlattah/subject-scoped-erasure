# Parallel Deduplication for Self-Hosted Cloud Storage

## Project Plan

---

## 1. Motivation & Background Information

Self-hosted cloud storage systems give users control over their data by storing files on personal hardware rather than commercial cloud providers. This approach improves privacy, reduces recurring subscription costs, and keeps sensitive backups under the user’s direct ownership.

In practice, personal cloud libraries grow quickly. Users routinely upload the same photos, documents, videos, archives, and backups from phones, laptops, external drives, and messaging apps. Over time, exact duplicates and near-duplicate images consume disk space without adding value. On a personal device such as a MacBook, wasted space can slow backups, increase storage costs, and make file organization harder.

Existing file managers and basic sync tools often detect duplicates slowly because they scan and hash files serially. For large personal libraries, single-threaded scanning becomes a bottleneck. Parallel programming on multi-core CPUs can significantly reduce scan and hash time by distributing work across cores.

This project combines a small-scale private cloud service with a **parallel deduplication engine** written in Python. The system will run on a MacBook Pro, accept uploads from both the MacBook and an iPhone client, detect duplicate files, report reclaimable storage, and present results through a web dashboard.

---

## 2. Problem Statement, Project Objectives & Scope

### 2.1 Problem Statement

As users continuously back up personal files to a self-hosted cloud from multiple devices, duplicate content accumulates rapidly. Without an efficient deduplication mechanism, storage is wasted and users lack clear visibility into:

- which files are exact duplicates,
- how much space could be recovered,
- how file categories contribute to storage use, and
- whether parallel scanning meaningfully improves performance over serial methods.

The core problem is to **detect and report duplicates efficiently** in a personal cloud setting using parallel Python techniques, while remaining practical to deploy and demonstrate on consumer hardware (MacBook + iPhone).

### 2.2 Project Objectives

| # | Objective |
|---|-----------|
| 1 | Implement a small-scale private cloud service for personal file storage and upload |
| 2 | Implement exact duplicate detection using cryptographic and/or fast non-cryptographic hashing |
| 3 | Develop a parallel file-scanning and hashing engine using Python parallel programming |
| 4 | Compare the performance of serial vs. parallel deduplication methods |
| 5 | Generate a storage report showing duplicate groups and potential storage savings |
| 6 | Provide a web dashboard for storage usage, duplicate groups, file categories, and deduplication results |
| 7 | Test the system with files uploaded from a MacBook and an iPhone |

### 2.3 Scope

**In scope**

- Local private cloud service hosted on a MacBook Pro
- File upload/storage for common personal content (photos, documents, videos, compressed files, backups)
- Exact duplicate detection via hashing (e.g., SHA-256 and/or xxHash/BLAKE3-style fast hashes)
- Optional near-duplicate image detection (perceptual hashing) as a stretch/secondary feature
- Parallel vs. serial scanning/hashing comparison and basic benchmarking
- SQLite-backed metadata and duplicate-group storage
- Web dashboard for usage, categories, duplicate groups, and savings
- End-to-end demo using MacBook and iPhone as upload clients

**Out of scope**

- Production-grade multi-user cloud or public internet deployment
- Block-level / chunk-level deduplication (content-defined chunking)
- Automatic deletion or silent removal of user files (reporting and guided cleanup only, unless explicitly added later)
- Cross-device realtime sync comparable to commercial products (iCloud, Dropbox, etc.)
- Mobile-native app development (iPhone used via browser upload or standard file transfer)
- Distributed cluster / multi-machine parallelization

---

## 3. Major Technical Components

```
┌─────────────┐     upload      ┌──────────────────────┐
│  iPhone /   │ ──────────────► │  Private Cloud API   │
│  MacBook    │                 │  (Python web service)│
└─────────────┘                 └──────────┬───────────┘
                                           │
                                           ▼
                                ┌──────────────────────┐
                                │  File Storage Layer  │
                                │  (local disk)        │
                                └──────────┬───────────┘
                                           │
                                           ▼
┌──────────────────────┐        ┌──────────────────────┐
│  Web Dashboard       │ ◄───── │  Deduplication       │
│  (usage, groups,     │        │  Engine              │
│   categories, report)│        │  serial + parallel   │
└──────────────────────┘        └──────────┬───────────┘
                                           │
                                           ▼
                                ┌──────────────────────┐
                                │  SQLite Database     │
                                │  (metadata, hashes,  │
                                │   duplicate groups)  │
                                └──────────────────────┘
```

### 3.1 Private Cloud Service

- Lightweight Python web service for file upload, listing, and download
- Local filesystem storage on the MacBook
- Basic authentication or local-network-only access for the demo
- Accepts uploads from MacBook browser and iPhone Safari / Files sharing

### 3.2 File Ingestion & Metadata Layer

- Record filename, path, size, MIME/type category, upload source, timestamps
- Persist metadata in **SQLite**
- Classify files into categories (images, documents, video, archives, other)

### 3.3 Parallel Deduplication Engine

- **Scan**: walk stored files and collect candidates for hashing
- **Hash**: compute fingerprints for exact-match detection
  - Primary: cryptographic hash (e.g., SHA-256) for correctness
  - Optional fast path: non-cryptographic / faster hash for large datasets
- **Parallelism**: Python `concurrent.futures` (ProcessPoolExecutor / ThreadPoolExecutor) or `multiprocessing` to utilize multiple CPU cores
- **Serial baseline**: same pipeline without parallelism for fair comparison
- **Optional**: perceptual hash (pHash/aHash/dHash) for near-duplicate images

### 3.4 Duplicate Grouping & Storage Report

- Group files by identical hash
- Compute reclaimable space (sum of sizes of redundant copies)
- Export / display storage savings report

### 3.5 Web Dashboard

- Storage usage overview
- Duplicate groups and potential savings
- File category breakdown
- Serial vs. parallel timing / throughput results
- Trigger rescan / refresh deduplication results

### 3.6 Evaluation & Benchmarking Harness

- Controlled datasets (synthetic duplicates + real personal samples)
- Metrics: wall-clock time, throughput (MB/s or files/s), CPU utilization notes, storage savings
- Document results in an evaluation report

### 3.7 Tooling & Stack

| Layer | Choice |
|-------|--------|
| Language | Python |
| Database | SQLite |
| VCS | Git |
| Host | Apple MacBook Pro |
| Client | Apple iPhone (+ MacBook) |
| Likely libs | Flask/FastAPI, pathlib, hashlib / xxhash, concurrent.futures, SQLite (stdlib), simple HTML/JS or lightweight frontend |

---

## 4. Expected Results & Deliverables

### 4.1 Expected Results

1. A runnable **private cloud** on the MacBook that accepts uploads from MacBook and iPhone.
2. Correct **exact duplicate detection** with grouped results and measurable storage savings.
3. A **parallel hashing engine** that demonstrably outperforms the serial baseline on multi-core hardware for sufficiently large datasets.
4. A clear **performance comparison** (serial vs. parallel) with charts or tables in the evaluation report.
5. A usable **web dashboard** summarizing storage, categories, duplicates, and dedup outcomes.
6. (Stretch) Detection of **near-duplicate images** with separate reporting from exact duplicates.

### 4.2 Deliverables

| # | Deliverable | Description |
|---|-------------|-------------|
| 1 | **Private cloud service** | Local Python service for upload/storage of personal files |
| 2 | **Working software prototype** | End-to-end deduplication pipeline (scan → hash → group → report), serial + parallel modes |
| 3 | **Web dashboard** | UI for storage usage, duplicate groups, categories, and deduplication results |
| 4 | **Evaluation report** | Methodology, datasets, serial vs. parallel benchmarks, accuracy notes, storage savings, limitations, and future work |

### 4.3 Success Criteria

- Uploads succeed from both MacBook and iPhone onto the MacBook-hosted service.
- Exact duplicates are detected with no false merges for different file contents (hash correctness).
- Parallel mode shows improved wall-clock performance vs. serial on the test MacBook for representative workloads.
- Dashboard and report present actionable storage-savings figures.
- Prototype is reproducible via Git with clear setup instructions.

---

## 5. Project Schedule

Assumes a multi-week academic/project timeline. Adjust week boundaries to match course deadlines.

| Phase | Weeks | Tasks | Milestone |
|-------|-------|--------|-----------|
| **A. Foundations** | 1–2 | Finalize requirements; set up Git repo, Python env, project layout; choose web framework; design SQLite schema | Repo + schema + skeleton app |
| **B. Private cloud MVP** | 2–3 | File upload/list/download API; local storage paths; basic category tagging; iPhone upload test on local network | Working private cloud uploads |
| **C. Serial dedup** | 3–4 | File scanner; SHA-256 (and optional fast hash); duplicate grouping; storage savings calculation | Correct exact-dedup report |
| **D. Parallel engine** | 4–5 | Process/thread pool hashing; chunked/batched work; serial vs. parallel CLI or API modes; basic timing instrumentation | Parallel mode functional |
| **E. Dashboard** | 5–6 | Usage overview, duplicate groups UI, category charts, trigger rescan, show benchmark summary | Dashboard usable for demo |
| **F. Near-dup (optional)** | 6 | Perceptual hashing for images; separate “similar images” view | Stretch feature complete or deferred |
| **G. Evaluation** | 6–7 | Build test corpora; run serial/parallel benchmarks; capture savings; write evaluation report; polish README/setup | Evaluation report draft |
| **H. Demo & wrap-up** | 7–8 | End-to-end MacBook + iPhone demo rehearsal; bug fixes; final report and presentation materials | Final deliverables submitted |

### Suggested checkpoints

- **Week 2**: First successful upload from iPhone to MacBook service  
- **Week 4**: Exact duplicates detected and reported correctly  
- **Week 5**: Parallel speedup measurable on MacBook  
- **Week 6**: Dashboard demo-ready  
- **Week 8**: Final evaluation report and live demo  

---

## 6. AI Usage Plan & Considerations

### 6.1 Intended AI Use

AI assistants (e.g., Cursor / ChatGPT-class tools) may be used as a productivity and learning aid for:

- Scaffolding project structure, boilerplate APIs, and SQLite schema drafts
- Explaining Python concurrency models (`multiprocessing` vs. threads vs. `asyncio`) and recommending suitable patterns for CPU-bound hashing
- Generating unit-test stubs and sample benchmark harness outlines
- Reviewing code for bugs, race conditions, and edge cases (partial reads, empty files, permission errors)
- Drafting dashboard UI layouts and improving clarity of documentation / evaluation write-ups
- Suggesting experimental designs for fair serial vs. parallel comparison

### 6.2 Boundaries & Academic Integrity

- **Core design decisions** (architecture, hashing strategy, parallelism model, evaluation methodology) remain the student’s responsibility.
- AI-generated code must be **reviewed, understood, tested, and adapted**; do not paste unverified code into the prototype.
- Benchmark numbers, evaluation conclusions, and demo results must come from **actual runs on the MacBook**, not fabricated or AI-invented metrics.
- Cite or acknowledge AI assistance according to course policy (tools used, purpose, and extent).
- Do not use AI to generate confidential personal data; use synthetic or consented sample files for demos.

### 6.3 Privacy & Safety Considerations

- Prefer local-only / LAN-only deployment during development; avoid exposing the service to the public internet without authentication.
- Exclude real sensitive documents from shared Git history; use `.gitignore` for upload directories and local databases.
- When testing with iPhone photos, use non-sensitive sample media where possible.
- Hashing and metadata storage should not exfiltrate file contents to external AI services; keep analysis on-device unless explicitly sanitizing samples.

### 6.4 Quality Controls When Using AI

| Practice | Rationale |
|----------|-----------|
| Verify hash correctness with known duplicate/non-duplicate pairs | Prevent silent logic errors |
| Re-run benchmarks after AI refactors | Concurrency changes can invalidate timings |
| Keep a short “AI assistance log” (date, task, outcome) | Supports transparency in the evaluation report |
| Prefer small, reviewable AI diffs over large generated modules | Easier to own and defend in viva/demo |

### 6.5 Risks & Mitigations

| Risk | Mitigation |
|------|-------------|
| AI suggests inappropriate parallelism (GIL-bound threads for CPU hashing) | Prefer process pools for CPU-bound hashing; validate with measurements |
| Over-scoped dashboard / cloud features | Stick to MVP scope in Section 2.3 |
| iPhone upload networking issues (HTTPS, mDNS, firewall) | Document LAN setup early; fall back to cable/AirDrop + local import if needed |
| Unfair serial vs. parallel comparison | Same dataset, warmed caches noted, multiple runs, report medians |

---

## Quick Reference

| Item | Detail |
|------|--------|
| **Title** | Parallel Deduplication for Self-Hosted Cloud Storage |
| **Host hardware** | Apple MacBook Pro |
| **Client hardware** | Apple iPhone (+ MacBook) |
| **Language** | Python |
| **Database** | SQLite |
| **VCS** | Git |
| **Primary outcomes** | Private cloud + parallel dedup engine + dashboard + evaluation report |
