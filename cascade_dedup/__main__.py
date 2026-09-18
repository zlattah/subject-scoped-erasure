"""CLI: python -m cascade_dedup bench"""

from __future__ import annotations

import argparse
import json
import sys

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
    corpus = build_remux_corpus(
        duration=args.duration,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    blobs = remux_blobs(corpus, include_transcode=args.include_transcode)
    logical = sum(len(b) for b in blobs)
    print(
        f"video corpus: {len(blobs)} files, {logical / 1024:.1f} KiB logical, "
        f"duration={args.duration}s {args.width}x{args.height}@{args.fps}",
        file=sys.stderr,
    )
    for clip, files in corpus.items():
        kinds = ", ".join(
            f"{k}={len(v)}" for k, v in files.items() if k != "transcode" or args.include_transcode
        )
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
    parser = argparse.ArgumentParser(
        prog="cascade-dedup",
        description="Canonical access-unit dedup for lossless H.264/AAC remuxes",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    bench = sub.add_parser(
        "bench",
        help="FastCDC vs container samples vs canonical AUs on remux clones",
    )
    bench.add_argument("--duration", type=float, default=4.0)
    bench.add_argument("--width", type=int, default=320)
    bench.add_argument("--height", type=int, default=240)
    bench.add_argument("--fps", type=int, default=12)
    bench.add_argument("--modes", default="all", help="fastcdc,container-sample,canonical-au")
    bench.add_argument("--include-transcode", action="store_true")
    bench.add_argument("--json", action="store_true")
    bench.set_defaults(func=cmd_bench)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
