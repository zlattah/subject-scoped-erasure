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

## Limits (by design)

- Labels are trusted. A real deployment needs a PII/policy layer; that is out of scope.
- Unrecoverability is computational (AES). It is not “the disk was overwritten.”
- If the key store is backed up inside the same WORM vault as the chunks, shredding `s_S` does not erase old key-store snapshots. Key-store retention must be shorter than, or independently shreddable from, data retention.
- Legal holds block shred of the keys they still need.
