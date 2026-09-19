# Subject-scoped erasure in a deduplicated, immutable backup

Research plan for **one problem**: a backup store that shares identical bytes cannot, without extra design, both **keep history immutable** and **forget one person**.

This project is only that conflict. It is not a new chunking algorithm.

**Core** is a labeled two-subject store (unique / identical / mixed blobs). **PhD layer** adds (1) mixed **containers** — one PST/mbox and one photo library with two subjects, (2) **holds vs erase**, and (3) a **real multi-tenant trace**.

- Definitions and design: [docs/method.md](docs/method.md)
- Related work: [docs/related-work.md](docs/related-work.md)
- Planned evaluation: [docs/evaluation.md](docs/evaluation.md)

---

## Problem statement

**Given** a backup system that (1) **deduplicates** so that identical content is stored once and referenced from many files, users, and snapshots, and (2) treats retained snapshots as **immutable** (they must stay restorable and must not be silently rewritten),

**construct** a store and a key/layout policy such that `erase(S)` for a **data subject** `S` makes `S`’s personal data **unrecoverable** from every retained snapshot—including snapshots that still contain other people’s data that **byte-shares** with `S`—

**while** every other subject who still has a right to that content can **restore** their own snapshots, and while we can **measure** the extra space and restore cost versus “never share across subjects.”

The failure mode today is simple. If Alice and Bob both backup the same bytes, there is one physical chunk and two recipes. Deleting Alice’s recipe does not remove the bytes. Destroying a key that wraps that chunk blinds Bob. Rewriting last Tuesday’s snapshot to drop Alice breaks immutability. Nested “all policies must remain” wrapping (FadeVersion’s multi-policy sketch) deletes the object for everyone when any one person is erased.

**The research leftover:** specify and implement erase of a **subject** when the unit of sharing is a **chunk**, the snapshot is **WORM**, and a chunk may be **mixed** (more than one subject’s personal data in the same bytes). FadeVersion already shows how to shred a *version* or *file* without breaking other versions that share an object. Database crypto-erasure shreds a *row*. Physical sanitization wipes *unreferenced* chunks. None of those is subject-scoped erase under immutability and mixed content.

---

## Definitions

These terms are used with these meanings only.

### People and data

**Data subject.** The natural person whose personal data the store must be able to forget. In this project a subject is an identifier `S` (for example `alice`). Erase is `erase(S)`, not “delete file F” and not “delete snapshot V.”

**Personal data.** Information that relates to an identified or identifiable subject (GDPR-style). A public ISO or a shared app binary is typically **not** personal data. A mailbox, photo of a person, or HR row **is**. The core prototype **labels** files or regions as `unique` / `identical` / `mixed`. The PhD layer parses **real mixed containers** (below) instead of only trusting a whole-file label.

**Controller / operator.** Whoever runs the backup store and must perform `erase(S)` and still restore everyone else.

**Tenant.** A billing or isolation boundary that may contain many subjects (a company, a family iCloud account, one backup client). Cross-user share can happen **inside** a tenant (Alice and Bob at the same firm) or **across** tenants (two firms both backup the same installer). A **multi-tenant trace** records who ingested what, and when, across tenants.

### How a deduplicated backup is laid out

**File.** A named byte sequence the user thinks of as one object (`inbox.pst`, `photo.jpg`).

**Chunk.** The unit the store actually shares. A file is split into chunks (fixed size or content-defined). Each chunk has a **fingerprint** (cryptographic hash of its bytes) and is stored at most once.

**Deduplication.** If two files, users, or snapshots produce the same chunk bytes, the store keeps **one physical copy** and records multiple **references**. That is the space win. It is also why erase is hard: a chunk has **many owners**.

**Recipe (file recipe).** The metadata that rebuilds one file: ordered list of chunk ids (and sizes). Recipes are per file per snapshot. They are small; chunks are large.

**Snapshot (backup version).** A point-in-time set of recipes for one user’s (or one machine’s) files. “Restore Tuesday” means: read Tuesday’s recipes, fetch the chunks, write the files out.

