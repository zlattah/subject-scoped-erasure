# Subject-scoped erasure in a deduplicated, immutable backup

A backup store that shares identical bytes cannot, without extra design, both **keep history immutable** and **forget one person**. This project is that conflict: a store, a key/layout policy, and the real objects that make the policy hard — shared mailboxes, photo libraries, legal holds, and more than one tenant. It is not a new chunking algorithm.

- Working project plan: [projectplan.md](projectplan.md)
- English-class interim report: [english-class-interim-report.md](english-class-interim-report.md)
- Definitions and design: [docs/method.md](docs/method.md)
- Related work: [docs/related-work.md](docs/related-work.md)
- Planned evaluation: [docs/evaluation.md](docs/evaluation.md)

---

## Motivation

Enterprise backup (Veeam, Rubrik, Cohesity, Data Domain) **deduplicates** across machines and now sells **immutable / Object Lock** vaults so ransomware cannot delete history. The same vault still holds last month’s mail, file shares, and laptop images. When HR offboards someone, or a customer exercises GDPR/CCPA erasure, the live app can drop the account; the backup chain often cannot be rewritten for 30–365 days or longer.

That pattern is not only “the VM backup appliance.” Multi-tenant SaaS, Microsoft 365 / Google Workspace archives, and shared mailboxes or photo libraries have the same shape: one store, many subjects, and objects that are **mixed** (one PST, one Teams site, one family album). On that same vault, legal hold vs erase is already a daily eDiscovery fight — keep this mailbox, forget Alice.

Regulators treat those leftover copies as in scope. The ICO says a valid erasure request must cover backups, or those copies must be put **beyond use** until they rotate, and must not be restored into production. The EDPB’s coordinated action on the right to erasure lists **deletion from backups** as a main failure, and questions whether “wait for the job to age out” is **without undue delay** when retention is long. What operators do today is wait, lock, restore-and-edit by hand, or crypto-shred a **whole tenant**. That can be acceptable for a 7-day backup and a single owner. It fails when immutability is long, chunks are shared, and the file is mixed. The rest of this plan is the store you would need in that setting.

---

## Problem statement

**Given** a backup system that (1) **deduplicates** so that identical content is stored once and referenced from many files, users, and snapshots, and (2) treats retained snapshots as **immutable** (they must stay restorable and must not be silently rewritten),

**construct** a store and a key/layout policy such that `erase(S)` for a **data subject** `S` makes `S`’s personal data **unrecoverable** from every retained snapshot—including snapshots that still contain other people’s data that **byte-shares** with `S`—

**while** every other subject who still has a right to that content can **restore** their own snapshots, and while we can **measure** the extra space and restore cost versus “never share across subjects.”

The failure mode is the same one the motivation runs into. If Alice and Bob both backup the same bytes, there is one physical chunk and two recipes. Deleting Alice’s recipe does not remove the bytes. Destroying a key that wraps that chunk blinds Bob. Rewriting last Tuesday’s snapshot to drop Alice breaks immutability. Nested “all policies must remain” wrapping (FadeVersion’s multi-policy sketch) deletes the object for everyone when any one person is erased.

So the leftover is not “invent shredding” (Boneh already did) and not “delete a version without breaking the next one” (FadeVersion already did). It is erase of a **subject** when the unit of sharing is a **chunk**, the snapshot is **WORM**, the bytes may be **mixed**, a **hold** may forbid shred, and the workload may span **tenants**. The glossary below is the vocabulary for that leftover.

---

## Definitions

These terms are used with these meanings only. They build from people, to how the store is laid out, to how “gone” is allowed to happen.

### People and data

**Data subject.** The natural person whose personal data the store must be able to forget. Here a subject is an identifier `S` (for example `alice`). Erase is `erase(S)`, not “delete file F” and not “delete snapshot V.”

**Personal data.** Information that relates to an identified or identifiable subject (GDPR-style). A public ISO or a shared app binary is typically **not** personal data. A mailbox, a photo of a person, or an HR row **is**. The store is told which bytes are whose — either by a label on a file or region (`unique` / `identical` / `mixed`), or by parsing a container (messages in a PST, items in a photo library). The parser is not a legal classifier; it is how mixed files become labeled inner objects.

