"""Subject-scoped erase in a chunk-deduplicated, immutable backup.

Recipes and ciphertext are append-only. Control keys and wraps live in a
mutable key store and may be shredded. Plaintext fingerprints are computed
at ingest (trusted backup client), not by the untrusted disk.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cascade_dedup.chunking import fingerprint as blake_fp

CHUNK_SIZE = 4096
Redactor = Callable[[bytes, str], bytes]


class FileClass(str, Enum):
    UNIQUE = "unique"
    IDENTICAL = "identical"
    MIXED = "mixed"


class WrapMode(str, Enum):
    OR_WRAP = "or-wrap"
    AND_WRAP = "and-wrap"
    NO_CROSS_USER = "no-cross-user"


class MixedPolicy(str, Enum):
    NEVER_SHARE = "never-share"
    OR_WRAP = "or-wrap"
    COPY_OUT = "copy-out-mixed"
    DROP_FOR_BOTH = "drop-for-both"
    KEEP_FOR_BOB = "keep-for-bob"


def _aes_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def _encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, None)


def _decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _split(data: bytes) -> list[bytes]:
    if not data:
        return [b""]
    return [data[i : i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]


@dataclass
class Recipe:
    subject: str
    snapshot_id: str
    path: str
    chunk_ids: list[str]
    file_class: FileClass
    erased: bool = False
    unrestorable: bool = False


@dataclass
class ChunkRecord:
    chunk_id: str
    plaintext_fp: bytes
    nonce: bytes
    ciphertext: bytes
    file_class: FileClass
    owners: set[str] = field(default_factory=set)


@dataclass
class Hold:
    hold_id: str
    subject: str | None = None
    snapshot_id: str | None = None
    path: str | None = None


@dataclass
class FileRestore:
    path: str
    data: bytes | None
    ok: bool
    unrestorable: bool = False
    contains_erased_subject: bool = False
    reason: str = ""


@dataclass
class RestoreResult:
    files: dict[str, FileRestore]
    contains_erased_subject: bool = False

    def bytes_for(self, path: str) -> bytes | None:
        rec = self.files.get(path)
        return None if rec is None else rec.data


@dataclass
class StoreStats:
    physical_bytes: int
    live_bytes: int
    n_chunks: int
    n_live_chunks: int
    n_recipes: int


class EraseStore:
    """In-memory prototype: chunk log + recipes + key store."""

    def __init__(
        self,
        *,
        wrap_mode: WrapMode = WrapMode.OR_WRAP,
        mixed_policy: MixedPolicy = MixedPolicy.NEVER_SHARE,
        redactor: Redactor | None = None,
    ) -> None:
        self.wrap_mode = wrap_mode
        self.mixed_policy = mixed_policy
        self.redactor = redactor
        self.chunks: dict[str, ChunkRecord] = {}
        self.fp_index: dict[bytes, list[str]] = {}
        self.recipes: list[Recipe] = []
        self.subject_keys: dict[str, bytes | None] = {}
        self.wraps: dict[tuple[str, str], tuple[bytes, bytes]] = {}
        self.holds: dict[str, Hold] = {}
        self.pins: dict[str, int] = {}
        self.pending_erase: set[str] = set()
        self.copyouts: dict[tuple[str, str, str], list[str]] = {}
        self.recoverability_windows: list[dict] = []

    def _subject_key(self, subject: str) -> bytes:
        key = self.subject_keys.get(subject)
        if key is None:
            key = _aes_key()
            self.subject_keys[subject] = key
        return key

    def _wrap_dek(self, chunk_id: str, subject: str, dek: bytes) -> None:
        nonce, wrapped = _encrypt(self._subject_key(subject), dek)
        self.wraps[(chunk_id, subject)] = (nonce, wrapped)

    def _unwrap_dek(self, chunk_id: str, subject: str) -> bytes | None:
        skey = self.subject_keys.get(subject)
        wrap = self.wraps.get((chunk_id, subject))
        if skey is None or wrap is None:
            return None
        nonce, wrapped = wrap
        try:
            return _decrypt(skey, nonce, wrapped)
        except Exception:
            return None

    def _chunk_pinned(self, chunk_id: str) -> bool:
        return self.pins.get(f"chunk:{chunk_id}", 0) > 0

    def _subject_pinned(self, subject: str) -> bool:
        return self.pins.get(f"subject:{subject}", 0) > 0

    def _recipe_held(self, recipe: Recipe) -> bool:
        for hold in self.holds.values():
            if hold.subject and hold.subject != recipe.subject:
                continue
            if hold.snapshot_id and hold.snapshot_id != recipe.snapshot_id:
                continue
            if hold.path and hold.path != recipe.path:
                continue
            if hold.subject or hold.snapshot_id or hold.path:
                return True
        return False

    def _put_payload(
        self,
        subject: str,
        data: bytes,
        file_class: FileClass,
        *,
        share: bool,
    ) -> list[str]:
        ids: list[str] = []
        for piece in _split(data):
            fp = blake_fp(piece)
            reuse: str | None = None
            if share:
                for cid in self.fp_index.get(fp, []):
                    rec = self.chunks[cid]
                    if rec.file_class != file_class:
                        continue
                    dek = None
                    for owner in rec.owners:
                        dek = self._unwrap_dek(cid, owner)
                        if dek is not None:
                            break
                    if dek is None:
                        continue
                    reuse = cid
                    rec.owners.add(subject)
                    self._wrap_dek(cid, subject, dek)
                    break
            if reuse is None:
                dek = _aes_key()
                nonce, ct = _encrypt(dek, piece)
                cid = uuid.uuid4().hex
                self.chunks[cid] = ChunkRecord(
                    chunk_id=cid,
                    plaintext_fp=fp,
                    nonce=nonce,
                    ciphertext=ct,
                    file_class=file_class,
                    owners={subject},
                )
                self.fp_index.setdefault(fp, []).append(cid)
                self._wrap_dek(cid, subject, dek)
                reuse = cid
            ids.append(reuse)
        return ids

    def ingest(
        self,
        subject: str,
        snapshot_id: str,
        path: str,
        data: bytes,
        file_class: FileClass | str,
    ) -> Recipe:
        file_class = FileClass(file_class)
        share = False
        if file_class is FileClass.UNIQUE:
            for piece in _split(data):
                fp = blake_fp(piece)
                for cid in self.fp_index.get(fp, []):
                    rec = self.chunks[cid]
                    if rec.owners - {subject}:
                        raise ValueError(
                            f"unique label lied: {path!r} already owned by {rec.owners}"
                        )
            share = True
        elif file_class is FileClass.IDENTICAL:
            if self.wrap_mode is WrapMode.NO_CROSS_USER:
                share = False
            else:
                share = True
        else:
            if self.mixed_policy is MixedPolicy.OR_WRAP and self.wrap_mode is not WrapMode.NO_CROSS_USER:
                share = True
            else:
                share = False

        chunk_ids = self._put_payload(subject, data, file_class, share=share)
        recipe = Recipe(
            subject=subject,
            snapshot_id=snapshot_id,
            path=path,
            chunk_ids=chunk_ids,
            file_class=file_class,
        )
        self.recipes.append(recipe)
        return recipe

    def _assemble(self, subject: str, chunk_ids: list[str]) -> bytes | None:
        parts: list[bytes] = []
        for cid in chunk_ids:
            rec = self.chunks.get(cid)
            dek = self._unwrap_dek(cid, subject)
            if rec is None or dek is None:
                return None
            try:
                parts.append(_decrypt(dek, rec.nonce, rec.ciphertext))
            except Exception:
                return None
        return b"".join(parts)

    def restore(self, subject: str, snapshot_id: str) -> RestoreResult:
        files: dict[str, FileRestore] = {}
        flagged = False
        for recipe in self.recipes:
            if recipe.subject != subject or recipe.snapshot_id != snapshot_id:
                continue
            copy_ids = self.copyouts.get((subject, snapshot_id, recipe.path))
            held = self._recipe_held(recipe)
            if copy_ids is not None:
                data = self._assemble(subject, copy_ids)
                files[recipe.path] = FileRestore(
                    path=recipe.path,
                    data=data,
                    ok=data is not None,
                    unrestorable=False,
                    contains_erased_subject=False,
                    reason="copy-out",
                )
                continue
            if recipe.erased and not held:
                files[recipe.path] = FileRestore(
                    path=recipe.path,
                    data=None,
                    ok=False,
                    reason="recipe-erased",
                )
                continue
            if recipe.unrestorable:
                files[recipe.path] = FileRestore(
                    path=recipe.path,
                    data=None,
                    ok=False,
                    unrestorable=True,
                    reason="immutable-mixed",
                )
                continue
            data = self._assemble(subject, recipe.chunk_ids)
            contains = data is not None and (
                subject in self.pending_erase
                or (bool(self.pending_erase) and recipe.file_class is FileClass.MIXED)
            )
            files[recipe.path] = FileRestore(
                path=recipe.path,
                data=data,
                ok=data is not None,
                contains_erased_subject=contains,
                reason="" if data is not None else "missing-key",
            )
            flagged = flagged or contains
        return RestoreResult(files=files, contains_erased_subject=flagged)

    def hold(
        self,
        hold_id: str,
        *,
        subject: str | None = None,
        snapshot_id: str | None = None,
        path: str | None = None,
    ) -> None:
        hold = Hold(hold_id=hold_id, subject=subject, snapshot_id=snapshot_id, path=path)
        self.holds[hold_id] = hold
        for recipe in self.recipes:
            if subject and recipe.subject != subject:
                continue
            if snapshot_id and recipe.snapshot_id != snapshot_id:
                continue
            if path and recipe.path != path:
                continue
            if not (subject or snapshot_id or path):
                continue
            self.pins[f"subject:{recipe.subject}"] = self.pins.get(f"subject:{recipe.subject}", 0) + 1
            for cid in recipe.chunk_ids:
                self.pins[f"chunk:{cid}"] = self.pins.get(f"chunk:{cid}", 0) + 1

    def release(self, hold_id: str) -> None:
        hold = self.holds.pop(hold_id, None)
        if hold is None:
            return
        for recipe in self.recipes:
            if hold.subject and recipe.subject != hold.subject:
                continue
            if hold.snapshot_id and recipe.snapshot_id != hold.snapshot_id:
                continue
            if hold.path and recipe.path != hold.path:
                continue
            if not (hold.subject or hold.snapshot_id or hold.path):
                continue
            sk = f"subject:{recipe.subject}"
            self.pins[sk] = max(0, self.pins.get(sk, 0) - 1)
            for cid in recipe.chunk_ids:
                ck = f"chunk:{cid}"
                self.pins[ck] = max(0, self.pins.get(ck, 0) - 1)
        for subject in list(self.pending_erase):
            if not self._subject_pinned(subject):
                self._finish_erase(subject)

    def erase(self, subject: str) -> None:
        if self._subject_pinned(subject):
            self.pending_erase.add(subject)
            self.recoverability_windows.append(
                {"subject": subject, "blocked": True, "holds": list(self.holds)}
            )
            for recipe in self.recipes:
                if recipe.subject == subject and not self._recipe_held(recipe):
                    recipe.erased = True
            return
        self._finish_erase(subject)

    def _finish_erase(self, subject: str) -> None:
        self.pending_erase.discard(subject)
        for recipe in self.recipes:
            if recipe.subject == subject:
                recipe.erased = True
        affected = [c for c in self.chunks.values() if subject in c.owners]
        mixed_touched = [c for c in affected if c.file_class is FileClass.MIXED]
        for rec in affected:
            rec.owners.discard(subject)
            self.wraps.pop((rec.chunk_id, subject), None)
            if self.wrap_mode is WrapMode.AND_WRAP:
                self._shred_chunk(rec)
                continue
            if not rec.owners and not self._chunk_pinned(rec.chunk_id):
                self._shred_chunk(rec)

        if mixed_touched and self.wrap_mode is not WrapMode.AND_WRAP:
            self._apply_mixed_policy(subject)

        if not self._subject_pinned(subject):
            self.subject_keys[subject] = None

    def _shred_chunk(self, rec: ChunkRecord) -> None:
        for owner in list(rec.owners):
            self.wraps.pop((rec.chunk_id, owner), None)
        rec.owners.clear()
        for cid_list in self.fp_index.values():
            if rec.chunk_id in cid_list:
                cid_list.remove(rec.chunk_id)

    def _apply_mixed_policy(self, erased: str) -> None:
        policy = self.mixed_policy
        mixed_recipes = [
            r
            for r in self.recipes
            if r.file_class is FileClass.MIXED and r.subject != erased
        ]
        if policy is MixedPolicy.OR_WRAP or policy is MixedPolicy.KEEP_FOR_BOB:
            return
        if policy is MixedPolicy.NEVER_SHARE:
            return
        if policy is MixedPolicy.DROP_FOR_BOTH:
            for recipe in self.recipes:
                if recipe.file_class is FileClass.MIXED:
                    recipe.unrestorable = True
                    for cid in recipe.chunk_ids:
                        rec = self.chunks.get(cid)
                        if rec is not None:
                            self._shred_chunk(rec)
            return
        if policy is MixedPolicy.COPY_OUT:
            originals: list[str] = []
            for recipe in mixed_recipes:
                recipe.unrestorable = True
                originals.extend(recipe.chunk_ids)
                if self.redactor is None:
                    continue
                pt = self._assemble(recipe.subject, recipe.chunk_ids)
                if pt is None:
                    continue
                new_ids = self._put_payload(
                    recipe.subject,
                    self.redactor(pt, erased),
                    FileClass.UNIQUE,
                    share=False,
                )
                self.copyouts[(recipe.subject, recipe.snapshot_id, recipe.path)] = new_ids
            for cid in originals:
                rec = self.chunks.get(cid)
                if rec is not None:
                    self._shred_chunk(rec)
            return

    def leftover_plaintexts(self, *, exclude_subject: str | None = None) -> list[bytes]:
        """Decrypt everything still reachable from remaining keys (leftover-store attacker)."""
        out: list[bytes] = []
        seen: set[str] = set()
        for (chunk_id, subject), _wrap in list(self.wraps.items()):
            if exclude_subject and subject == exclude_subject:
                continue
            if self.subject_keys.get(subject) is None:
                continue
            if chunk_id in seen:
                continue
            rec = self.chunks.get(chunk_id)
            dek = self._unwrap_dek(chunk_id, subject)
            if rec is None or dek is None:
                continue
            try:
                out.append(_decrypt(dek, rec.nonce, rec.ciphertext))
                seen.add(chunk_id)
            except Exception:
                continue
        return out

    def stats(self) -> StoreStats:
        physical = sum(len(c.ciphertext) for c in self.chunks.values())
        live = 0
        n_live = 0
        for rec in self.chunks.values():
            if any(self._unwrap_dek(rec.chunk_id, o) for o in rec.owners):
                live += len(rec.ciphertext)
                n_live += 1
        return StoreStats(
            physical_bytes=physical,
            live_bytes=live,
            n_chunks=len(self.chunks),
            n_live_chunks=n_live,
            n_recipes=len(self.recipes),
        )


def strip_marker(data: bytes, subject: str) -> bytes:
    """Test redactor: drop lines that contain the subject name (any case)."""
    token = subject.encode().lower()
    lines = data.split(b"\n")
    return b"\n".join(line for line in lines if token not in line.lower())


def class_mix(store: EraseStore) -> dict[str, int]:
    counts = {c.value: 0 for c in FileClass}
    for recipe in store.recipes:
        counts[recipe.file_class.value] += 1
    return counts


def replay_trace(
    events: Iterable[tuple[str, str, str, str, bytes, str]],
    *,
    wrap_mode: WrapMode = WrapMode.OR_WRAP,
    mixed_policy: MixedPolicy = MixedPolicy.NEVER_SHARE,
) -> tuple[EraseStore, dict]:
    """events: (time, tenant, subject, path, bytes, class)."""
    store = EraseStore(wrap_mode=wrap_mode, mixed_policy=mixed_policy)
    tenants: dict[str, int] = {}
    for time, tenant, subject, path, data, file_class in events:
        store.ingest(subject, time, f"{tenant}/{path}", data, file_class)
        tenants[tenant] = tenants.get(tenant, 0) + 1
    mix = class_mix(store)
    before = store.stats()
    return store, {"tenants": tenants, "mix": mix, "before": before}
