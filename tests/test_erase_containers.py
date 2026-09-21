"""Inner-object erase on one mbox and one two-subject photo folder."""

from __future__ import annotations

from cascade_dedup.containers import ingest_mbox, ingest_photo_library, sample_mbox
from cascade_dedup.erase import EraseStore, FileClass, MixedPolicy, strip_marker


def test_mbox_inner_erase():
    store = EraseStore(mixed_policy=MixedPolicy.COPY_OUT, redactor=strip_marker)
    items = ingest_mbox(store, sample_mbox(), "tuesday")
    assert any(i.file_class is FileClass.MIXED for i in items)
    assert any(i.file_class is FileClass.IDENTICAL for i in items)
    store.erase("alice")
    alice = store.restore("alice", "tuesday")
    bob = store.restore("bob", "tuesday")
    assert all(not f.ok for f in alice.files.values())
    bob_text = b"".join(f.data or b"" for f in bob.files.values())
    assert b"contract" in bob_text.lower() or b"BOB" in bob_text or b"Bob" in bob_text
    assert b"Alice Lane" not in bob_text
    leftover = b"".join(store.leftover_plaintexts(exclude_subject="alice"))
    assert b"Alice Lane" not in leftover


def test_mbox_whole_file_or_wrap_leaks():
    store = EraseStore(mixed_policy=MixedPolicy.OR_WRAP)
    raw = sample_mbox()
    store.ingest("alice", "tue", "inbox.mbox", raw, FileClass.MIXED)
    store.ingest("bob", "tue", "inbox.mbox", raw, FileClass.MIXED)
    store.erase("alice")
    bob = store.restore("bob", "tue").bytes_for("inbox.mbox")
    assert bob is not None and b"Alice Lane" in bob


def test_photo_library(tmp_path):
    (tmp_path / "alice-solo.jpg").write_bytes(b"JPEG-ALICE-ONLY")
    (tmp_path / "bob-solo.jpg").write_bytes(b"JPEG-BOB-ONLY")
    (tmp_path / "group-alice-bob.jpg").write_bytes(b"JPEG-GROUP-ALICE-and-BOB")
    (tmp_path / "alice-setup.bin").write_bytes(b"same-photo-bytes")
    (tmp_path / "bob-setup.bin").write_bytes(b"same-photo-bytes")
    store = EraseStore(mixed_policy=MixedPolicy.DROP_FOR_BOTH)
    ingest_photo_library(store, tmp_path, "tuesday")
    store.erase("alice")
    bob = store.restore("bob", "tuesday")
    alice = store.restore("alice", "tuesday")
    assert any(f.data == b"JPEG-BOB-ONLY" for f in bob.files.values())
    assert all(f.data != b"JPEG-ALICE-ONLY" for f in alice.files.values() if f.data)
    assert all(
        f.data != b"JPEG-GROUP-ALICE-and-BOB" for f in bob.files.values() if f.ok
    )
    leftover = b"".join(store.leftover_plaintexts(exclude_subject="alice"))
    assert b"ALICE-ONLY" not in leftover