**Controller / operator.** Whoever runs the backup store and must perform `erase(S)` and still restore everyone else.

**Tenant.** A billing or isolation boundary that may contain many subjects (a company, a family iCloud account, one backup client). Sharing can happen **inside** a tenant (Alice and Bob at the same firm) or **across** tenants (two firms both backup the same installer). A **multi-tenant trace** records who ingested what, and when, across tenants — the workload this design is measured on, not a second project.

### How a deduplicated backup is laid out

**File.** A named byte sequence the user thinks of as one object (`inbox.pst`, `photo.jpg`).

**Chunk.** The unit the store actually shares. A file is split into chunks (fixed size or content-defined). Each chunk has a **fingerprint** (cryptographic hash of its bytes) and is stored at most once.

**Deduplication.** If two files, users, or snapshots produce the same chunk bytes, the store keeps **one physical copy** and records multiple **references**. That is the space win, and why erase is hard: a chunk has **many owners**.

**Recipe (file recipe).** The metadata that rebuilds one file: ordered list of chunk ids (and sizes). Recipes are per file per snapshot. They are small; chunks are large.

**Snapshot (backup version).** A point-in-time set of recipes for one user’s (or one machine’s) files. “Restore Tuesday” means: read Tuesday’s recipes, fetch the chunks, write the files out.

**Cross-version sharing.** Tuesday and Wednesday share chunks that did not change. Ordinary backup dedup.

**Cross-user sharing.** Alice and Bob independently backup the same bytes, so they share a physical chunk. This is the case that fights subject erase.

**Owner set of a chunk.** The set of subjects (and snapshots) whose recipes still reference that chunk. `erase(S)` must remove `S` from every owner set and then decide what to do with the chunk.

### Three file classes

These three classes are the same policy problem at three granularities: a whole file, a labeled blob, or an object *inside* a mailbox or library.

**Unique.** Bytes that appear in only one subject’s backups. Erase is easy: drop recipes, shred that subject’s wraps, garbage-collect the chunk.

**Identical (shareable).** The same bytes appear in two subjects’ backups, and the content is **not** treated as either subject’s exclusive personal data (for example a shared installer). After `erase(Alice)`, Bob must still restore; Alice must not restore from *her* recipes. The physical chunk may stay.

**Mixed.** One stored region contains personal data of **more than one** subject. After `erase(Alice)`, Alice’s contribution must be unrecoverable, and Bob must still get a restorable object that no longer yields Alice. You cannot keep one shared ciphertext and satisfy both unless you rewrite or split the object.

In the simplest tests the region is a **labeled blob**. In the setting from the motivation it is a **container** that interleaves people, so the interesting unit is inside the file:

- **Shared mailbox / one PST (or mbox).** One backup object. Messages, attachments, and contacts belong to different subjects (Alice sent, Bob received, Carol is in the thread). Inner chunks may be Alice-only, Bob-only, or still mixed (one MIME part with both names; one attachment both were sent).
- **One photo library with two subjects.** One library (Photos-style package, shared album, or a directory plus sidecar DB) holds photos of Alice, of Bob, and of **both**. Erase must drop Alice’s items without deleting Bob’s solo photos. Thumbnails and the library DB are themselves mixed metadata.

Ingest therefore **parses** the container, labels *inner* objects (messages, attachments, photos), and applies unique / identical / mixed **per inner object**. Wrapping the whole PST as one OR-wrapped blob is the leak that parsing exists to close.

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

**OR-wrap.** Each entitled subject has their own `{k}_{s_i}`. Any remaining `s_i` decrypts `k`. `erase(Alice)` shreds `s_Alice` only. Bob still reads the chunk. Correct for **identical** content; **wrong** for **mixed** content (Alice’s bytes stay readable via Bob).

**AND-wrap (conjunctive / nested).** `k` is wrapped so that **every** listed policy is needed, or so that revoking **any** policy destroys `k` (FadeVersion’s nested multi-policy sketch). Then `erase(Alice)` can make the chunk unreadable for Bob as well. Correct only if nobody else should keep the object.