**Cross-version sharing.** Tuesday and Wednesday share chunks that did not change. This is ordinary backup dedup.

**Cross-user sharing.** Alice and Bob independently backup the same bytes, so they share a physical chunk. This is the case that fights subject erase.

**Owner set of a chunk.** The set of subjects (and snapshots) whose recipes still reference that chunk. `erase(S)` must remove `S` from every owner set and then decide what to do with the chunk.

### Three file classes (the test corpus)

**Unique.** Bytes that appear in only one subject’s backups. Erase is easy: drop recipes, shred that subject’s wraps, garbage-collect the chunk.

**Identical (shareable).** The same bytes appear in two subjects’ backups, and the content is **not** treated as either subject’s exclusive personal data (for example a shared installer). After `erase(Alice)`, Bob must still restore; Alice must not restore from *her* recipes. The physical chunk may stay.

**Mixed (labeled blob).** One stored region is tagged as containing personal data of **more than one** subject. After `erase(Alice)`, Alice’s contribution must be unrecoverable, and Bob must still get a restorable object that no longer yields Alice. You cannot keep one shared ciphertext and satisfy both unless you rewrite or split the object. The core prototype uses this label.

**Mixed container (PhD).** A *real file or library* that interleaves more than one subject, so the interesting unit is **inside** the file, not the file name.

- **Shared mailbox / one PST (or mbox).** Outlook `.pst` / `.ost` or an mbox is one backup object. Messages, attachments, and contacts belong to different subjects (Alice sent, Bob received, Carol is in the thread). Chunks may be Alice-only, Bob-only, or still mixed (one MIME part with both names; one attachment both were sent).
- **One photo library with two subjects.** A single library (Apple Photos-style package, a shared album zip, or a directory plus sidecar DB) holds photos of Alice, of Bob, and of **both** (group shots). Erase must drop Alice’s items and Alice-in-group-shots without deleting Bob’s solo photos. Thumbnails and the library DB are themselves mixed metadata.

For these, ingest must **parse** the container, label *inner* objects (messages, attachments, photos), and apply unique / identical / mixed **per inner object**. Whole-file OR-wrap of the PST is the leak the PhD chapter exists to close.

### Delete, erase, and “gone”

**Logical delete.** Remove a recipe or mark a file unused. The chunk bytes usually remain. This is what ordinary backup “delete this snapshot” does until garbage collection.

**Garbage collection (GC).** Reclaim physical chunks whose owner set is empty. GC does **not** by itself make leftover copies on old media unreadable, and it cannot drop a chunk that Bob still needs.

**Physical delete / sanitization.** Overwrite or copy-forward-and-erase so unreferenced bytes are gone from the device (Botelho et al., FAST 2013). This **rewrites** the store. It assumes the chunk is already unreferenced. It is the opposite of “this snapshot is frozen.”

**Cryptographic erasure (assured deletion / crypto-shredding).** Encrypt the data under a key; “delete” by destroying the key so leftover ciphertext is computationally useless. This is how you erase inside media you are not allowed to rewrite (tapes, cloud replicas, WORM). Invented for backups by Boneh and Lipton (1996); policy form in FADE / FadeVersion.

**Unrecoverable.** A computationally bounded attacker who gets the leftover store, all remaining keys, and all remaining recipes cannot obtain subject `S`’s personal data. If Bob still holds a wrap of the same `k` that encrypts Alice’s mixed bytes, Alice is **not** unrecoverable.

**Residual ciphertext.** Encrypted bytes that remain on immutable media after a shred. Harmless if no key remains; a leak if any wrap of `k` remains.

### Keys and wrapping

**Data-encryption key (DEK, `k`).** Random key that encrypts one chunk (or one object): store `{chunk}_k`.

**Control key (wrap key, `s`).** Key that encrypts a DEK for one policy: store `{k}_s` next to a recipe or in a key store. Destroying `s` is how that policy loses access.

**Key escrow / key store.** Separate, mutable store of control keys. Snapshots of **data** may be immutable; the key store must be allowed to shred, or erase cannot happen.

