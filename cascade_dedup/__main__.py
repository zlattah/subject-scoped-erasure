"""CLI: python -m cascade_dedup bench"""

from __future__ import annotations

import argparse
import json
import sys

from cascade_dedup.corpus import versioned_blobs
from cascade_dedup.gain import train_gain_predictor
from cascade_dedup.pipeline import ALL_MODES, ingest_versions


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    keys = [k for k in rows[0] if k != "name"]
    name_w = max(len(str(r["name"])) for r in rows)
    name_w = max(name_w, 4)
    print(f"{'mode':<{name_w}}  " + "  ".join(f"{k:>16}" for k in keys))
    for row in rows:
        print(f"{row['name']:<{name_w}}  " + "  ".join(f"{row[k]:>16}" for k in keys))


def _parse_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


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
    modes = list(ALL_MODES) if args.modes == "all" else _parse_csv(args.modes)
    policies = _parse_csv(args.delta_policy)
    predictor = None
    if "predict" in policies:
        train = versioned_blobs(
            n_versions=args.versions,
            base_size=args.base_size,
            seed=args.train_seed,
        )
        predictor = train_gain_predictor(train, threshold=args.gain_threshold)
        print(
            f"predictor: source={predictor.source} n_train={predictor.n_train} "
            f"weights={tuple(round(w, 3) for w in predictor.weights)} "
            f"intercept={predictor.intercept:.3f} threshold={predictor.threshold}",
            file=sys.stderr,
        )
    rows = []
    for mode in modes:
        for policy in policies:
            _, stats = ingest_versions(
                versions,
                mode=mode,
                do_delta=policy != "none",
                delta_policy=policy,
                predictor=predictor,
            )
            rows.append(stats.as_row())
    _print_table(rows)
    if args.json:
        print(json.dumps(rows, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cascade-dedup")
    sub = parser.add_subparsers(dest="cmd", required=True)
    bench = sub.add_parser("bench", help="compare CDC and delta-policy variants on a synthetic timeline")
    bench.add_argument("--versions", type=int, default=6)
    bench.add_argument("--base-size", type=int, default=512 * 1024)
    bench.add_argument("--seed", type=int, default=0)
    bench.add_argument("--train-seed", type=int, default=101, help="frozen corpus seed for the gain predictor")
    bench.add_argument("--modes", default="all", help="comma-separated modes, or 'all'")
    bench.add_argument(
        "--delta-policy",
        default="encode,predict",
        help="comma-separated: encode, predict, none",
    )
    bench.add_argument("--gain-threshold", type=float, default=0.10)
    bench.add_argument("--json", action="store_true")
    bench.set_defaults(func=cmd_bench)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
