"""Parse one mbox and one two-subject photo library into inner ingest objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email import message_from_bytes
from email.message import Message
from pathlib import Path

from cascade_dedup.erase import EraseStore, FileClass

@dataclass
class InnerObject:
    subject: str
    path: str
    data: bytes
    file_class: FileClass


def _subjects_from_message(msg: Message) -> list[str]:
    raw = msg.get("X-Backup-Subject", "")
    if raw.strip():
        return [p.strip().lower() for p in raw.split(",") if p.strip()]
    who = (msg.get("From") or "").lower()
    if "alice" in who:
        return ["alice"]
    if "bob" in who:
        return ["bob"]
    return ["unknown"]


def parse_mbox(data: bytes, *, container: str = "inbox.mbox") -> list[InnerObject]:
    if data.startswith(b"From "):
        bodies = [c for c in re.split(rb"(?=^From )", data, flags=re.MULTILINE) if c.strip()]
    else:
        bodies = [data] if data.strip() else []

    out: list[InnerObject] = []
    seen_payload: dict[bytes, str] = {}
    for i, raw in enumerate(bodies):
        msg = message_from_bytes(raw)
        owners = _subjects_from_message(msg)
        payload = msg.get_payload(decode=True)
        if payload is None:
            payload = (msg.get_payload() or "").encode() if not msg.is_multipart() else raw
        if msg.is_multipart():
            bits = []
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                body = part.get_payload(decode=True) or b""
                bits.append(body)
            payload = b"\n".join(bits) or raw

        payload = payload.strip()
        if len(owners) > 1:
            cls = FileClass.MIXED
            for owner in owners:
                out.append(
                    InnerObject(
                        subject=owner,
                        path=f"{container}/msg/{i}",
                        data=payload,
                        file_class=cls,
                    )
                )
            continue

        owner = owners[0]
        cls = FileClass.IDENTICAL if payload in seen_payload and seen_payload[payload] != owner else FileClass.UNIQUE
        if payload not in seen_payload:
            seen_payload[payload] = owner
        elif seen_payload[payload] != owner:
            cls = FileClass.IDENTICAL
            for prev in out:
                if prev.data == payload:
                    prev.file_class = FileClass.IDENTICAL
        out.append(
            InnerObject(
                subject=owner,
                path=f"{container}/msg/{i}/{owner}",
                data=payload,
                file_class=cls,
            )
        )
    return out


def ingest_mbox(store: EraseStore, data: bytes, snapshot_id: str, *, container: str = "inbox.mbox") -> list[InnerObject]:
    items = parse_mbox(data, container=container)
    for item in items:
        store.ingest(item.subject, snapshot_id, item.path, item.data, item.file_class)
    return items


def parse_photo_library(root: str | Path) -> list[InnerObject]:
    root = Path(root)
    out: list[InnerObject] = []
    seen: dict[bytes, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        data = path.read_bytes()
        name = path.stem.lower()
        rel = str(path.relative_to(root))
        people = [p for p in ("alice", "bob") if p in name]
        if len(people) > 1 or "group" in name:
            cls = FileClass.MIXED
            who = people or ["alice", "bob"]
            for owner in who:
                out.append(InnerObject(subject=owner, path=f"photos/{rel}", data=data, file_class=cls))
            continue
        owner = people[0] if people else "alice"
        cls = FileClass.UNIQUE
        if data in seen and seen[data] != owner:
            cls = FileClass.IDENTICAL
            for prev in out:
                if prev.data == data:
                    prev.file_class = FileClass.IDENTICAL
        elif data in seen:
            cls = FileClass.IDENTICAL
        else:
            seen[data] = owner
        out.append(InnerObject(subject=owner, path=f"photos/{rel}", data=data, file_class=cls))
    return out


def ingest_photo_library(store: EraseStore, root: str | Path, snapshot_id: str) -> list[InnerObject]:
    items = parse_photo_library(root)
    for item in items:
        store.ingest(item.subject, snapshot_id, item.path, item.data, item.file_class)
    return items


def sample_mbox() -> bytes:
    return b"""From alice@example.com Sun Sep 20 00:00:00 2026
X-Backup-Subject: alice
From: Alice <alice@example.com>
Subject: address

My home address is 1 Alice Lane.

From bob@example.com Sun Sep 20 00:01:00 2026
X-Backup-Subject: bob
From: Bob <bob@example.com>
Subject: contract

Bob's contract text.

From mixed@example.com Sun Sep 20 00:02:00 2026
X-Backup-Subject: alice, bob
From: legal@example.com
Subject: thread

ALICE and BOB are both on this thread.

From alice@example.com Sun Sep 20 00:03:00 2026
X-Backup-Subject: alice
From: Alice <alice@example.com>
Subject: installer

OfficeSetup-bytes-identical

From bob@example.com Sun Sep 20 00:04:00 2026
X-Backup-Subject: bob
From: Bob <bob@example.com>
Subject: installer

OfficeSetup-bytes-identical
"""