**OR-wrap.** Each entitled subject has their own `{k}_{s_i}`. Any remaining `s_i` decrypts `k`. `erase(Alice)` shreds `s_Alice` only. Bob still reads the chunk. Correct for **identical/shareable** content; **wrong** for **mixed** content (Alice’s bytes stay readable via Bob).

**AND-wrap (conjunctive / nested).** `k` is wrapped so that **every** listed policy is needed, or so that revoking **any** policy destroys `k` (FadeVersion’s nested multi-policy sketch). Then `erase(Alice)` can make the chunk unreadable for Bob as well. Correct only if nobody else should keep the object.

**Copy-out (re-encrypt / split).** On `erase(S)`, if a chunk is mixed or must not stay shared, write a new object for the remaining subjects (new bytes or new `k'`) and stop using the old `k` for them. Costs space and, if you rewrite an old snapshot, breaks immutability. If you only copy-out **future** backups, old snapshots still hold the mixed ciphertext.

### Immutability and holds

**Immutable snapshot / WORM / vault.** A retained backup must stay bit-for-bit restorable and must not be editable by ransomware or by a routine “please drop Alice from Tuesday.” Typical product goal: nobody (including a compromised admin) can encrypt or delete history.

**Legal hold / retention.** A pin on a snapshot, file, tenant, or subject that **forbids shred** until the pin lifts (litigation, statutory keep, tax). Holds are first-class in the PhD layer, not a footnote.

**Hold vs erase.** `erase(S)` and a hold can target overlapping bytes:

| Situation | Required outcome |
|---|---|
| Hold on Alice’s own snapshot, then `erase(Alice)` | **Defer.** Do not shred `s_Alice` or Alice-only DEKs until the hold lifts. Queue a **deferred erase**. |
| Hold on Bob’s snapshot that **OR-shares** an identical installer with Alice, then `erase(Alice)` | Shred Alice’s wrap and recipes. **Do not** shred `k` while Bob’s hold (or Bob) still needs it. |
| Hold on a **mixed** PST / photo library that contains Alice and Bob, then `erase(Alice)` | Cannot rewrite the held snapshot. Keep the mixed ciphertext while the hold is live (Alice is **not** yet unrecoverable from that snapshot). When the hold lifts, run deferred erase: copy-out Bob’s inner objects, then shred Alice’s remaining wraps. |
| `erase(Alice)` completes, then a hold is requested on Alice | Too late for those keys if already shredded. Hold only applies to data still recoverable. |
| Two holds (regulator keep vs subject erase) | Erase waits; the plan records **why** and **until when**. Restore of a held mixed snapshot may still yield Alice — that is the documented cost of the hold, not a silent leak. |

**Deferred erase.** Work queued by `erase(S)` that cannot shred yet because a hold still references those keys or snapshots. When the last blocking hold lifts, the queue runs automatically: same rules as immediate erase.

**Restore.** Rebuild files from a snapshot’s recipes plus chunks plus keys. After `erase(S)` and after any deferred erase has run, restore(`S`, anything) must fail for `S`’s personal data; restore(`T`, old snapshot) must still succeed for `T ≠ S` unless that snapshot was mixed and marked unrestorable. While a hold blocks erase, restore of the held object may still contain `S` — the API must say so.

### What this project is not

**New CDC / FastCDC variant.** Chunking is a given; the question is ownership and keys.

**Encrypted deduplication (DupLESS, convergent encryption).** Those make ciphertexts match so the server can share space. They do **not** define `erase(S)`. Same ciphertext ⇒ leftover decryptability for whoever still has a message-derived key.

**Perceptual / near-duplicate matching.** Irrelevant here.

---

## Why the three goals fight

| Goal | Mechanism | What it wants |
|---|---|---|
| Save space | One physical chunk, many recipes | Share `k` and the bytes |
| Survive ransomware | Immutable snapshots | Do not rewrite Tuesday |
| Forget Alice | Unrecoverable personal data | Destroy every path to Alice’s bytes |

On **unique** data, all three can hold: shred Alice’s keys, GC the chunk if unused, leave other snapshots alone.

