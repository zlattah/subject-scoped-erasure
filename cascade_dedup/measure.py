"""Policy measurements: same corpus, four wrap modes, hold window, synthetic trace.

This is not a CDC-ratio contest. The score is unrecoverability + Bob's restore
+ live bytes versus never sharing across subjects.
"""

from __future__ import annotations

import json
import random
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from cascade_dedup.containers import ingest_mbox, ingest_photo_library, sample_mbox
from cascade_dedup.erase import (
    EraseStore,
    FileClass,
    MixedPolicy,
    WrapMode,
    class_mix,
    strip_marker,
)

ALICE_UNIQUE = b"ALICE-SECRET"
ALICE_MIXED = b"ALICE-LINE"
BOB_MIXED = b"BOB-LINE"
INSTALLER_PREFIX = b"OfficeSetup.exe"


@dataclass
class ModeRow:
    name: str
    live_bytes_before: int
    live_bytes_after: int
    physical_bytes_after: int
    n_live_chunks_after: int
    n_chunks: int
    alice_unique_gone: bool
    bob_identical_ok: bool
    bob_mixed_has_alice: bool
    leftover_has_alice_unique: bool
    leftover_has_alice_mixed: bool
    unrestorable_mixed: int
    erase_ms: float
    space_vs_never_share_before: float | None
    space_vs_never_share_after: float | None


def _blob(rng: random.Random, n: int, prefix: bytes) -> bytes:
    pad = bytes(rng.getrandbits(8) for _ in range(max(0, n - len(prefix))))
    return prefix + pad


def labeled_corpus(seed: int = 0) -> list[tuple[str, str, str, bytes, str]]:
    """Deterministic two-subject corpus: unique, identical, mixed."""
    rng = random.Random(seed)
    snap = "tuesday"
    events: list[tuple[str, str, str, bytes, str]] = []
    for i in range(24):
        events.append(
            (
                "alice",
                snap,
                f"alice/unique/{i}.bin",
                _blob(rng, 4096, ALICE_UNIQUE + f"-{i}\n".encode()),
                "unique",
            )
        )
        events.append(
            (
                "bob",
                snap,
                f"bob/unique/{i}.bin",
                _blob(rng, 4096, b"BOB-ONLY-" + f"{i}\n".encode()),
                "unique",
            )
        )
    for i in range(8):
        shared = _blob(rng, 16384, INSTALLER_PREFIX + f"-{i}\n".encode())
        events.append(("alice", snap, f"shared/setup-{i}.exe", shared, "identical"))
        events.append(("bob", snap, f"shared/setup-{i}.exe", shared, "identical"))
    for i in range(8):
        mixed = ALICE_MIXED + f"-{i}\n".encode() + _blob(rng, 4096, b"") + BOB_MIXED + f"-{i}\n".encode()
        events.append(("alice", snap, f"mixed/legal-{i}.pst", mixed, "mixed"))
        events.append(("bob", snap, f"mixed/legal-{i}.pst", mixed, "mixed"))
    return events


def _ingest_all(store: EraseStore, events: list[tuple[str, str, str, bytes, str]]) -> None:
    for subject, snap, path, data, cls in events:
        store.ingest(subject, snap, path, data, cls)


def _leftover_join(store: EraseStore) -> bytes:
    return b"".join(store.leftover_plaintexts(exclude_subject="alice"))


def evaluate_mode(
    name: str,
    events: list[tuple[str, str, str, bytes, str]],
    *,
    wrap_mode: WrapMode,
    mixed_policy: MixedPolicy,
    redactor=None,
) -> ModeRow:
    store = EraseStore(wrap_mode=wrap_mode, mixed_policy=mixed_policy, redactor=redactor)
    _ingest_all(store, events)
    before = store.stats()
    t0 = time.perf_counter()
    store.erase("alice")
    erase_ms = (time.perf_counter() - t0) * 1000
    after = store.stats()
    alice = store.restore("alice", "tuesday")
    bob = store.restore("bob", "tuesday")
    leftover = _leftover_join(store)
    alice_unique_ok = any(
        (f.data or b"").startswith(ALICE_UNIQUE) for f in alice.files.values() if f.ok
    )
    by_path = {p: d for s, _, p, d, c in events if s == "bob" and c == "identical"}
    bob_identical_ok = all(bob.bytes_for(path) == data for path, data in by_path.items())
    bob_mixed_has_alice = any(
        ALICE_MIXED in (f.data or b"") for path, f in bob.files.items() if path.startswith("mixed/")
    )
    unrestorable = sum(1 for r in store.recipes if r.unrestorable)
    return ModeRow(
        name=name,
        live_bytes_before=before.live_bytes,
        live_bytes_after=after.live_bytes,
        physical_bytes_after=after.physical_bytes,
        n_live_chunks_after=after.n_live_chunks,
        n_chunks=after.n_chunks,
        alice_unique_gone=not alice_unique_ok,
        bob_identical_ok=bob_identical_ok,
        bob_mixed_has_alice=bob_mixed_has_alice,
        leftover_has_alice_unique=ALICE_UNIQUE in leftover,
        leftover_has_alice_mixed=ALICE_MIXED in leftover,
        unrestorable_mixed=unrestorable,
        erase_ms=round(erase_ms, 3),
        space_vs_never_share_before=None,
        space_vs_never_share_after=None,
    )