**Copy-out (re-encrypt / split).** On `erase(S)`, if a chunk is mixed or must not stay shared, write a new object for the remaining subjects (new bytes or new `k'`) and stop using the old `k` for them. Costs space and, if you rewrite an old snapshot, breaks immutability. If you only copy-out **future** backups, old snapshots still hold the mixed ciphertext.

### Immutability and holds

**Immutable snapshot / WORM / vault.** A retained backup must stay bit-for-bit restorable and must not be editable by ransomware or by a routine “please drop Alice from Tuesday.” Typical product goal: nobody (including a compromised admin) can encrypt or delete history.

**Legal hold / retention.** A pin on a snapshot, file, tenant, or subject that **forbids shred** until the pin lifts (litigation, statutory keep, tax). Holds are part of the same `erase` path: they delay shred, they do not invent a second store.

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

**Perceptual / near-duplicate matching.** A group photo is mixed because both people are in it, not because two photos “look similar.”

---

## Why the three goals fight

The motivation asked for space savings, a frozen vault, and a forgotten person. Those three pull the store in different directions:

| Goal | Mechanism | What it wants |
|---|---|---|
| Save space | One physical chunk, many recipes | Share `k` and the bytes |
| Survive ransomware | Immutable snapshots | Do not rewrite Tuesday |
| Forget Alice | Unrecoverable personal data | Destroy every path to Alice’s bytes |

On **unique** data, all three can hold: shred Alice’s keys, GC the chunk if unused, leave other snapshots alone.

On **identical** shareable data, space and immutability hold if you OR-wrap; Alice loses her recipe/wrap; Bob keeps the chunk. “Forget Alice” here means Alice cannot restore **her** copy, not that the bytes vanish from the earth.

On **mixed** data, you cannot share one `{chunk}_k` and also forget Alice while Bob restores the same snapshot. You must **not share** (per-subject encryption, no cross-user dedup), **split** the object (copy-out), or **accept** that Bob’s restore still contains Alice (then you have not erased). Holds only make the last case last longer: Alice stays recoverable until the pin lifts.

---

## Method (planned)

The store is one pipeline. Labels, containers, holds, and traces are inputs to the same ingest / erase / restore path.

1. Ingest files (or inner objects from a parsed PST/mbox or photo library) with a subject and a class (`unique` / `identical` / `mixed`).
2. Chunk and store `{chunk}_k` with an **owner set** and one wrap per entitled subject (**OR-wrap** by default).
3. `erase(S)`: drop `S`’s recipes that are not on hold; shred `s_S` when no hold pins it; remove `S` from owner sets. If a hold is live, queue **deferred erase** instead of shredding.
4. If a chunk’s owner set is empty and unpinned → shred `k` (and GC when allowed).
5. If a chunk is **mixed** and `S` was an owner → **copy-out** remaining subjects to a new object that no longer contains `S` (or refuse and report that immutability forbids in-place rewrite of old snapshots). New snapshots of remaining subjects use the copy-out; old snapshots either fail a mixed-erase check or are marked unrestorable for the mixed file.
6. Compare, in the same store: (a) **no cross-user share**; (b) **AND-wrap**; (c) **OR-wrap without copy-out** (the mixed leak); (d) whole-file wrap of a PST/library vs inner-object erase.
7. Replay a multi-tenant ingest log through that store and measure share vs erase vs hold cost on that mix.

Details: [docs/method.md](docs/method.md).

---

## Related work

Boneh & Lipton (USENIX Security 1996) and Perlman’s Ephemerizer/FADE line invent cryptographic erasure of backups. **FadeVersion** (Rahumed et al., 2011) adds layered keys so you can delete a **version** without breaking other versions that share an object. Botelho et al. (FAST 2013) **sanitize** unreferenced chunks in Data Domain. Strzelczak et al. (FAST 2013) **GC** shared chunks in HYDRAstor. Database papers (Shastri et al., PVLDB 2020; Sarkar et al.) shred **rows** in DB backups. DupLESS et al. encrypt so you can still **dedup**. None specifies `erase(subject)` when chunks are shared, snapshots are immutable, content may be mixed, and a hold may delay shred. Full list: [docs/related-work.md](docs/related-work.md).

---

## Objectives