On **identical** shareable data, space and immutability hold if you OR-wrap; Alice loses her recipe/wrap; Bob keeps the chunk. “Forget Alice” here means Alice cannot restore **her** copy, not that the bytes vanish from the earth.

On **mixed** data, you cannot share one `{chunk}_k` and also forget Alice while Bob restores the same snapshot. You must **not share** (per-subject encryption, no cross-user dedup), **split** the object (copy-out), or **accept** that Bob’s restore still contains Alice (then you have not erased).

---

## Method (planned)

1. Ingest files labeled with a subject and a class (`unique` / `identical` / `mixed`).
2. Chunk and store `{chunk}_k` with an **owner set** and one wrap per entitled subject (**OR-wrap** by default).
3. `erase(S)`: drop `S`’s recipes; shred `s_S`; remove `S` from owner sets.
4. If a chunk’s owner set is empty → shred `k` (and GC when allowed).
5. If a chunk is **mixed** and `S` was an owner → **copy-out** remaining subjects to a new object that no longer contains `S` (or refuse and report that immutability forbids in-place rewrite of old snapshots). New snapshots of remaining subjects use the copy-out; old snapshots either fail a mixed-erase check or are marked unrestorable for the mixed file.
6. Baselines in the same store: (a) **no cross-user share** (per-subject encryption, FadeVersion-style version share only); (b) **AND-wrap**; (c) **OR-wrap without copy-out** (shows the mixed-content leak).
7. **PhD — mixed containers:** parse a PST/mbox and a two-subject photo library into inner objects; run erase on inner labels, not the whole file.
8. **PhD — holds:** `hold(...)` / `release(...)`; `erase(S)` becomes immediate or **deferred**; never shred a key a live hold still needs.
9. **PhD — multi-tenant trace:** replay a real (or published) multi-tenant ingest log, assign subjects/tenants, measure share vs erase vs hold cost at that mix.

Details: [docs/method.md](docs/method.md).

---

## Related work (one paragraph)

Boneh & Lipton (USENIX Security 1996) and Perlman’s Ephemerizer/FADE line invent cryptographic erasure of backups. **FadeVersion** (Rahumed et al., 2011) adds layered keys so you can delete a **version** without breaking other versions that share an object. Botelho et al. (FAST 2013) **sanitize** unreferenced chunks in Data Domain. Strzelczak et al. (FAST 2013) **GC** shared chunks in HYDRAstor. Database papers (Shastri et al., PVLDB 2020; Sarkar et al.) shred **rows** in DB backups. DupLESS et al. encrypt so you can still **dedup**. None specifies `erase(subject)` when chunks are shared, snapshots are immutable, and content may be mixed. Full list: [docs/related-work.md](docs/related-work.md).

---

## Objectives

**Core (enough for a complete prototype / MSc-scale write-up)**

1. Freeze the problem statement and the glossary above; cite FadeVersion, FADE, Boneh–Lipton, Botelho sanitization, and DupLESS so the leftover is not overclaimed.
2. Specify the key/layout rules for `unique`, `identical`, and labeled `mixed` under an immutable snapshot log and a mutable key store.
3. Implement a laptop-scale store: ingest, restore, `erase(S)`, owner sets, OR-wrap, AND-wrap, copy-out.
4. Measure extra unique bytes, erase latency, and restore success/failure on a synthetic two-subject corpus.
5. Write so a leak on mixed+OR-wrap and a space hit on no-cross-user-share are expected results, not surprises.

**PhD layer (in scope for the full thesis, not optional footnotes)**

6. **Mixed containers.** Ingest one **PST/mbox** and one **photo library** that each contain two subjects. Parse to messages / attachments / photos; erase Alice inside the container; Bob’s remaining inner objects restore; Alice is not recoverable from leftover store + Bob’s keys.
7. **Holds vs erase.** Implement hold, release, and deferred erase. Show the four cases in the hold table (hold-then-erase on Alice; hold on Bob’s shared identical chunk; hold on mixed container; erase-then-hold). Measure how long Alice remains recoverable while a hold is live, and that shred runs when the last hold lifts.
8. **Real multi-tenant trace.** Replay a published or obtained multi-tenant backup trace (or the closest public proxy: FSL-style backup streams labeled into tenants/subjects). Report how much data is unique vs identical vs container-mixed, and the space/restore/unrecoverability cost of `erase` + holds on that mix. If a true multi-tenant trace cannot be released, document the substitute and what it cannot prove.

