# Evaluation (planned)

No implementation results yet. The experiment is a **policy test**, not a CDC-ratio contest.

## Corpus

Synthetic, two subjects (`alice`, `bob`), three classes, several snapshots:

| Class | What is ingested | Expected share before erase |
|---|---|---|
| `unique` | Different files per subject | None across users |
| `identical` | Same bytes, both subjects | One physical copy (OR-wrap) |
| `mixed` | One blob labeled as containing both subjects | No payload share (or share-and-leak in the negative baseline) |

Sizes stay laptop-scale. Labels are part of the input.

## Checks after `erase(alice)`

| Mode | unique | identical | mixed |
|---|---|---|---|
| `or-wrap` | Alice fail, Bob ok, chunk gone or shredded | Alice fail, Bob **byte-identical** restore, one copy remains | If shared: **Bob’s restore still contains Alice** (documented leak) |
| `and-wrap` | Alice fail | Bob may fail (wrong) | Bob fails |
| `no-cross-user` | Alice fail, Bob ok | Alice fail, Bob ok, **two** copies | Alice fail, Bob ok, two copies |
| `copy-out-mixed` | as `or-wrap` | as `or-wrap` | Bob restores a redacted/new object; Alice bytes not in store+Bob keys; old mixed snapshot fails unless rewrite is allowed |

Also: leftover-store attacker (all remaining keys + chunk log + recipes) must not decrypt Alice’s unique or mixed personal bytes.

## Metrics

- Unique physical bytes before/after erase (space cost of each mode).
- Restore success/failure and byte equality for Bob.
- Erase latency (key shred + owner-set updates; GC optional).
- Number of mixed snapshots that become unrestorable (immutability cost).

## PhD layer

### Mixed containers

Two fixtures, two subjects:

1. **One PST or mbox** — Alice-only messages, Bob-only messages, a shared thread, a shared attachment.
2. **One photo library** — Alice solos, Bob solos, at least one group shot, optional identical original ingested twice.

Checks after `erase(alice)`:

- Alice-only inner objects unrestorable; their DEKs shredded if unpinned.
- Bob-only inner objects byte-identical.
- Shared attachment behaves as `identical`.
- Group shot follows the declared policy (`keep-for-Bob` leak vs `drop-for-both`).
- Whole-file OR-wrap of the PST/library is the **negative** baseline (Bob’s restore still contains Alice’s mail/photos).

### Holds vs erase

Run the four README cases on the same fixtures:

| Case | Expect |
|---|---|
| Hold Alice snapshot, then `erase(alice)` | No shred of Alice keys until `release`; then deferred erase completes |
| Hold Bob snapshot that shares an identical chunk, then `erase(alice)` | Alice wrap gone; `k` stays while hold (or Bob) lives |
| Hold mixed PST/library, then `erase(alice)` | Restore of held object may still contain Alice and is flagged; after release, copy-out/drop then shred |
| `erase(alice)` then hold Alice | Hold cannot revive shredded keys |

Metric: **recoverability window** — time (or snapshot count) Alice remains decryptable after `erase` was requested but a hold was live.

### Multi-tenant trace

Replay the trace into the store. Report:

- Fraction of bytes unique / identical / container-mixed, per tenant and global.
- Unique bytes after a sample of `erase(subject)` calls vs `no-cross-user`.
- How many erases hit a hold (if the trace or a synthetic hold schedule includes them).

If only a public proxy trace is available, say so and do not claim enterprise generality.

## What would count as a failed experiment

- `or-wrap` on mixed with no leak warning (the leak is the point of the negative test).
- Claiming FadeVersion already did subject erase.
- Measuring only dedup ratio and ignoring restore/unrecoverability.
- PhD write-up that never parses a PST/library and only uses whole-file mixed labels.
- Shredding keys that a live hold still needs, or hiding the recoverability window.
