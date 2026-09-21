"""Policy tests for subject-scoped erase (not a CDC-ratio contest)."""

from __future__ import annotations

from cascade_dedup.erase import (
    EraseStore,
    FileClass,
    MixedPolicy,
    WrapMode,
    replay_trace,
    strip_marker,
)


DIARY = b"Alice diary: secret"
INSTALLER = b"OfficeSetup.exe" + b"X" * 100
MIXED = b"line ALICE home\nline BOB contract\n"


def ingest_pair(store: EraseStore, snap: str = "tuesday") -> None:
    store.ingest("alice", snap, "diary.txt", DIARY, FileClass.UNIQUE)
    store.ingest("bob", snap, "notes.txt", b"Bob only notes", FileClass.UNIQUE)
    store.ingest("alice", snap, "setup.exe", INSTALLER, FileClass.IDENTICAL)
    store.ingest("bob", snap, "setup.exe", INSTALLER, FileClass.IDENTICAL)
    store.ingest("alice", snap, "legal.pst", MIXED, FileClass.MIXED)
    store.ingest("bob", snap, "legal.pst", MIXED, FileClass.MIXED)


def test_unique_erase_alice():
    store = EraseStore()
    ingest_pair(store)
    store.erase("alice")
    alice = store.restore("alice", "tuesday")
    bob = store.restore("bob", "tuesday")
    assert alice.bytes_for("diary.txt") is None
    assert bob.bytes_for("notes.txt") == b"Bob only notes"
    leftover = b"".join(store.leftover_plaintexts(exclude_subject="alice"))
    assert b"secret" not in leftover


def test_identical_or_wrap_keeps_one_copy_for_bob():
    store = EraseStore(wrap_mode=WrapMode.OR_WRAP)
    ingest_pair(store)
    before = store.stats()
    store.erase("alice")
    bob = store.restore("bob", "tuesday")
    alice = store.restore("alice", "tuesday")
    assert alice.bytes_for("setup.exe") is None
    assert bob.bytes_for("setup.exe") == INSTALLER
    after = store.stats()
    assert after.n_live_chunks < before.n_live_chunks
    live_installers = [
        p for p in store.leftover_plaintexts() if p == INSTALLER or INSTALLER in p
    ]
    assert live_installers


def test_and_wrap_blinds_bob_on_identical():
    store = EraseStore(wrap_mode=WrapMode.AND_WRAP)
    ingest_pair(store)
    store.erase("alice")
    bob = store.restore("bob", "tuesday")
    assert bob.bytes_for("setup.exe") is None


def test_no_cross_user_two_copies():
    store = EraseStore(wrap_mode=WrapMode.NO_CROSS_USER)
    store.ingest("alice", "tue", "setup.exe", INSTALLER, FileClass.IDENTICAL)
    store.ingest("bob", "tue", "setup.exe", INSTALLER, FileClass.IDENTICAL)
    assert store.stats().n_chunks == 2
    store.erase("alice")
    assert store.restore("bob", "tue").bytes_for("setup.exe") == INSTALLER
    assert store.stats().n_live_chunks == 1


def test_or_wrap_mixed_leaks_alice_via_bob():
    store = EraseStore(mixed_policy=MixedPolicy.OR_WRAP)
    ingest_pair(store)
    store.erase("alice")
    bob = store.restore("bob", "tuesday").bytes_for("legal.pst")
    assert bob is not None and b"ALICE" in bob
    leftover = b"".join(store.leftover_plaintexts())
    assert b"ALICE" in leftover


def test_copy_out_mixed_redacts_alice():
    store = EraseStore(mixed_policy=MixedPolicy.COPY_OUT, redactor=strip_marker)
    ingest_pair(store)
    store.erase("alice")
    bob = store.restore("bob", "tuesday")
    data = bob.bytes_for("legal.pst")
    assert data is not None
    assert b"ALICE" not in data
    assert b"BOB" in data
    leftover = b"".join(store.leftover_plaintexts(exclude_subject="alice"))
    assert b"ALICE" not in leftover
    assert store.restore("alice", "tuesday").bytes_for("legal.pst") is None


def test_drop_for_both_mixed():
    store = EraseStore(mixed_policy=MixedPolicy.DROP_FOR_BOTH)
    ingest_pair(store)
    store.erase("alice")
    assert store.restore("bob", "tuesday").bytes_for("legal.pst") is None


def test_unique_label_conflict():
    store = EraseStore()
    store.ingest("alice", "tue", "a.bin", b"same", FileClass.UNIQUE)
    try:
        store.ingest("bob", "tue", "b.bin", b"same", FileClass.UNIQUE)
        raise AssertionError("expected conflict")
    except ValueError:
        pass


def test_hold_defers_alice_shred():
    store = EraseStore()
    ingest_pair(store)
    store.hold("h1", subject="alice", snapshot_id="tuesday")
    store.erase("alice")
    got = store.restore("alice", "tuesday")
    assert got.bytes_for("diary.txt") == DIARY
    assert got.contains_erased_subject
    leftover = b"".join(store.leftover_plaintexts())
    assert b"secret" in leftover
    store.release("h1")
    assert store.restore("alice", "tuesday").bytes_for("diary.txt") is None
    leftover2 = b"".join(store.leftover_plaintexts(exclude_subject="alice"))
    assert b"secret" not in leftover2


def test_hold_bob_identical_keeps_k():
    store = EraseStore()
    ingest_pair(store)
    store.hold("h2", subject="bob", snapshot_id="tuesday")
    store.erase("alice")
    assert store.restore("alice", "tuesday").bytes_for("setup.exe") is None
    assert store.restore("bob", "tuesday").bytes_for("setup.exe") == INSTALLER


def test_erase_then_hold_cannot_revive():
    store = EraseStore()
    ingest_pair(store)
    store.erase("alice")
    store.hold("late", subject="alice", snapshot_id="tuesday")
    assert store.restore("alice", "tuesday").bytes_for("diary.txt") is None


def test_trace_replay_mix_and_erase_cost():
    events = [
        ("t0", "acme", "alice", "diary.txt", DIARY, "unique"),
        ("t0", "acme", "bob", "notes.txt", b"bob", "unique"),
        ("t0", "acme", "alice", "setup.exe", INSTALLER, "identical"),
        ("t0", "acme", "bob", "setup.exe", INSTALLER, "identical"),
        ("t0", "globex", "carol", "x.bin", b"carol-only", "unique"),
    ]
    store, info = replay_trace(events)
    assert info["mix"]["unique"] == 3
    assert info["mix"]["identical"] == 2
    before_live = store.stats().live_bytes
    store.erase("alice")
    after_live = store.stats().live_bytes
    assert after_live < before_live
    assert store.restore("bob", "t0").bytes_for("acme/setup.exe") == INSTALLER
