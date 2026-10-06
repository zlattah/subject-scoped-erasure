"""CLI: python -m cascade_dedup demo | ingest | restore | erase | hold | release | eval"""

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


def _load(path: str) -> EraseStore:
    p = Path(path)
    if p.exists():
        return pickle.loads(p.read_bytes())
    return EraseStore()


def _save(path: str, store: EraseStore) -> None:
    Path(path).write_bytes(pickle.dumps(store))


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


def cmd_eval(args: argparse.Namespace) -> int:
    from cascade_dedup.measure import dumps_eval, format_mode_table, run_eval

    result = run_eval(seed=args.seed)
    print(format_mode_table(result["modes"]))
    print()
    print("hold:", json.dumps(result["hold"]))
    print("trace mix:", json.dumps(result["trace"]["byte_mix_frac"]))
    print(
        "trace live after erase(alice): copy-out",
        result["trace"]["copy_out_mixed"]["live_after_erase_alice"],
        "never-share",
        result["trace"]["no_cross_user"]["live_after_erase_alice"],
        "ratio",
        result["trace"]["space_vs_never_share"],
    )
    print("containers:", json.dumps(result["containers"]))
    print(result["note"])
    if args.json:
        print(dumps_eval(result))
    if args.out:
        Path(args.out).write_text(dumps_eval(result) + "\n")
        print("wrote", args.out, file=sys.stderr)
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

    ev = sub.add_parser("eval", help="Policy measurements vs never-share (synthetic corpus)")
    ev.add_argument("--seed", type=int, default=0)
    ev.add_argument("--json", action="store_true")
    ev.add_argument("--out", help="Write full JSON results to this path")
    ev.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
