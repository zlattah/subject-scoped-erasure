# Project plan

Working plan for the backup-erase store. Not the English-class report — that is [english-class-interim-report.md](english-class-interim-report.md). Claim and glossary live in the [README](README.md).

---

## Goal

Build one store where `erase(alice)` can succeed without rewriting a retained snapshot and without breaking Bob when they share bytes. Prove it with tests and measurements, including mixed mail/photos, holds, and a tenant-labelled ingest mix.

## Outcome

A Python prototype (`ingest` / `restore` / `erase` / `hold` / `release`) plus a short technical write-up of what held, what leaked, and what it cost in unique bytes.

---

## Work packages

Do these in order. Each package ends with tests, not a slide.

| ID | Package | Done when |
|---|---|---|
| WP0 | Claim freeze | README glossary matches the code names (`subject`, `chunk`, `recipe`, `owner set`, unique / identical / mixed). |
| WP1 | Store skeleton | Append-only chunk log, recipes, mutable key store. Ingest and restore one unique file. |
| WP2 | Identical share | Two subjects, one payload, OR-wrap. `erase(alice)`: Alice cannot restore; Bob’s bytes match; one physical copy remains. |
| WP3 | Labeled mixed | Mixed blob is not silently OR-wrapped. Copy-out or explicit unrestorable old snapshot. Leftover store + Bob’s keys must not yield Alice. |
| WP4 | Baselines | Same API: `and-wrap`, `no-cross-user`, `or-wrap` without copy-out (documented leak). |
| WP5 | Containers | One mbox or PST and one two-subject photo folder. Erase inner objects. Whole-file wrap is the leak baseline. |
| WP6 | Holds | `hold` / `release` / deferred erase. Live hold blocks shred. After release, same checks as WP2–WP5. Record recoverability window. |
| WP7 | Trace | Replay a tenant-labelled ingest log (public proxy if needed). Report unique / identical / mixed mix and erase/hold cost. |
| WP8 | Write-up | Technical note: invariant, costs, limits. Point at FadeVersion; do not claim Boneh shredding is new. |

## Dependencies

```
WP0 → WP1 → WP2 → WP3 → WP4
                    └→ WP5 → WP6 → WP7 → WP8
```

WP6 can start as soon as WP2 exists (holds on unique/identical). WP5 can use mbox first; full Outlook PST is optional hardening of the same package.

## Deliverables

| Artefact | Path / form |
|---|---|
| Store + CLI | `cascade_dedup` (or a dedicated package if the old tree is retired) |
| Tests | unique / identical / mixed / hold / leftover-store attacker |
| Fixtures | two-subject files; mbox; photo folder; optional PST |
| Trace replay | script + table of mix and costs |
| Academic report | `english-class-interim-report.md` (sections 3–5 still empty) |
| CS course plan | `cs-project-plan.md` |
| Design notes | `docs/method.md`, `docs/evaluation.md` |

## Stack

- Python 3.11+
- AES-GCM for `{chunk}_k`; control keys in a local escrow
- Content-defined or fixed-size chunks (pick one in WP1 and keep it)
- pytest

## Risks

| Risk | If it happens | What we do |
|---|---|---|
| PST parsing eats the project | Outlook format is hostile | Ship mbox + say PST is the same rule on a harder parser |
| No real multi-tenant trace | Access / ethics | Named public substitute; do not claim enterprise generality |
| Mixed + hold bugs | Alice leaks or Bob goes blind | Leftover-store attacker tests before any “success” claim |
| Key store backed up with chunks | Shred is a lie | Key-store retention shorter / independently shreddable; document it |

## Checks (the bar)

- Unique: Alice gone; Bob unaffected.
- Identical: Alice gone; Bob byte-identical; still ~one copy.
- Mixed: no silent leak; Bob gets copy-out, drop, or a failed old snapshot.
- Container: Alice’s messages/photos gone from her restore; Bob’s remain.
- Hold: no shred while pinned; after `release`, same bar as above.
- Trace: numbers match the log we actually ran.

## Status

Implementation starts at WP1 (store skeleton) and proceeds through WP8 (write-up).
