# CS project plan

**Subject-scoped erasure in a deduplicated, immutable backup**

A laptop-scale backup store that can forget one person without rewriting frozen snapshots and without breaking other people who still share stored bytes.

---

## Motivation & background information

Backup products keep many recovery points affordable by **deduplicating** identical byte regions (**chunks**) across files, machines, and snapshots, and by locking history in **immutable** or Object-Lock vaults so a compromised network cannot encrypt or delete it. **Immutable** here means write-once, read-many (WORM): new backups can be appended, but a retained day (for example last Tuesday) must stay bit-for-bit restorable. Rewriting that day to edit one record is treated as a failure of the protection model, not as a feature.

Those two properties collide with the right to erasure (GDPR Article 17 and similar laws). The same vault still holds last month’s mail, file shares, and laptop images. When human resources offboard an employee or a customer asks to be forgotten, the live application can drop the account while the backup often cannot be rewritten for thirty to three hundred and sixty-five days, or years. Multi-tenant software-as-a-service, Microsoft 365 and Google Workspace archives, and mixed objects that interleave people (one Outlook mailbox file, one Teams site, one family album) have the same shape. Litigation **holds** already demand “keep this mailbox, forget Alice.”

Supervisory authorities treat leftover backup copies as in scope. The UK Information Commissioner’s Office requires erasure to cover backups or that those copies be put **beyond use** until they rotate and not restored into production. The European Data Protection Board lists deletion from backups among the main practical failures. The right to erase a person is therefore real; **on backups it is weakly implemented**. Live systems (disable the account, delete the row) are much further along. Backup products still sell **space** (share a chunk once) and **ransomware survival** (do not rewrite Tuesday). Cutting one person out of that shared, frozen vault fights both features, so vendors ship workarounds instead of subject-scoped erase: **wait** until the job ages out and call the copy “beyond use”; **lock** restore so Alice is not rolled back into production while the bytes stay on disk; **restore-and-edit in a lab** (slow, and she was still in the vault); **crypto-shred a whole tenant** (Alice gone, Bob blinded); or **refuse** to run mailbox-remove tools while Object Lock is on, because editing the vault is what immutability forbids. That can suffice for a short retention and a single owner. It fails when the lock lasts months, chunks are shared across people, the file is mixed, or a hold says keep the mailbox.

The applications are those stores in operation. An **enterprise backup / Object-Lock vault** must still restore last Tuesday after ransomware; the same lock means a departed employee’s laptop and mailbox stay in the chain until retention expires. **HR offboarding** and **GDPR/CCPA erasure** can drop the live account in minutes while an administrator restore reconstitutes the person. **Microsoft 365 and Google Workspace archives**, and **multi-tenant SaaS backups**, pack many users or customers into one deduplicated pool, so forgetting Alice must not destroy Bob’s tenant. **Shared Outlook mailboxes (PST files), Teams sites, legal-matter mailboxes, and photo libraries** are mixed objects: one blob contains more than one person. **eDiscovery holds** reverse the order — keep this mailbox, forget Alice elsewhere — so erase waits and restore must flag that she is still recoverable from the pinned snapshot. The design is not aimed at a personal backup disk with one owner and a seven-day rotation.

Prior research already covers pieces of this setting: encrypt a file and throw away the file key (Boneh and Lipton, 1996); delete a **version** wrap while other versions still open a shared object (FadeVersion, Rahumed et al., 2011); reclaim or physically sanitize **unreferenced** chunks (HYDRAstor; Botelho et al., FAST 2013); encrypt so a server can still deduplicate (DupLESS). None of those specifies `erase` of a **person** when the shared unit is a **chunk**, the snapshot cannot be rewritten, the bytes may be **mixed**, and a hold may delay shred. This project is the laptop-scale store that setting would need.

---

## Problem statement, project objectives & scope

A **data subject** is the person the store must be able to forget (here, an identifier such as Alice). A **file** is what the user thinks of as one object. The store splits files into **chunks** (the unit that can be shared). A **recipe** is the small metadata that rebuilds one file: an ordered list of chunk identifiers. A **snapshot** is a frozen set of recipes for one person’s files at one moment; “restore Tuesday” means read Tuesday’s recipes, fetch those chunks, decrypt, and write the files out. Deduplication means Alice and Bob can have two recipes and **one** physical copy of the same installer.

**Problem.** Given a backup that (1) stores identical content once and (2) treats retained snapshots as immutable, construct a store and a key/layout policy such that `erase(S)` makes subject `S`’s personal data **unrecoverable** from every retained snapshot—including snapshots that byte-share with other people—while every other entitled subject can still **restore**, holds can defer shred without lying about either requirement, and extra space and restore cost can be measured against never sharing across subjects.

