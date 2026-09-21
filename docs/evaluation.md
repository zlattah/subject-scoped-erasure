# Evaluation

The experiment is a **policy test**, not a CDC-ratio contest. Reproduce:

```bash
python -m cascade_dedup eval --seed 0
```

Full JSON from seed 0: [erase-eval.json](erase-eval.json). Laptop-scale **synthetic** data. Do not claim enterprise generality. `physical_bytes` stay high because the chunk log is WORM; **`live_bytes`** is the decryptable set (leftover keys + remaining wraps).

## Corpus

Seeded two-subject ingest (`alice`, `bob`), snapshot `tuesday`:

| Class | What | Logical shape |
|---|---|---|
| `unique` | 24 files each | 4 KiB, Alice files marked `ALICE-SECRET` |
| `identical` | 8 shared installers | 16 KiB each, both subjects |
| `mixed` | 8 labeled blobs | contains `ALICE-LINE` and `BOB-LINE` |

## Mode table (seed 0)

After `erase(alice)`. `vs_ns_*` is live bytes / never-share live bytes.

| Mode | Alice unique gone | Bob installer exact | Bob mixed still has Alice | live after | vs never-share before | vs never-share after |
|---|---|---|---|---|---|---|
| `or-wrap` | yes | yes | **yes (leak)** | 263 488 | **0.69** | 1.00 |
| `and-wrap` | yes | **no** | no (Bob blinded) | 98 688 | 0.69 | 0.37 |
| `no-cross-user` | yes | yes | **yes** (Bob’s private copy) | 263 488 | 1.00 | 1.00 |
| `copy-out-mixed` | yes | yes | **no** | 263 384 | 0.75 | 1.00 |

Read of the numbers:

- Sharing pays **before** erase: OR-wrap holds 69% of never-share live bytes (362 176 / 526 976).
- After Alice is gone, OR-wrap and never-share land on the **same** live set (Bob’s unique + one installer + mixed). The duplicate installer copies were only wasted while Alice still existed.
- AND-wrap looks cheapest after erase because it also destroys Bob’s shared objects. That is the wrong baseline.
- Copy-out keeps the share saving on identical files, redacts mixed (`unrestorable_mixed = 8`), leftover keys have no `ALICE-SECRET` / `ALICE-LINE`. After erase its live bytes match never-share within 0.04% (redaction drops a few lines). The win is **correctness**, not a smaller Bob.

Erase on this corpus is < 1 ms in-process. That is not a system latency result.

## Holds

| Metric | Value |
|---|---|
| Snapshots Alice stayed decryptable after `erase` while held | 3 / 3 |
| Restore flagged `contains_erased_subject` | yes |
| Gone after `release` | yes |
| Leftover has Alice after release | no |
| Erases blocked by hold | 1 |

The recoverability window is **measured in snapshots the hold covered**, not hidden.

## Synthetic multi-tenant trace

180 events, three named tenants (`acme`, `globex`, `contoso`). **Proxy workload**, not a production backup log.

| | unique | identical | mixed |
|---|---|---|---|
| Byte fraction | 0.385 | 0.591 | 0.024 |

After `erase(alice)`: copy-out live **798 067** vs never-share **995 564** (ratio **0.80**). The identical-heavy mix is where sharing still pays after one subject is shredded. Leftover has no `ALICE-SECRET`.

## Containers

| Check | Result |
|---|---|
| mbox parsed; Bob restore after erase has no `Alice Lane` | pass |
| whole-file OR-wrap of the same mbox still leaks `Alice Lane` | pass (negative) |
| photo library: Bob keeps solo; group dropped (`drop-for-both`) | pass |

Outlook PST is still **mbox-shaped**.

## What would count as a failed experiment

- `or-wrap` on mixed with no leak (the leak is the point of the negative test).
- Claiming FadeVersion already did subject erase.
- Measuring only dedup ratio and ignoring restore/unrecoverability.
- Stopping at whole-file mixed labels and never parsing a mailbox/library.
- Shredding keys a live hold still needs, or hiding the recoverability window.

This run does not fail those checks. It also does not replace a real tenant trace or a native PST.
