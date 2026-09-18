"""Minimal Matroska reader: Tracks + SimpleBlock/Block payloads."""

from __future__ import annotations

from dataclasses import dataclass, field


def read_vint(data: bytes, i: int) -> tuple[int, int]:
    if i >= len(data):
        raise ValueError("truncated vint")
    b0 = data[i]
    mask = 0x80
    length = 1
    while length <= 8 and (b0 & mask) == 0:
        mask >>= 1
        length += 1
    if length > 8 or i + length > len(data):
        raise ValueError("bad vint")
    value = b0 & (mask - 1)
    for j in range(1, length):
        value = (value << 8) | data[i + j]
    return value, length


def read_id(data: bytes, i: int) -> tuple[int, int]:
    """Element IDs keep the VINT length bit (Matroska / EBML)."""
    if i >= len(data):
        raise ValueError("truncated id")
    b0 = data[i]
    mask = 0x80
    length = 1
    while length <= 4 and (b0 & mask) == 0:
        mask >>= 1
        length += 1
    if length > 4 or i + length > len(data):
        raise ValueError("bad id")
    return int.from_bytes(data[i : i + length], "big"), length


@dataclass
class MkvBlock:
    track: int
    codec: bytes
    codec_private: bytes
    payload: bytes


@dataclass
class MkvMovie:
    blocks: list[MkvBlock] = field(default_factory=list)
    parameter_sets: list[bytes] = field(default_factory=list)
    ranges: list[tuple[int, int]] = field(default_factory=list)  # payload offsets in file


# Element IDs
_SEGMENT = 0x18538067
_TRACKS = 0x1654AE6B
_TRACK_ENTRY = 0xAE
_TRACK_NUMBER = 0xD7
_CODEC_ID = 0x86
_CODEC_PRIVATE = 0x63A2
_CLUSTER = 0x1F43B675
_SIMPLE_BLOCK = 0xA3
_BLOCK_GROUP = 0xA0
_BLOCK = 0xA1


def _walk(data: bytes, start: int, end: int):
    i = start
    while i + 1 < end:
        try:
            eid, n1 = read_id(data, i)
            size, n2 = read_vint(data, i + n1)
        except ValueError:
            break
        payload = i + n1 + n2
        if payload + size > end:
            break
        yield eid, i, payload, size
        i = payload + size


def _read_uint(data: bytes, start: int, size: int) -> int:
    return int.from_bytes(data[start : start + size], "big")


def _parse_tracks(data: bytes, start: int, end: int) -> dict[int, tuple[bytes, bytes]]:
    tracks: dict[int, tuple[bytes, bytes]] = {}
    for eid, _i, p, sz in _walk(data, start, end):
        if eid != _TRACK_ENTRY:
            continue
        number = None
        codec = b""
        priv = b""
        for teid, _ti, tp, tsz in _walk(data, p, p + sz):
            if teid == _TRACK_NUMBER:
                number = _read_uint(data, tp, tsz)
            elif teid == _CODEC_ID:
                codec = data[tp : tp + tsz].rstrip(b"\x00")
            elif teid == _CODEC_PRIVATE:
                priv = data[tp : tp + tsz]
        if number is not None:
            tracks[number] = (codec, priv)
    return tracks


def _laced_frames(payload: bytes, flags: int) -> list[bytes]:
    lacing = (flags >> 1) & 0x03
    if lacing == 0:
        return [payload] if payload else []
    if not payload:
        return []
    n_frames = payload[0] + 1
    i = 1
    sizes: list[int] = []
    if lacing == 1:  # Xiph
        remaining = n_frames - 1
        while remaining:
            acc = 0
            while i < len(payload) and payload[i] == 255:
                acc += 255
                i += 1
            if i >= len(payload):
                return [payload]
            acc += payload[i]
            i += 1
            sizes.append(acc)
            remaining -= 1
        last = len(payload) - i - sum(sizes)
        sizes.append(max(last, 0))
    elif lacing == 2:  # fixed
        body = len(payload) - 1
        if n_frames == 0 or body % n_frames:
            return [payload[1:]]
        each = body // n_frames
        return [payload[1 + k * each : 1 + (k + 1) * each] for k in range(n_frames)]
    else:  # EBML
        remaining = n_frames - 1
        prev = None
        while remaining:
            val, n = read_vint(payload, i)
            i += n
            # first size is unsigned; later are signed offsets from previous
            if prev is None:
                prev = val
            else:
                bias = (1 << (7 * n - 1)) - 1
                prev = prev + (val - bias)
            sizes.append(prev)
            remaining -= 1
        last = len(payload) - i - sum(sizes)
        sizes.append(max(last, 0))
    frames = []
    for sz in sizes:
        frames.append(payload[i : i + sz])
        i += sz
    return [f for f in frames if f]


def _parse_block(data: bytes, p: int, size: int, tracks: dict[int, tuple[bytes, bytes]]) -> list[tuple[MkvBlock, int, int]]:
    try:
        track, n = read_vint(data, p)
    except ValueError:
        return []
    if p + n + 3 > p + size:
        return []
    flags = data[p + n + 2]
    payload_off = p + n + 3
    payload = data[payload_off : p + size]
    frames = _laced_frames(payload, flags)
    codec, priv = tracks.get(track, (b"", b""))
    out = []
    cursor = payload_off
    # For no-lacing, the whole payload is one frame at payload_off.
    if ((flags >> 1) & 0x03) == 0:
        out.append(
            (
                MkvBlock(track=track, codec=codec, codec_private=priv, payload=payload),
                payload_off,
                len(payload),
            )
        )
        return out
    for frame in frames:
        out.append(
            (
                MkvBlock(track=track, codec=codec, codec_private=priv, payload=frame),
                cursor,
                len(frame),
            )
        )
        cursor += len(frame)
    return out


def parse_mkv(data: bytes) -> MkvMovie:
    movie = MkvMovie()
    tracks: dict[int, tuple[bytes, bytes]] = {}
    # Skip EBML header, find Segment
    for eid, _i, p, sz in _walk(data, 0, len(data)):
        if eid != _SEGMENT:
            continue
        for seid, _si, sp, ssz in _walk(data, p, p + sz):
            if seid == _TRACKS:
                tracks = _parse_tracks(data, sp, sp + ssz)
            elif seid == _CLUSTER:
                for ceid, _ci, cp, csz in _walk(data, sp, sp + ssz):
                    if ceid == _SIMPLE_BLOCK:
                        for block, off, ln in _parse_block(data, cp, csz, tracks):
                            movie.blocks.append(block)
                            movie.ranges.append((off, ln))
                    elif ceid == _BLOCK_GROUP:
                        for beid, _bi, bp, bsz in _walk(data, cp, cp + csz):
                            if beid == _BLOCK:
                                for block, off, ln in _parse_block(data, bp, bsz, tracks):
                                    movie.blocks.append(block)
                                    movie.ranges.append((off, ln))
        break
    from cascade_dedup.media import parse_avcc

    for codec, priv in tracks.values():
        if codec in {b"V_MPEG4/ISO/AVC", b"V_MPEG4/ISO/AVC"} or codec.startswith(b"V_MPEG4/ISO/AVC"):
            _, psets = parse_avcc(priv)
            for nal in psets:
                if nal not in movie.parameter_sets:
                    movie.parameter_sets.append(nal)
    return movie
