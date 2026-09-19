# Subject-scoped erasure in a deduplicated, immutable backup

Research plan for **one problem**: a backup store that shares identical bytes cannot, without extra design, both **keep history immutable** and **forget one person**.

This project is only that conflict. It is not a new chunking algorithm.

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

**Personal data.** Information that relates to an identified or identifiable subject (GDPR-style). A public ISO or a shared app binary is typically **not** personal data. A mailbox, photo of a person, or HR row **is**. This project does not implement a legal classifier; the prototype **labels** files or regions as `unique` / `identical` / `mixed` so the policy can be tested.

**Controller / operator.** Whoever runs the backup store and must perform `erase(S)` and still restore everyone else.

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

**Mixed.** One stored region contains personal data of **more than one** subject (family photo, shared mailbox, spreadsheet with two employees). After `erase(Alice)`, Alice’s contribution must be unrecoverable, and Bob must still get a restorable object that no longer yields Alice. You cannot keep one shared ciphertext and satisfy both unless you rewrite or split the object.

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

**Legal hold / retention.** A snapshot or record that **must not** be erased yet (litigation, statutory retention). `erase(S)` may have to wait, or apply only after the hold lifts. The key store must not shred a key that a hold still requires.

**Restore.** Rebuild files from a snapshot’s recipes plus chunks plus keys. After `erase(S)`, restore(`S`, anything) must fail for `S`’s personal data; restore(`T`, old snapshot) must still succeed for `T ≠ S`.

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

Details: [docs/method.md](docs/method.md).

---

## Related work (one paragraph)

Boneh & Lipton (USENIX Security 1996) and Perlman’s Ephemerizer/FADE line invent cryptographic erasure of backups. **FadeVersion** (Rahumed et al., 2011) adds layered keys so you can delete a **version** without breaking other versions that share an object. Botelho et al. (FAST 2013) **sanitize** unreferenced chunks in Data Domain. Strzelczak et al. (FAST 2013) **GC** shared chunks in HYDRAstor. Database papers (Shastri et al., PVLDB 2020; Sarkar et al.) shred **rows** in DB backups. DupLESS et al. encrypt so you can still **dedup**. None specifies `erase(subject)` when chunks are shared, snapshots are immutable, and content may be mixed. Full list: [docs/related-work.md](docs/related-work.md).

---

## Objectives

1. Freeze the problem statement and the glossary above; cite FadeVersion, FADE, Boneh–Lipton, Botelho sanitization, and DupLESS so the leftover is not overclaimed.
2. Specify the key/layout rules for `unique`, `identical`, and `mixed` under an immutable snapshot log and a mutable key store.
3. Implement a laptop-scale store: ingest, restore, `erase(S)`, owner sets, OR-wrap, AND-wrap, copy-out.
4. Measure extra unique bytes, erase latency, and restore success/failure on a synthetic two-subject corpus.
5. Write the report so a leak on mixed+OR-wrap and a space hit on no-cross-user-share are expected results, not surprises.

---

## Scope

**In**

- Subject-scoped erase in a chunk-addressed backup with immutable snapshots.
- Explicit unique / identical / mixed classes and OR vs AND vs no-share vs copy-out.
- Synthetic multi-subject corpus; honest threat model (leftover store + remaining keys).
- Comparison to FadeVersion-style **version** delete (already solved) vs **subject** delete (this work).

**Out**

- A new CDC algorithm or video remux hasher.
- Legal advice or an automatic PII detector (labels are inputs).
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
| Corpus | Synthetic two-subject files (unique / identical / mixed) |
| Eval | Ingest → share → erase → restore checks + unique-byte counts |

---

## Success criteria

- After `erase(Alice)` on **unique** data: Alice cannot restore; chunks are shredded or GC’d; Bob is unaffected.
- After `erase(Alice)` on **identical** shareable data: Alice cannot restore her snapshot; Bob’s restore byte-matches the original; unique bytes stay near one copy.
- After `erase(Alice)` on **mixed** data: Alice’s bytes are not recoverable from the store plus Bob’s remaining keys; Bob gets a defined outcome (copy-out success, or an explicit “old snapshot cannot keep this file” failure)—not a silent leak.
- AND-wrap and no-cross-user-share are implemented as baselines and lose either Bob’s restore or space, as predicted.
- The write-up names FadeVersion’s version-scoped leftover and does not claim Boneh-style shredding is new.

---

## Schedule

| Phase | Focus |
|---|---|
| A | Freeze claim, glossary, and related work (this document) |
| B | Data model: chunks, recipes, owner sets, key wraps |
| C | `erase(S)` + restore for unique and identical; tests for the mixed leak under OR-wrap |
| D | Copy-out / refusal policy for mixed + immutable snapshots; space/restore measurements |
| E | Write-up: problem, definitions, design, limits |

---

## Status

This repository’s **plan** is the erasure problem above. The implementation of the store is the next phase (Phase B).
