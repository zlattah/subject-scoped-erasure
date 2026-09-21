# CS project plan

Subject-scoped erasure in a deduplicated, immutable backup.

This is the Computer Science **project plan** (motivation through schedule and AI use). It is not the English-class interim report ([english-class-interim-report.md](english-class-interim-report.md)) and not the working work-package list ([projectplan.md](projectplan.md)). Claim and glossary: [README.md](README.md).

---

## Motivation & background information

Backup products keep many recovery points affordable by **deduplicating** identical chunks across files, machines, and snapshots, and by locking history in **immutable** or Object-Lock vaults so a compromised network cannot encrypt or delete it. A retained snapshot is expected to stay bit-for-bit restorable; rewriting last week’s backup to edit one record is treated as a failure of that model.

Those two properties collide with the right to erasure (GDPR Article 17 and similar laws). The same vault still holds last month’s mail, file shares, and laptop images. When human resources offboard an employee or a customer asks to be forgotten, the live application can drop the account while the backup often cannot be rewritten for thirty to three hundred and sixty-five days, or years. Multi-tenant software-as-a-service, Microsoft 365 and Google Workspace archives, and mixed objects that interleave people (one Outlook PST, one Teams site, one family album) have the same shape. Litigation **holds** already demand “keep this mailbox, forget Alice.”

Supervisory authorities treat leftover backup copies as in scope. The UK ICO requires erasure to cover backups or that those copies be put **beyond use** until they rotate and not restored into production. The EDPB lists deletion from backups among the main practical failures. Operators today wait, lock, restore-and-edit in a lab, or crypto-shred an entire tenant. That can suffice for a short retention and a single owner. It fails when immutability is long, chunks are shared across people, and the file is mixed.

The applications are those stores in operation. An **enterprise backup / Object-Lock vault** must still restore last Tuesday after ransomware; the same lock means a departed employee’s laptop and mailbox stay in the chain until retention expires. **HR offboarding** and **GDPR/CCPA erasure** can drop the live account in minutes while an administrator restore reconstitutes the person. **Microsoft 365 and Google Workspace archives**, and **multi-tenant SaaS backups**, pack many users or customers into one deduplicated pool, so forgetting Alice must not destroy Bob’s tenant. **Shared Outlook PSTs, Teams sites, legal-matter mailboxes, and photo libraries** are mixed objects: one blob contains more than one person. **eDiscovery holds** reverse the order — keep this mailbox, forget Alice elsewhere — so erase waits and restore must flag that she is still recoverable from the pinned snapshot. The design is not aimed at a personal backup disk with one owner and a seven-day rotation.

Prior research already covers pieces of this setting: encrypt a file and throw away the file key (Boneh and Lipton, 1996); delete a **version** wrap while other versions still open a shared object (FadeVersion, Rahumed et al., 2011); reclaim or physically sanitize **unreferenced** chunks (HYDRAstor; Botelho et al., FAST 2013); encrypt so a server can still deduplicate (DupLESS). None of those specifies `erase` of a **person** when the shared unit is a **chunk**, the snapshot cannot be rewritten, the bytes may be **mixed**, and a hold may delay shred. This project is the laptop-scale store that setting would need.

---

## Problem statement, project objectives & scope

**Problem.** Given a backup that (1) stores identical content once and (2) treats retained snapshots as immutable, construct a store and a key/layout policy such that `erase(S)` makes data subject `S`’s personal data **unrecoverable** from every retained snapshot—including snapshots that byte-share with other people—while every other entitled subject can still **restore**, holds can defer shred without lying about either requirement, and extra space and restore cost can be measured against never sharing across subjects.

Deleting only Alice’s **recipe** (the small list of chunk ids for her file) is not enough: Tuesday’s frozen snapshot still has its own recipe, and the key store still has the keys an admin uses to restore. Destroying the one data key `k` on a chunk Bob still needs blinds Bob. Rewriting Tuesday breaks the ransomware vault. The leftover is therefore **subject-scoped erase**, not a new rolling hash.

The difficulty is not uniform. **Unique** bytes (Alice’s diary) can be shredded with her keys. **Identical** shareable bytes (a public installer) may stay on disk if Bob can restore and Alice cannot restore *her* copy: shred her wrap `s_alice`, keep `k` for Bob (**OR-wrap**). **Mixed** bytes (one PST, one group photograph) cannot stay as a single shared ciphertext if Alice must be unrecoverable and Bob must still open a useful object. A legal hold delays shred and must be visible: while it is live, restore may still yield Alice.

**Objectives.**