MODES: list[tuple[str, WrapMode, MixedPolicy]] = [
    ("or-wrap", WrapMode.OR_WRAP, MixedPolicy.OR_WRAP),
    ("and-wrap", WrapMode.AND_WRAP, MixedPolicy.OR_WRAP),
    ("no-cross-user", WrapMode.NO_CROSS_USER, MixedPolicy.NEVER_SHARE),
    ("copy-out-mixed", WrapMode.OR_WRAP, MixedPolicy.COPY_OUT),
]


def evaluate_modes(seed: int = 0) -> list[ModeRow]:
    events = labeled_corpus(seed)
    rows: list[ModeRow] = []
    for name, wrap, mixed in MODES:
        redactor = strip_marker if mixed is MixedPolicy.COPY_OUT else None
        rows.append(
            evaluate_mode(name, events, wrap_mode=wrap, mixed_policy=mixed, redactor=redactor)
        )
    never_before = next(r.live_bytes_before for r in rows if r.name == "no-cross-user")
    never_after = next(r.live_bytes_after for r in rows if r.name == "no-cross-user")
    for row in rows:
        row.space_vs_never_share_before = (
            round(row.live_bytes_before / never_before, 4) if never_before else None
        )
        row.space_vs_never_share_after = (
            round(row.live_bytes_after / never_after, 4) if never_after else None
        )
    return rows


def measure_hold_window(*, wait_snapshots: int = 3) -> dict:
    """Alice stays decryptable for wait_snapshots while a hold is live, then shred completes."""
    store = EraseStore()
    diary = ALICE_UNIQUE + b"\nhold-window\n"
    store.ingest("alice", "s0", "diary.txt", diary, FileClass.UNIQUE)
    store.hold("lawsuit", subject="alice", snapshot_id="s0")
    store.erase("alice")
    decryptable = 0
    for i in range(wait_snapshots):
        if store.restore("alice", "s0").bytes_for("diary.txt") == diary:
            decryptable += 1
        store.ingest("bob", f"s{i + 1}", "ping.bin", f"tick-{i}".encode(), FileClass.UNIQUE)
    flagged = store.restore("alice", "s0").contains_erased_subject
    store.release("lawsuit")
    gone = store.restore("alice", "s0").bytes_for("diary.txt") is None
    leftover = _leftover_join(store)
    return {
        "wait_snapshots": wait_snapshots,
        "decryptable_snapshots": decryptable,
        "flagged_during_hold": flagged,
        "gone_after_release": gone,
        "leftover_has_alice_after_release": ALICE_UNIQUE in leftover,
        "erases_blocked_by_hold": 1,
    }


def synthetic_trace(seed: int = 1, n_events: int = 180) -> list[tuple[str, str, str, str, bytes, str]]:
    rng = random.Random(seed)
    tenants = ("acme", "globex", "contoso")
    subjects = {"acme": ("alice", "bob"), "globex": ("carol", "dave"), "contoso": ("alice", "erin")}
    events = []
    shared_cache: dict[str, bytes] = {}
    for i in range(n_events):
        tenant = tenants[i % 3]
        subj = subjects[tenant][i % 2]
        t = f"t{i // 12}"
        roll = rng.random()
        if roll < 0.55:
            cls = "unique"
            marker = ALICE_UNIQUE if subj == "alice" else f"{subj.upper()}-ONLY".encode()
            data = _blob(rng, rng.choice((2048, 4096, 8192)), marker + b"\n")
            path = f"u/{i}.bin"
        elif roll < 0.85:
            cls = "identical"
            key = f"inst-{i // 6}"
            if key not in shared_cache:
                shared_cache[key] = _blob(rng, 16384, INSTALLER_PREFIX + key.encode())
            data = shared_cache[key]
            path = f"setup/{key}.exe"
        else:
            cls = "mixed"
            data = ALICE_MIXED + b"\n" + _blob(rng, 2048, b"") + BOB_MIXED + b"\n"
            path = f"mail/{i}.pst"
        events.append((t, tenant, subj, path, data, cls))
    return events