1. Freeze the problem statement and the glossary above; cite FadeVersion, FADE, Boneh–Lipton, Botelho sanitization, and DupLESS so the leftover is not overclaimed.
2. Specify the key/layout rules for `unique`, `identical`, and `mixed` (labeled blobs and inner objects) under an immutable snapshot log, a mutable key store, and holds.
3. Implement the store: ingest, restore, `erase(S)`, `hold` / `release`, owner sets, OR-wrap, AND-wrap, copy-out, deferred erase.
4. Parse one **PST/mbox** and one **photo library** with two subjects; erase Alice inside the container; restore Bob’s remaining inner objects.
5. Measure extra unique bytes, erase latency, restore success/failure, and the recoverability window while a hold is live, first on a synthetic two-subject corpus, then on a multi-tenant ingest trace (or a named public substitute).
6. Write so a leak on mixed+OR-wrap, a space hit on no-cross-user-share, and a delay while a hold is live are expected results, not surprises.

---

## Scope

**In**

- Subject-scoped erase in a chunk-addressed backup with immutable snapshots.
- Unique / identical / mixed, including mixed **containers** (one PST/mbox and one two-subject photo library) parsed to inner objects.
- OR vs AND vs no-share vs copy-out, plus whole-file wrap as the leak baseline for containers.
- Holds: hold/release, deferred shred, documented window where a held mixed snapshot still yields the subject.
- Synthetic multi-subject corpus and a multi-tenant trace (or named public substitute).
- Threat model: leftover store + remaining keys.
- FadeVersion-style **version** delete as a solved baseline, not the claim.

**Out**

- A new CDC algorithm.
- Legal advice. Automatic PII detection may help label a trace; it is not the contribution.
- Production key hardware, SGX, or blockchain.
- Encrypted-dedup brute-force resistance (DupLESS) as the contribution.
- Physical drive-level overwrite as the only delete mechanism.
- Near-duplicate / perceptual matching.

---

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Store | In-repo chunk store + recipes + key store |
| Chunks | Content-defined or fixed-size (implementation detail) |
| Crypto | AES-GCM (or equivalent) for `{chunk}_k`; control keys in a local escrow |
| Corpus | Synthetic two-subject files; synthetic PST/mbox + two-subject photo library; multi-tenant ingest trace |
| Eval | Ingest → share → hold/erase → restore checks + unique-byte counts |

---

## Success criteria

- After `erase(Alice)` on **unique** data: Alice cannot restore; chunks are shredded or GC’d; Bob is unaffected.
- After `erase(Alice)` on **identical** shareable data: Alice cannot restore her snapshot; Bob’s restore byte-matches the original; unique bytes stay near one copy.
- After `erase(Alice)` on **mixed** data (labeled or inside a container): Alice’s bytes are not recoverable from the store plus Bob’s remaining keys; Bob gets a defined outcome (copy-out, drop, or an explicit “old snapshot cannot keep this file” failure)—not a silent leak.
- On a PST/library, Alice’s messages/photos are gone from her restore; Bob’s remaining items restore; whole-file wrap of the container is shown as the leak baseline.
- AND-wrap and no-cross-user-share lose either Bob’s restore or space, as predicted.
- A live hold blocks shred of the keys it still needs; after `release`, deferred erase meets the same unrecoverability checks as immediate erase. The hold window is measured, not hidden.
- The multi-tenant trace reports share mix and erase/hold cost; the write-up does not generalize beyond what the trace contains.
- The write-up names FadeVersion’s version-scoped leftover and does not claim Boneh-style shredding is new.

---

## Schedule

| Phase | Focus |
|---|---|
| A | Freeze claim, glossary, and related work (this document) |
| B | Data model: chunks, recipes, owner sets, key wraps |
| C | `erase(S)` + restore for unique and identical; tests for the mixed leak under OR-wrap |
| D | Copy-out / refusal for mixed + immutable snapshots; space/restore measurements |
| E | PST/mbox + two-subject photo library parsers; inner-object erase |
| F | Hold / release / deferred erase; hold-vs-erase cases |
| G | Multi-tenant trace ingest and measurements |
| H | Write-up: problem, definitions, results, limits |

---

## Status

The plan above is the whole project. Prototype: `cascade_dedup/erase.py`. Measurements: `python -m cascade_dedup eval` (see [docs/evaluation.md](docs/evaluation.md)).
