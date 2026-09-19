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

## What would count as a failed experiment

- `or-wrap` on mixed with no leak warning (the leak is the point of the negative test).
- Claiming FadeVersion already did subject erase.
- Measuring only dedup ratio and ignoring restore/unrecoverability.