def measure_trace(seed: int = 1) -> dict:
    events = synthetic_trace(seed)
    byte_mix = {"unique": 0, "identical": 0, "mixed": 0}
    per_tenant: dict[str, dict[str, int]] = {}
    for _t, tenant, _s, _p, data, cls in events:
        byte_mix[cls] += len(data)
        bucket = per_tenant.setdefault(tenant, {"unique": 0, "identical": 0, "mixed": 0})
        bucket[cls] += len(data)
    total = sum(byte_mix.values()) or 1

    def _run(wrap: WrapMode, mixed: MixedPolicy, redactor=None) -> dict:
        store = EraseStore(wrap_mode=wrap, mixed_policy=mixed, redactor=redactor)
        for t, tenant, subj, path, data, cls in events:
            store.ingest(subj, t, f"{tenant}/{path}", data, cls)
        before = store.stats().live_bytes
        store.erase("alice")
        after = store.stats().live_bytes
        leftover = _leftover_join(store)
        return {
            "live_before": before,
            "live_after_erase_alice": after,
            "leftover_has_alice_unique": ALICE_UNIQUE in leftover,
            "recipes": class_mix(store),
        }

    claim = _run(WrapMode.OR_WRAP, MixedPolicy.COPY_OUT, strip_marker)
    never = _run(WrapMode.NO_CROSS_USER, MixedPolicy.NEVER_SHARE)
    return {
        "n_events": len(events),
        "logical_bytes": total,
        "byte_mix": byte_mix,
        "byte_mix_frac": {k: round(v / total, 4) for k, v in byte_mix.items()},
        "per_tenant_bytes": per_tenant,
        "copy_out_mixed": claim,
        "no_cross_user": never,
        "space_vs_never_share": round(
            claim["live_after_erase_alice"] / never["live_after_erase_alice"], 4
        )
        if never["live_after_erase_alice"]
        else None,
        "proxy": "synthetic tenant mix (not an enterprise trace)",
    }


def measure_containers() -> dict:
    copy_store = EraseStore(mixed_policy=MixedPolicy.COPY_OUT, redactor=strip_marker)
    ingest_mbox(copy_store, sample_mbox(), "tuesday")
    copy_store.erase("alice")
    bob_copy = copy_store.restore("bob", "tuesday")
    bob_text = b"".join(f.data or b"" for f in bob_copy.files.values())
    leak_store = EraseStore(mixed_policy=MixedPolicy.OR_WRAP)
    raw = sample_mbox()
    leak_store.ingest("alice", "tue", "inbox.mbox", raw, FileClass.MIXED)
    leak_store.ingest("bob", "tue", "inbox.mbox", raw, FileClass.MIXED)
    leak_store.erase("alice")
    whole = leak_store.restore("bob", "tue").bytes_for("inbox.mbox") or b""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "alice-solo.jpg").write_bytes(b"JPEG-ALICE-ONLY")
        (root / "bob-solo.jpg").write_bytes(b"JPEG-BOB-ONLY")
        (root / "group-alice-bob.jpg").write_bytes(b"JPEG-GROUP-ALICE-and-BOB")
        photos = EraseStore(mixed_policy=MixedPolicy.DROP_FOR_BOTH)
        ingest_photo_library(photos, root, "tuesday")
        photos.erase("alice")
        bob_p = photos.restore("bob", "tuesday")
        photo_bob_has_alice_solo = any(b"ALICE-ONLY" in (f.data or b"") for f in bob_p.files.values())
        photo_bob_has_group = any(b"GROUP-ALICE" in (f.data or b"") for f in bob_p.files.values() if f.ok)
    return {
        "mbox_inner_bob_has_alice_lane": b"Alice Lane" in bob_text,
        "mbox_whole_file_or_wrap_leaks": b"Alice Lane" in whole,
        "photo_bob_has_alice_solo": photo_bob_has_alice_solo,
        "photo_bob_group_dropped": not photo_bob_has_group,
    }


def run_eval(seed: int = 0) -> dict:
    rows = evaluate_modes(seed)
    return {
        "corpus": "synthetic labeled unique/identical/mixed, seed=%d" % seed,
        "modes": [asdict(r) for r in rows],
        "hold": measure_hold_window(),
        "trace": measure_trace(seed + 1),
        "containers": measure_containers(),
        "note": (
            "Laptop-scale synthetic. Do not claim enterprise generality. "
            "physical_bytes stay high because the chunk log is WORM; live_bytes is the decryptable set."
        ),
    }


def format_mode_table(rows: list[dict]) -> str:
    headers = [
        "mode",
        "alice_gone",
        "bob_ident",
        "mixed_leak",
        "live_after",
        "vs_ns_before",
        "vs_ns_after",
        "erase_ms",
    ]
    lines = ["  ".join(f"{h:>12}" for h in headers)]
    for r in rows:
        lines.append(
            "  ".join(
                [
                    f"{r['name']:>12}",
                    f"{str(r['alice_unique_gone']):>12}",
                    f"{str(r['bob_identical_ok']):>12}",
                    f"{str(r['bob_mixed_has_alice']):>12}",
                    f"{r['live_bytes_after']:>12}",
                    f"{r['space_vs_never_share_before']:>12}",
                    f"{r['space_vs_never_share_after']:>12}",
                    f"{r['erase_ms']:>12}",
                ]
            )
        )
    return "\n".join(lines)


def dumps_eval(result: dict) -> str:
    return json.dumps(result, indent=2)
