"""CLI: python -m cascade_dedup demo | ingest | restore | erase | hold | release | bench"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

from cascade_dedup.containers import ingest_mbox, ingest_photo_library, sample_mbox
from cascade_dedup.erase import (
    EraseStore,
    FileClass,
    MixedPolicy,
    WrapMode,
    strip_marker,
)
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


def _load(path: str) -> EraseStore:
    p = Path(path)
    if p.exists():
        return pickle.loads(p.read_bytes())
    return EraseStore()


def _save(path: str, store: EraseStore) -> None:
    Path(path).write_bytes(pickle.dumps(store))


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


def _print_restore(who: str, snap: str, result) -> None:
    print(f"restore {who!r} {snap!r} contains_erased_subject={result.contains_erased_subject}")
    for path, rec in sorted(result.files.items()):
        preview = rec.data[:60] if rec.data else b""
        print(f"  {path}: ok={rec.ok} unrestorable={rec.unrestorable} data={preview!r}")


def cmd_demo(_args: argparse.Namespace) -> int:
    print("== unique + identical OR-wrap + copy-out mixed ==")
    store = EraseStore(mixed_policy=MixedPolicy.COPY_OUT, redactor=strip_marker)
    store.ingest("alice", "tuesday", "diary.txt", b"Alice diary: secret", FileClass.UNIQUE)
    store.ingest("bob", "tuesday", "notes.txt", b"Bob only notes", FileClass.UNIQUE)
    inst = b"OfficeSetup.exe" + b"X" * 40
    store.ingest("alice", "tuesday", "setup.exe", inst, FileClass.IDENTICAL)
    store.ingest("bob", "tuesday", "setup.exe", inst, FileClass.IDENTICAL)
    mixed = b"line ALICE home\nline BOB contract\n"
    store.ingest("alice", "tuesday", "legal.pst", mixed, FileClass.MIXED)
    store.ingest("bob", "tuesday", "legal.pst", mixed, FileClass.MIXED)
    print("before erase", store.stats())
    store.erase("alice")
    print("after erase(alice)", store.stats())
    _print_restore("alice", "tuesday", store.restore("alice", "tuesday"))
    _print_restore("bob", "tuesday", store.restore("bob", "tuesday"))
    leftover = store.leftover_plaintexts(exclude_subject="alice")
    print("leftover has ALICE:", any(b"ALICE" in p or b"secret" in p for p in leftover))

    print("\n== hold defers shred ==")
    held = EraseStore()
    held.ingest("alice", "tuesday", "diary.txt", b"Alice diary: secret", FileClass.UNIQUE)
    held.hold("lawsuit", subject="alice", snapshot_id="tuesday")
    held.erase("alice")
    _print_restore("alice", "tuesday", held.restore("alice", "tuesday"))
    held.release("lawsuit")
    _print_restore("alice", "tuesday", held.restore("alice", "tuesday"))

    print("\n== mbox inner objects ==")
    mail = EraseStore(mixed_policy=MixedPolicy.COPY_OUT, redactor=strip_marker)
    ingest_mbox(mail, sample_mbox(), "tuesday")
    mail.erase("alice")
    _print_restore("bob", "tuesday", mail.restore("bob", "tuesday"))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    store = _load(args.db)
    data = Path(args.file).read_bytes()
    store.ingest(args.subject, args.snapshot, args.path or args.file, data, args.cls)
    _save(args.db, store)
    print(store.stats())
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    store = _load(args.db)
    _print_restore(args.subject, args.snapshot, store.restore(args.subject, args.snapshot))
    return 0


def cmd_erase(args: argparse.Namespace) -> int:
    store = _load(args.db)
    store.erase(args.subject)
    _save(args.db, store)
    print("erased", args.subject, store.stats())
    return 0


def cmd_hold(args: argparse.Namespace) -> int:
    store = _load(args.db)
    store.hold(args.id, subject=args.subject, snapshot_id=args.snapshot, path=args.path)
    _save(args.db, store)
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    store = _load(args.db)
    store.release(args.id)
    _save(args.db, store)
    return 0


def cmd_photos(args: argparse.Namespace) -> int:
    store = _load(args.db)
    ingest_photo_library(store, args.dir, args.snapshot)
    _save(args.db, store)
    print(store.stats())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cascade-dedup",
        description="Subject-scoped erase in a deduplicated immutable backup",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    demo = sub.add_parser("demo", help="Run the Alice/Bob scenarios against an in-memory store")
    demo.set_defaults(func=cmd_demo)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--db", default="erase-store.pkl")
    ingest.add_argument("--subject", required=True)
    ingest.add_argument("--snapshot", required=True)
    ingest.add_argument("--file", required=True)
    ingest.add_argument("--path")
    ingest.add_argument("--cls", default="unique", choices=[c.value for c in FileClass])
    ingest.add_argument("--wrap", default="or-wrap", choices=[m.value for m in WrapMode])
    ingest.set_defaults(func=cmd_ingest)

    restore = sub.add_parser("restore")
    restore.add_argument("--db", default="erase-store.pkl")
    restore.add_argument("--subject", required=True)
    restore.add_argument("--snapshot", required=True)
    restore.set_defaults(func=cmd_restore)

    erase = sub.add_parser("erase")
    erase.add_argument("--db", default="erase-store.pkl")
    erase.add_argument("subject")
    erase.set_defaults(func=cmd_erase)

    hold = sub.add_parser("hold")
    hold.add_argument("--db", default="erase-store.pkl")
    hold.add_argument("--id", required=True)
    hold.add_argument("--subject")
    hold.add_argument("--snapshot")
    hold.add_argument("--path")
    hold.set_defaults(func=cmd_hold)

    rel = sub.add_parser("release")
    rel.add_argument("--db", default="erase-store.pkl")
    rel.add_argument("id")
    rel.set_defaults(func=cmd_release)

    photos = sub.add_parser("photos", help="Ingest a two-subject photo folder")
    photos.add_argument("--db", default="erase-store.pkl")
    photos.add_argument("--dir", required=True)
    photos.add_argument("--snapshot", required=True)
    photos.set_defaults(func=cmd_photos)

    bench = sub.add_parser("bench", help="Legacy remux AU bench (not the erasure claim)")
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