1. Freeze a glossary so the claim is not confused with version delete or physical overwrite (`subject`, chunk, recipe, snapshot, owner set, unique / identical / mixed, OR-wrap, AND-wrap, copy-out, hold, deferred erase).
2. Implement one pipeline: `ingest`, `restore`, `erase(S)`, `hold` / `release`, with an append-only chunk log and a **mutable** key store.
3. Parse one mailbox (mbox; PST if feasible) and one two-subject photo library so erase runs on inner messages and photos, not only on the whole file.
4. Compare, on the same API: OR-wrap, AND-wrap, no cross-user share, and copy-out on mixed (plus whole-file wrap as the leak baseline).
5. Measure live decryptable bytes versus never-share, restore success/failure, mixed leak or redaction, the hold recoverability window, and a synthetic (or named public) tenant-labelled ingest mix.
6. Write the comparison so a leak under mixed OR-wrap, a space cost under never-share, and a delay under hold are expected outcomes, not surprises.

**In scope.** Subject-scoped erase in a chunk-addressed backup; the three file classes, including mixed containers; wrap-mode baselines; holds; leftover-store attacker (remaining keys + chunk log + recipes); laptop-scale Python prototype and policy tests.

**Out of scope.** A new content-defined chunking algorithm; legal advice or a production PII classifier (labels and header heuristics are inputs); SGX, blockchain, or HSMs as the contribution; DupLESS-style encrypted-dedup brute-force resistance; physical drive overwrite as the only delete mechanism; perceptual near-duplicate matching.

---

## Major technical components

The prototype is one in-process store, not a distributed cluster.

1. **Chunk log (WORM data plane).** File bytes are split (fixed-size in the current prototype), encrypted with AES-GCM under a per-chunk data key `k`, and appended. Ciphertext is not rewritten in place. After shred, leftover blobs are residual ciphertext.

2. **Recipes (immutable snapshots).** Per subject, per snapshot, per path: ordered chunk ids. “Restore Tuesday” reads that list and decrypts. `erase` marks recipes unrestorable; it does not edit Tuesday’s bag.

3. **Key store (mutable control plane).** Subject control keys `s_alice`, wraps `{k}_{s_i}`, owner sets, hold pins, deferred-erase queue. If this store is itself locked inside the same WORM vault, shred is a lie.

4. **Class rules at ingest.** Unique: share fingerprint only within one subject. Identical: OR-wrap the same `k` (or store two copies in the never-share baseline). Mixed: do not silently OR-wrap; never-share, copy-out on erase, drop-for-both, or keep-for-Bob as a documented leak. AND-wrap is the FadeVersion-style baseline that blinds remaining owners.

5. **Container parsers.** mbox (and later PST if time allows) and a two-subject photo folder. Inner objects get unique / identical / mixed labels. Whole-file wrap of the container is the negative leak test.

6. **Holds.** Pins on the same keys `erase` would shred. Live pin → deferred erase and a flagged restore. `release` finishes the queue. Hold after shred cannot revive keys.

7. **Measurement harness.** `python -m cascade_dedup eval` runs the same corpus under the four modes, records live bytes versus never-share, leftover-attacker checks, hold window in snapshots, a synthetic three-tenant mix, and mbox/photo checks. Details: [docs/method.md](docs/method.md), [docs/evaluation.md](docs/evaluation.md).

**Stack.** Python 3.11+, `cryptography` (AES-GCM), pytest. CLI: `ingest` / `restore` / `erase` / `hold` / `release` / `demo` / `eval`.

---

## Expected results & deliverables

**Expected results (policy, not a compression contest).**

- Unique: after `erase(alice)`, Alice cannot restore; leftover keys do not yield her marker bytes; Bob is unaffected.
- Identical OR-wrap: Bob’s restore is byte-identical; one live copy remains; Alice cannot restore her copy.
- Mixed OR-wrap: **documented leak** — Bob’s restore still contains Alice. If this “passes” unrecoverability, the test is wrong.
- Mixed copy-out or drop: leftover store + Bob’s keys do not yield Alice; Bob gets a redacted object, a drop, or an explicit unrestorable old snapshot.
- AND-wrap and never-share lose Bob’s restore or space, as predicted.
- Hold: no shred while pinned; window counted; after `release`, the same unrecoverability checks pass.
- Sharing saves space **before** erase (on the current synthetic labeled corpus, OR-wrap live bytes were about 69% of never-share). After Alice is gone, remaining live bytes for OR-wrap and never-share match unless mixed is redacted. An identical-heavy synthetic tenant mix still showed copy-out at about 80% of never-share after `erase(alice)`. These numbers are laptop-scale and synthetic; they are not an enterprise trace.