Unrecoverable means a computationally bounded attacker who obtains the leftover disk, all **remaining** keys, and all remaining recipes cannot reconstruct `S`’s personal data. Deleting only Alice’s recipe is not enough: Tuesday’s frozen snapshot still has its own recipe, and the product still holds keys so an administrator can restore. Destroying the one data-encryption key `k` on a chunk Bob still needs blinds Bob. Rewriting Tuesday breaks the ransomware vault. The leftover is therefore **subject-scoped erase**, not a new rolling hash.

The difficulty is not uniform.

- **Unique** bytes (Alice’s diary) belong to one person and can be shredded with her keys.
- **Identical** shareable bytes (a public installer) may stay on disk if Bob can restore and Alice cannot restore *her* copy: each person has their own **wrap** of the same `k` (OR-wrap). Forgetting Alice means destroying her wrap `s_alice`, not destroying `k`.
- **Mixed** bytes (one mailbox file, one group photograph) cannot stay as a single shared ciphertext if Alice must be unrecoverable and Bob must still open a useful object. **Copy-out** writes Bob a new object that no longer contains Alice; the old Tuesday mixed file cannot be patched in place, so it is marked unrestorable or fails restore. **AND-wrap** (nested policies) destroys `k` when any person is erased and blinds Bob — a baseline, not the claim.
- A legal **hold** delays shred and must be visible: while it is live, restore may still yield Alice.

**Objectives.**

1. State the problem and the terms above so the claim is not confused with deleting a file, deleting a snapshot, or overwriting a disk.
2. Implement one pipeline: ingest, restore, `erase(S)`, hold, and release, with an append-only encrypted chunk log and a **mutable** key store (the only place keys may be destroyed).
3. Parse one mailbox format (mbox, or Outlook PST if feasible) and one two-subject photo library so erase runs on inner messages and photos, not only on the whole file.
4. Compare, in the same program: OR-wrap, AND-wrap, never sharing across users, and copy-out on mixed (plus wrapping a whole mailbox as one blob as the leak baseline).
5. Measure how many bytes remain decryptable versus never-share, whether Bob’s restore matches, whether mixed data still contains Alice, how long a hold keeps her recoverable, and the unique / identical / mixed mix on a synthetic (or named public) tenant-labelled ingest log.
6. Write the comparison so a leak under mixed OR-wrap, a space cost under never-share, and a delay under hold are expected outcomes, not surprises.

**In scope.** Subject-scoped erase in a chunk-addressed backup; the three file classes, including mixed containers; wrap-mode baselines; holds; a leftover-store attacker model; a laptop-scale Python prototype and policy tests.

---

## Major technical components

The prototype is one in-process store, not a distributed cluster.

1. **Chunk log (immutable data plane).** File bytes are split into chunks, encrypted with AES-GCM under a random per-chunk key `k`, and **appended**. The ciphertext is not edited in place. After a key is destroyed, leftover ciphertext is junk (residual ciphertext). Physical deletion of those bytes may be forbidden while the volume is WORM.

2. **Recipes (snapshots).** For each person, each snapshot, and each path, the store keeps an ordered list of chunk ids. Restore concatenates the decrypted chunks. Erase marks recipes unrestorable; it does not rewrite last Tuesday’s list.

3. **Key store (mutable control plane).** Each subject has a control key (for example `s_alice`) that wraps `k`. The store also tracks owner sets (who still needs a chunk), hold pins, and a deferred-erase queue. If this key store is backed up inside the same frozen vault as the chunks, destroying `s_alice` does not erase old copies of the keys.

4. **Class rules at ingest.** Unique: do not treat the same bytes as unique for two people. Identical: OR-wrap one `k` for every entitled person (or store two copies in the never-share baseline). Mixed: do not silently OR-wrap; store per-person copies, copy-out on erase, drop the object for everyone, or keep Bob’s copy as a documented leak of Alice’s likeness. AND-wrap is the baseline that blinds remaining owners.

5. **Container parsers.** A mailbox (mbox first) and a two-subject photo folder are split into inner objects (messages, attachments, photos). Each inner object is labelled unique, identical, or mixed. Encrypting the whole mailbox as one blob is the negative test: Bob’s restore still contains Alice’s mail.

6. **Holds.** A hold pins the keys that restore of the target still needs. `erase(S)` then queues work instead of shredding. Restore of a held object may still contain `S` and must say so. `release` runs the queued shred. A hold requested after keys are already destroyed cannot bring them back.

7. **Measurement program.** The same synthetic corpus is ingested under the four wrap modes. It records decryptable bytes versus never-share, leftover-attacker checks (remaining keys plus leftover ciphertext), the hold window in snapshots, a small three-tenant mix, and mailbox/photo checks.

