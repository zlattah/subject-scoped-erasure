# Method: subject-scoped erase in a shared-chunk backup

The store has three durable parts:

1. **Chunk log** — encrypted chunk payloads `{chunk}_k`, append-only (immutable snapshots refer into it).
2. **Recipes** — per subject, per snapshot, per file: ordered chunk ids. Snapshots are immutable once committed.
3. **Key store** — DEKs and control keys. This part **must** allow shred. If you also WORM the key store, `erase` is impossible.

## Ingest

For each file the caller supplies `subject`, `snapshot_id`, `path`, `bytes`, and `class` ∈ {`unique`, `identical`, `mixed`}.

1. Split into chunks; fingerprint each chunk.
2. If this fingerprint is new: draw random DEK `k`, store `{chunk}_k`, record owner set `{subject}`.
3. If this fingerprint exists:
   - `unique` from a *different* subject is a corpus error (the label lied).
   - `identical`: add `subject` to the owner set; add `{k}_{s_subject}` (OR-wrap). Do not write a second payload.
   - `mixed`: do **not** silently OR-wrap. Either store a **per-subject copy** (no share) or mark the chunk mixed and require copy-out on erase. The default prototype stores mixed files **without** cross-user payload share, and records that a share would have been possible (to measure the cost of correctness).
4. Append a recipe for `(subject, snapshot_id, path)`.

## Restore

`restore(subject, snapshot_id)` reads that snapshot’s recipes, unwraps each DEK with `s_subject`, decrypts chunks, concatenates. Missing key or missing recipe → fail that file.

## Mixed containers (PhD)

Whole-file labels are not enough for mailboxes and libraries.

**PST / mbox.** Parse folders → messages → bodies and attachments. Each inner object gets `subject` set (From/To/Cc as a stand-in label in the prototype; a real system would use a policy table). Attachments that appear in both inboxes are `identical`. A single body that names two people, or a conversation export stored as one blob, is `mixed`. Ingest inner objects as the chunking unit; the PST path is a recipe that lists those inner chunk ids plus leftover container bytes (index, headers).

**Photo library.** Parse the album/package into items (original, derived thumbnail if stored separately, sidecar). Solo Alice / solo Bob = `unique`. The same original ingested under two accounts = `identical`. A group shot labeled Alice+Bob = `mixed` (copy-out = crop/redact is **out of scope**; default is drop the item from Alice’s restore and keep it on Bob only if policy says Bob may retain a photo that includes Alice — the prototype implements **drop-for-Alice, keep-for-Bob** as an explicit, documented leak of Alice’s *likeness* in Bob’s copy, versus **drop-for-both** as the strict unrecoverability option). Measure both policies.

`erase(S)` then runs on inner owner sets, not on “delete the whole PST.”

## Holds (PhD)

The key store tracks `holds`: `{hold_id, target, until?}` where `target` is a snapshot, file, tenant, or subject.

- `hold(target)` increments a pin on every control key and DEK needed to restore that target.
- `erase(S)` still drops Alice’s *future* ingest and her recipes that are **not** pinned. It **must not** shred a key with pin count > 0. Unfinished work goes on a **deferred-erase queue** tagged with `S` and the blocking `hold_id`s.
- `release(hold_id)` decrements pins. When a key’s pin hits 0 and it is queued for `S`, run the rest of `erase(S)` for that key (shred wrap, maybe shred `k`, maybe copy-out).

A restore of a still-held mixed target may return Alice’s bytes. The restore API flags `contains_erased_subject=true` until deferred erase finishes.

## erase(S)

1. Mark all of `S`’s recipes as erased (they are not rewritten in place; they become unrestorable).
2. Shred control key `s_S` in the key store (and any key-store backups under the same policy).
3. For each chunk that listed `S` in its owner set, remove `S`.
4. **Owner set empty:** shred `k`. Payload may remain as residual ciphertext; it is unrecoverable without `k`. Physical GC is optional and may be forbidden if the chunk log is WORM.
5. **Owner set non-empty, class `identical`:** stop. Remaining subjects still unwrap `k`.
6. **Owner set non-empty, class `mixed`:** this is a spec violation if we never shared mixed payloads. If a future mode did share them, **copy-out**: write a new payload for remaining subjects that does not contain `S` (caller-supplied redaction, or fail). Old snapshots that pointed at the mixed payload cannot be “fixed” without rewrite; they fail restore for that file.

## Baselines (same API)

| Mode | Share across users? | `erase(Alice)` on identical | `erase(Alice)` on mixed |
|---|---|---|---|
| `or-wrap` | yes | Alice fails, Bob ok, one copy | **leak** if shared: Bob’s `k` still yields Alice |
| `and-wrap` | yes (nested wraps) | Bob may fail | Bob fails |
| `no-cross-user` | no | Alice fails, Bob ok, **two** copies | Alice fails, Bob ok, two copies |
| `copy-out-mixed` | identical yes; mixed no or split on erase | as `or-wrap` | Bob gets new object; old mixed snapshot fails or is replaced only if rewrite is allowed |

`no-cross-user` is the space upper bound (“correct, expensive”). `or-wrap` on mixed is the security lower bound (“cheap, wrong”). The design we claim is `or-wrap` for identical + never-share or copy-out for mixed + shred `s_S` + immutable recipes.

## Multi-tenant trace (PhD)

Replay an ingest log: `(time, tenant, subject, path, bytes or fingerprint)`. Public substitutes if a private trace cannot be published: FSL homes traces, or a generated tenant mix on top of a public file corpus. The point is **workload shape** (how much unique / identical / container-mixed, how often holds would fire), not a new CDC number.

## Limits (by design)

- Core labels are trusted. Container parsers use header/path heuristics; they are not a legal PII product.
- Unrecoverability is computational (AES). It is not “the disk was overwritten.”
- If the key store is backed up inside the same WORM vault as the chunks, shredding `s_S` does not erase old key-store snapshots. Key-store retention must be shorter than, or independently shreddable from, data retention.
- Legal holds **block** shred of the keys they still need; that is required behavior, and it delays unrecoverability.
- Group photos: “forget Alice’s likeness in Bob’s copy” is a policy choice (`keep-for-Bob` vs `drop-for-both`), not something chunk hashing can decide.
