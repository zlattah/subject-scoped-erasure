"""CLI: python -m cascade_dedup bench"""

from __future__ import annotations

import argparse
import json
import sys

from cascade_dedup.corpus import versioned_blobs
from cascade_dedup.gain import train_gain_predictor
from cascade_dedup.learn import train_seq_policy
from cascade_dedup.pipeline import ALL_MODES, ingest_versions
from cascade_dedup.video import VIDEO_MODES, ingest_video_files
from cascade_dedup.video_corpus import build_remux_corpus, remux_blobs


def _print_table(rows: list[dict], *, file=None) -> None:
    if not rows:
        return
    out = file or sys.stdout
    keys = [k for k in rows[0] if k != "name"]
    name_w = max(len(str(r["name"])) for r in rows)
    name_w = max(name_w, 4)
    print(f"{'mode':<{name_w}}  " + "  ".join(f"{k:>16}" for k in keys), file=out)
    for row in rows:
        print(f"{row['name']:<{name_w}}  " + "  ".join(f"{row[k]:>16}" for k in keys), file=out)


def _parse_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def cmd_bench(args: argparse.Namespace) -> int:
    versions = versioned_blobs(
        n_versions=args.versions,
        base_size=args.base_size,
        seed=args.seed,
        profile=args.profile,
    )
    logical = sum(len(v) for v in versions)
    print(
        f"corpus: {args.versions} versions, {logical / (1024 * 1024):.2f} MiB logical, "
        f"seed={args.seed} profile={args.profile}",
        file=sys.stderr,
    )
    modes = list(ALL_MODES) if args.modes == "all" else _parse_csv(args.modes)
    policies = _parse_csv(args.delta_policy)
    predictor = None
    seq_policy = None
    if "predict" in policies:
        train = versioned_blobs(
            n_versions=args.versions,
            base_size=args.base_size,
            seed=args.train_seed,
            profile=args.profile,
        )
        predictor = train_gain_predictor(train, threshold=args.gain_threshold)
        print(
            f"predictor: source={predictor.source} n_train={predictor.n_train} n_neg={predictor.n_neg} "
            f"weights={tuple(round(w, 3) for w in predictor.weights)} "
            f"intercept={predictor.intercept:.3f} threshold={predictor.threshold:.3f}",
            file=sys.stderr,
        )
    if "seqcdc-learn" in modes:
        train = versioned_blobs(
            n_versions=args.versions,
            base_size=args.base_size,
            seed=args.train_seed,
            profile=args.profile,
        )
        seq_policy = train_seq_policy(train)
        print(
            f"seq-learn: skip={seq_policy.skip_head.source} n={seq_policy.skip_head.n_train} "
            f"pos={seq_policy.skip_head.n_pos} t={seq_policy.skip_head.threshold:.2f} "
            f"tmax={seq_policy.tmax_head.source} n={seq_policy.tmax_head.n_train} "
            f"pos={seq_policy.tmax_head.n_pos} t={seq_policy.tmax_head.threshold:.2f}",
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
                seq_policy=seq_policy,
            )
            rows.append(stats.as_row())
    if args.json:
        _print_table(rows, file=sys.stderr)
        print(json.dumps(rows, indent=2))
    else:
        _print_table(rows)
    return 0


def cmd_video_bench(args: argparse.Namespace) -> int:
    corpus = build_remux_corpus(
        duration=args.duration,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    blobs = remux_blobs(corpus, include_transcode=args.include_transcode)
    logical = sum(len(b) for b in blobs)
    n_files = len(blobs)
    print(
        f"video corpus: {n_files} files, {logical / 1024:.1f} KiB logical, "
        f"duration={args.duration}s {args.width}x{args.height}@{args.fps}",
        file=sys.stderr,
    )
    for clip, files in corpus.items():
        kinds = ", ".join(f"{k}={len(v)}" for k, v in files.items() if k != "transcode" or args.include_transcode)
        print(f"  {clip}: {kinds}", file=sys.stderr)
    modes = list(VIDEO_MODES) if args.modes == "all" else _parse_csv(args.modes)
    rows = []
    for mode in modes:
        _, stats = ingest_video_files(blobs, mode=mode)
        rows.append(stats.as_row())
    if args.json:
        _print_table(rows, file=sys.stderr)
        print(json.dumps(rows, indent=2))
    else:
        _print_table(rows)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cascade-dedup")
    sub = parser.add_subparsers(dest="cmd", required=True)
    bench = sub.add_parser("bench", help="compare CDC and delta-policy variants on a synthetic timeline")
    bench.add_argument("--versions", type=int, default=6)
    bench.add_argument("--base-size", type=int, default=512 * 1024)
    bench.add_argument("--seed", type=int, default=0)
    bench.add_argument("--profile", choices=("random", "mixed"), default="mixed")
    bench.add_argument(
        "--train-seed",
        type=int,
        default=101,
        help="frozen corpus seed for the gain predictor and the SeqCDC skip/Tmax scorer",
    )
    bench.add_argument("--modes", default="all", help="comma-separated modes, or 'all'")
    bench.add_argument(
        "--delta-policy",
        default="encode,predict",
        help="comma-separated: encode, predict, none",
    )
    bench.add_argument("--gain-threshold", type=float, default=0.10)
    bench.add_argument("--json", action="store_true")
    bench.set_defaults(func=cmd_bench)

    video = sub.add_parser(
        "video-bench",
        help="compare FastCDC, container samples, and canonical access-units on remux clones",
    )
    video.add_argument("--duration", type=float, default=4.0)
    video.add_argument("--width", type=int, default=320)
    video.add_argument("--height", type=int, default=240)
    video.add_argument("--fps", type=int, default=12)
    video.add_argument("--modes", default="all", help="fastcdc,container-sample,canonical-au")
    video.add_argument("--include-transcode", action="store_true")
    video.add_argument("--json", action="store_true")
    video.set_defaults(func=cmd_video_bench)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