**Deliverables.**

| Artefact | Form |
|---|---|
| Prototype store and CLI | `cascade_dedup` (`erase.py`, `containers.py`, `measure.py`) |
| Tests | `tests/test_erase_store.py`, `test_erase_containers.py`, `test_measure.py` |
| Evaluation write-up + JSON | [docs/evaluation.md](docs/evaluation.md), [docs/erase-eval.json](docs/erase-eval.json) |
| Design and related work | [docs/method.md](docs/method.md), [docs/related-work.md](docs/related-work.md) |
| This CS plan | `cs-project-plan.md` |
| English-class report | `english-class-interim-report.md` (design/results sections still reserved until filled) |
| Working engineering plan | `projectplan.md` |

A native Outlook PST parser, physical GC of WORM ciphertext, and a real multi-tenant production log are **hardening**, not required to call the prototype done. If they slip, the write-up names the substitute (mbox; synthetic trace) and does not generalise beyond it.

---

## Project schedule

Work is ordered by **dependency**, not by calendar dates. Each package ends with tests.

```
WP0 → WP1 → WP2 → WP3 → WP4
                    └→ WP5 → WP6 → WP7 → WP8
```

| Phase | Package | Done when |
|---|---|---|
| WP0 | Claim freeze | README glossary matches code names |
| WP1 | Store skeleton | Ingest and restore one unique file |
| WP2 | Identical share | OR-wrap; Bob exact; one live copy |
| WP3 | Labeled mixed | Copy-out or unrestorable; leftover attacker |
| WP4 | Baselines | AND-wrap, never-share, mixed OR-wrap leak |
| WP5 | Containers | One mbox (PST optional) and one photo folder |
| WP6 | Holds | Pin, deferred erase, measured window |
| WP7 | Trace | Mix table and erase/hold cost on the log actually run |
| WP8 | Write-up | Technical note; cite FadeVersion; do not claim Boneh is new |

WP1–WP7 already have an in-memory prototype and `eval` on synthetic data. Remaining schedule: keep tests green, optional PST hardening, replace or clearly label the tenant proxy if a public trace appears, then WP8. Holds can be extended as soon as WP2 exists; WP5 can stay on mbox if Outlook parsing consumes the project.

**Risks.** Hostile PST format → ship mbox. No real trace → named synthetic/public proxy. Mixed+hold bugs → leftover-store tests before any success claim. Key store backed up with chunks → shorter or independently shreddable key retention, documented.

---

## AI Usage Plan & Considerations

This project uses AI-assisted tools (including Cursor) as a **drafting and implementation aid**, not as an authority on novelty, law, or experimental truth.

**Intended uses.**

- Clarify and compress prose for plans and reports; keep the problem statement and glossary consistent.
- Search and summarise related work **as candidates**, then open the paper or primary page before citing.
- Draft Python for the store, parsers, tests, and `eval` harness from the written spec.
- Explain failures (restore leak, wrap bugs) and propose patches that are then run under pytest.

**Not intended uses.**

- Inventing papers, quotes, or measurements that were not produced by `eval` or tests.
- Treating model text as legal advice (ICO/EDPB/GDPR are cited from published sources; the store is not a compliance product).
- Pasting real tenant mail, photos, or backup dumps into a prompt. Labels and synthetic markers (`ALICE-SECRET`, fixture mbox) only.
- Submitting generated code or tables that have not been executed.

**Student responsibility.** The claim (subject erase under dedup + WORM + mixed + hold), the class rules, and the write-up’s honesty limits are human-owned. Every “success” row must match a test or a seed-0 `eval` JSON. If AI proposes that FadeVersion already did subject erase, the related-work note is checked against the paper: it did **version** wraps, not this leftover.

**Verification.** `python -m pytest`; `python -m cascade_dedup eval --seed 0`; leftover-attacker helpers in the store. Citations in the English-class report stay author–year and must correspond to entries in section 6 / [docs/related-work.md](docs/related-work.md).

**Integrity.** Acknowledge AI assistance in the course’s required form. Do not list a model as a co-author. Do not copy substantial copyrighted paper text into the repo; summarise and cite. Generated comments or names that overclaim (“novel CDC”, “GDPR certified”) are stripped.

**Limitations.** Models blur version-delete with subject-delete and unique with mixed. The glossary in the README is the check against that. Evaluation remains a synthetic policy test until a named public trace is used; AI must not be used to dress the proxy up as production telemetry.