**Stack.** Python 3.11+, AES-GCM for chunk encryption, pytest. Commands: ingest, restore, erase, hold, release, plus a demonstration and a measurement run.

---

## Expected results & deliverables

**Expected results** (policy correctness, not a compression contest).

- Unique: after `erase(alice)`, Alice cannot restore; leftover keys do not yield her diary; Bob is unaffected.
- Identical OR-wrap: Bob’s restore of the installer is byte-identical; one live copy remains; Alice cannot restore her copy.
- Mixed OR-wrap: **documented leak** — Bob’s restore still contains Alice. If this looks like successful erasure, the test is wrong.
- Mixed copy-out or drop: leftover store plus Bob’s keys do not yield Alice; Bob gets a redacted object, a drop, or an explicit “old snapshot cannot keep this file” failure.
- AND-wrap and never-share lose Bob’s restore or extra space, as predicted.
- Hold: no shred while pinned; the window is counted; after release, the same unrecoverability checks pass.
- Sharing saves space **before** erase (on the current synthetic corpus, OR-wrap held about 69% of the never-share decryptable bytes). After Alice is gone, remaining live bytes for OR-wrap and never-share match unless mixed is redacted. An identical-heavy synthetic tenant mix still showed copy-out at about 80% of never-share after `erase(alice)`. These numbers are laptop-scale and synthetic; they are not an enterprise trace.

**Deliverables.**

| Artefact | What it is |
|---|---|
| Prototype | Python backup store with ingest, restore, erase, hold, and release |
| Tests | Policy tests for unique, identical, mixed, holds, leftover keys, mailbox and photo folders |
| Measurements | Table of wrap modes, space versus never-share, hold window, synthetic tenant mix |
| Interim Report I | Introduction, literature, early design, unique/identical demo |
| Interim Report II | System design, methodology, mixed/hold/eval progress |
| Final report | Problem, method, experiments, limits; does not claim Boneh shredding or FadeVersion version-delete as new |
| Oral presentation and live demonstration | Unique / identical / mixed / hold on the running prototype |

A native Outlook PST parser, physically wiping WORM ciphertext, and a real multi-tenant production log are extra hardening. If they slip, the reports name the substitute (mbox; synthetic trace) and do not generalise beyond it.

---

## Project schedule

Course deadlines are the checkpoints. Work between them is what has to be in that submission.

| When | Course deadline | What this project delivers by then |
|---|---|---|
| **Semester A, weeks 1–4** | **Week 4 — Project Plan** | Problem, terms, related-work placement, this plan, and a frozen claim: `erase(S)` under deduplication, immutable snapshots, mixed content, and holds. |
| **Semester A, weeks 5–11** | **Week 11 — Interim Report I & presentation** | Store skeleton: unique erase and identical OR-wrap with tests; ingest / restore / erase; Interim Report I with introduction, literature, and early design; a short live demo (Alice’s diary gone, Bob’s installer still restores). |
| **Semester B, weeks 1–4** | **Week 4 — Interim Report II** | Mixed copy-out and leak baseline, mailbox and photo-library inner objects, holds and deferred erase; Interim Report II with system design and methodology; measurement table on the synthetic corpus. |
| **Semester B, weeks 5–11** | **Week 11 — Final Report** | Wrap-mode comparison (OR / AND / never-share / copy-out), hold recoverability window, synthetic tenant mix, leftover-store checks; Final Report with experiment results, limits, and honest FadeVersion/Boneh citations. |
| **Semester B, week 12** | **Week 12 — Oral presentation & project demonstration** | Talk through unique / identical / mixed / hold on the running prototype; show a live erase and the measurement table; answer what leaked, what Bob kept, and what the numbers mean. |

A laptop prototype and synthetic measurements already exist as a starting point. Semester A week 11 still has to turn that into the *report and presentation*. Semester B still has to finish the mixed/hold write-up, Interim Report II, the Final Report, and a rehearsed demo. If Outlook PST parsing overruns, the demo stays on mbox and the report says so.

**Risks.** Hostile Outlook mailbox format → ship mbox. No real multi-tenant trace → named synthetic or public substitute. Mixed and hold bugs → leftover-store tests before any success claim. Key store backed up with chunks → shorter or independently shreddable key retention, documented.

---

## AI Usage Plan & Considerations

This project uses AI-assisted tools (including Cursor) as a **drafting and implementation aid**, not as an authority on novelty, law, or experimental truth.

**Intended uses.**

- Clarify and compress prose for plans and reports; keep the problem statement and terms consistent.
- Search and summarise related work **as candidates**, then open the paper or primary page before citing.
- Draft Python for the store, parsers, tests, and measurement program from the written spec.
- Explain failures (restore leak, wrap bugs) and propose patches that are then run under the test suite.