---

## Scope

**In (core)**

- Subject-scoped erase in a chunk-addressed backup with immutable snapshots.
- Explicit unique / identical / labeled-mixed classes and OR vs AND vs no-share vs copy-out.
- Synthetic multi-subject corpus; honest threat model (leftover store + remaining keys).
- Comparison to FadeVersion-style **version** delete (already solved) vs **subject** delete (this work).

**In (PhD layer)**

- Mixed **containers**: one shared PST/mbox and one two-subject photo library, parsed to inner objects.
- **Holds vs erase**: hold/release, deferred shred, documented window where a held mixed snapshot still yields the subject.
- A **real multi-tenant trace** (or a named public substitute) with tenant/subject labels, share statistics, and erase/hold cost.

**Out**

- A new CDC algorithm.
- Legal advice. Automatic PII detection may be a *heuristic helper* for labeling a trace; it is not the contribution.
- Production key hardware, SGX, or blockchain.
- Encrypted-dedup brute-force resistance (DupLESS) as the contribution.
- Physical drive-level overwrite as the only delete mechanism.
- Near-duplicate / perceptual matching (a group photo is mixed because both people are in it, not because two photos “look similar”).

---

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Store | In-repo chunk store + recipes + key store |
| Chunks | Content-defined or fixed-size (implementation detail) |
| Crypto | AES-GCM (or equivalent) for `{chunk}_k`; control keys in a local escrow |
| Corpus (core) | Synthetic two-subject files (unique / identical / labeled mixed) |
| Corpus (PhD) | Synthetic PST/mbox + two-subject photo library; multi-tenant ingest trace |
| Eval | Ingest → share → hold/erase → restore checks + unique-byte counts |

---

## Success criteria

- After `erase(Alice)` on **unique** data: Alice cannot restore; chunks are shredded or GC’d; Bob is unaffected.
- After `erase(Alice)` on **identical** shareable data: Alice cannot restore her snapshot; Bob’s restore byte-matches the original; unique bytes stay near one copy.
- After `erase(Alice)` on **labeled mixed** data: Alice’s bytes are not recoverable from the store plus Bob’s remaining keys; Bob gets a defined outcome (copy-out success, or an explicit “old snapshot cannot keep this file” failure)—not a silent leak.
- AND-wrap and no-cross-user-share are implemented as baselines and lose either Bob’s restore or space, as predicted.
- **PhD — PST / photo library:** `erase(Alice)` removes Alice’s messages/photos (and Alice from group items by copy-out or drop); Bob’s remaining items restore; whole-file wrap of the container is shown as the leak baseline.
- **PhD — holds:** a live hold blocks shred of the keys it still needs; after `release`, deferred erase meets the same unrecoverability checks as immediate erase. The hold window is measured, not hidden.
- **PhD — multi-tenant trace:** report share mix and erase/hold cost on that trace; do not generalize beyond what the trace contains.
- The write-up names FadeVersion’s version-scoped leftover and does not claim Boneh-style shredding is new.

---

## Schedule

| Phase | Focus |
|---|---|
| A | Freeze claim, glossary, and related work (this document) |
| B | Data model: chunks, recipes, owner sets, key wraps |
| C | `erase(S)` + restore for unique and identical; tests for the labeled-mixed leak under OR-wrap |
| D | Copy-out / refusal policy for labeled mixed + immutable snapshots; space/restore measurements |
| E | **PhD:** PST/mbox + two-subject photo library parsers; inner-object erase |
| F | **PhD:** hold / release / deferred erase; hold-vs-erase cases |
| G | **PhD:** multi-tenant trace ingest and measurements |
| H | Write-up: problem, definitions, core results, PhD-layer results, limits |

---

## Status

This repository’s **plan** is the erasure problem above. The implementation of the store is the next phase (Phase B).
