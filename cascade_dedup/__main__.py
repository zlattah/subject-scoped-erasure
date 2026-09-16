"""CLI: python -m cascade_dedup bench"""

from __future__ import annotations

import argparse
import json
import sys

from cascade_dedup.corpus import versioned_blobs
from cascade_dedup.pipeline import ingest_versions


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    keys = [k for k in rows[0] if k != "name"]
    name_w = max(len(str(r["name"])) for r in rows)
    name_w = max(name_w, 4)
    print(f"{'mode':<{name_w}}  " + "  ".join(f"{k:>16}" for k in keys))
    for row in rows:
        print(f"{row['name']:<{name_w}}  " + "  ".join(f"{row[k]:>16}" for k in keys))


def cmd_bench(args: argparse.Namespace) -> int:
    versions = versioned_blobs(
        n_versions=args.versions,
        base_size=args.base_size,
        seed=args.seed,
    )
    logical = sum(len(v) for v in versions)
    print(
        f"corpus: {args.versions} versions, {logical / (1024 * 1024):.2f} MiB logical, seed={args.seed}",
        file=sys.stderr,
    )
    rows = []
    for mode in ("fastcdc", "radcdc-exact", "radcdc"):
        _, stats = ingest_versions(versions, mode=mode, do_delta=True)
        rows.append(stats.as_row())
    _print_table(rows)
    if args.json:
        print(json.dumps(rows, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cascade-dedup")
    sub = parser.add_subparsers(dest="cmd", required=True)
    bench = sub.add_parser("bench", help="compare FastCDC vs RAD-CDC on a synthetic timeline")
    bench.add_argument("--versions", type=int, default=6)
    bench.add_argument("--base-size", type=int, default=512 * 1024)
    bench.add_argument("--seed", type=int, default=0)
    bench.add_argument("--json", action="store_true")
    bench.set_defaults(func=cmd_bench)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
