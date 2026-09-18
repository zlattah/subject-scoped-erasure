"""ISO BMFF (MP4 / fragmented MP4) sample extraction for Dewakar-style hashing."""

from __future__ import annotations

from dataclasses import dataclass, field

from cascade_dedup.media import parse_avcc


@dataclass
class Mp4Sample:
    track_id: int
    handler: bytes  # b'vide' | b'soun' | ...
    offset: int
    size: int
    codec: bytes
    nal_length_size: int | None = None
    parameter_sets: tuple[bytes, ...] = ()


@dataclass
class Mp4Movie:
    samples: list[Mp4Sample] = field(default_factory=list)
    parameter_sets: list[bytes] = field(default_factory=list)


def _u32(data: bytes, i: int) -> int:
    return int.from_bytes(data[i : i + 4], "big")


def iter_boxes(data: bytes, start: int, end: int):
    i = start
    while i + 8 <= end:
        size = _u32(data, i)
        typ = data[i + 4 : i + 8]
        hdr = 8
        if size == 1:
            if i + 16 > end:
                break
            size = int.from_bytes(data[i + 8 : i + 16], "big")
            hdr = 16
        elif size == 0:
            size = end - i
        if size < hdr or i + size > end:
            break
        yield i, hdr, size, typ
        i += size


def find_child(data: bytes, start: int, end: int, want: bytes) -> tuple[int, int, int] | None:
    for i, hdr, size, typ in iter_boxes(data, start, end):
        if typ == want:
            return i, hdr, size
    return None


def _fullbox_payload(data: bytes, i: int, hdr: int, size: int) -> tuple[int, int, int]:
    """Return (version, flags, payload_offset)."""
    p = i + hdr
    ver = data[p]
    flags = int.from_bytes(data[p + 1 : p + 4], "big")
    return ver, flags, p + 4


def parse_stsz(data: bytes, i: int, hdr: int, size: int) -> list[int]:
    _, _, p = _fullbox_payload(data, i, hdr, size)
    default = _u32(data, p)
    count = _u32(data, p + 4)
    if default:
        return [default] * count
    out = []
    q = p + 8
    for _ in range(count):
        out.append(_u32(data, q))
        q += 4
    return out


def parse_stco(data: bytes, i: int, hdr: int, size: int, *, wide: bool) -> list[int]:
    _, _, p = _fullbox_payload(data, i, hdr, size)
    count = _u32(data, p)
    q = p + 4
    out = []
    step = 8 if wide else 4
    for _ in range(count):
        out.append(int.from_bytes(data[q : q + step], "big"))
        q += step
    return out


def parse_stsc(data: bytes, i: int, hdr: int, size: int) -> list[tuple[int, int, int]]:
    _, _, p = _fullbox_payload(data, i, hdr, size)
    count = _u32(data, p)
    q = p + 4
    out = []
    for _ in range(count):
        out.append((_u32(data, q), _u32(data, q + 4), _u32(data, q + 8)))
        q += 12
    return out


def _expand_chunk_samples(
    stsc: list[tuple[int, int, int]],
    chunk_offsets: list[int],
    sizes: list[int],
) -> list[tuple[int, int, int]]:
    """Return (file_offset, size, sample_desc_index) per sample."""
    if not chunk_offsets or not sizes:
        return []
    out: list[tuple[int, int, int]] = []
    sample_i = 0
    n_chunks = len(chunk_offsets)
    entries = stsc or [(1, 1, 1)]
    for ei, (first, spc, sdi) in enumerate(entries):
        next_first = entries[ei + 1][0] if ei + 1 < len(entries) else n_chunks + 1
        for chunk_no in range(first, min(next_first, n_chunks + 1)):
            off = chunk_offsets[chunk_no - 1]
            for _ in range(spc):
                if sample_i >= len(sizes):
                    return out
                sz = sizes[sample_i]
                out.append((off, sz, sdi))
                off += sz
                sample_i += 1
    return out


def parse_stsd(data: bytes, i: int, hdr: int, size: int) -> list[dict]:
    _, _, p = _fullbox_payload(data, i, hdr, size)
    count = _u32(data, p)
    q = p + 4
    end = i + size
    entries: list[dict] = []
    for _ in range(count):
        if q + 8 > end:
            break
        esize = _u32(data, q)
        codec = data[q + 4 : q + 8]
        entry_end = q + esize
        nal_len = None
        psets: list[bytes] = []
        avcc_at = data.find(b"avcC", q, entry_end)
        if avcc_at >= 4:
            bi = avcc_at - 4
            bsz = _u32(data, bi)
            if 8 <= bsz <= entry_end - bi:
                payload = data[avcc_at + 4 : bi + bsz]
                nal_len, psets = parse_avcc(payload)
        entries.append({"codec": codec, "nal_length_size": nal_len, "parameter_sets": psets})
        q = entry_end
    return entries


def _hdlr_type(data: bytes, mdia_start: int, mdia_end: int) -> bytes:
    hit = find_child(data, mdia_start, mdia_end, b"hdlr")
    if hit is None:
        return b""
    i, hdr, size = hit
    # FullBox + predefined (4) + handler (4)
    p = i + hdr + 4 + 4
    if p + 4 > i + size:
        return b""
    return data[p : p + 4]


def _trak_id(data: bytes, trak_start: int, trak_end: int) -> int:
    hit = find_child(data, trak_start, trak_end, b"tkhd")
    if hit is None:
        return 0
    i, hdr, size = hit
    ver, _, p = _fullbox_payload(data, i, hdr, size)
    # v0/v1: skip creation+modification then track_id
    skip = 16 if ver == 1 else 8
    return _u32(data, p + skip)


def _parse_stbl(
    data: bytes,
    stbl_start: int,
    stbl_end: int,
    *,
    track_id: int,
    handler: bytes,
) -> tuple[list[Mp4Sample], list[bytes]]:
    stsd_b = find_child(data, stbl_start, stbl_end, b"stsd")
    stsz_b = find_child(data, stbl_start, stbl_end, b"stsz")
    stsc_b = find_child(data, stbl_start, stbl_end, b"stsc")
    stco_b = find_child(data, stbl_start, stbl_end, b"stco")
    co64_b = find_child(data, stbl_start, stbl_end, b"co64")
    if not (stsd_b and stsz_b and stsc_b and (stco_b or co64_b)):
        return [], []
    entries = parse_stsd(data, *stsd_b)
    sizes = parse_stsz(data, *stsz_b)
    stsc = parse_stsc(data, *stsc_b)
    if co64_b:
        offs = parse_stco(data, *co64_b, wide=True)
    else:
        offs = parse_stco(data, *stco_b, wide=False)
    triples = _expand_chunk_samples(stsc, offs, sizes)
    samples: list[Mp4Sample] = []
    psets_all: list[bytes] = []
    default_entry = entries[0] if entries else {"codec": b"", "nal_length_size": None, "parameter_sets": []}
    for off, sz, sdi in triples:
        desc = entries[sdi - 1] if 1 <= sdi <= len(entries) else default_entry
        if desc["parameter_sets"] and not psets_all:
            psets_all = list(desc["parameter_sets"])
        samples.append(
            Mp4Sample(
                track_id=track_id,
                handler=handler,
                offset=off,
                size=sz,
                codec=desc["codec"],
                nal_length_size=desc["nal_length_size"],
                parameter_sets=tuple(desc["parameter_sets"]),
            )
        )
    return samples, psets_all


def _parse_trex(data: bytes, moov_start: int, moov_end: int) -> dict[int, dict]:
    defaults: dict[int, dict] = {}
    mvex = find_child(data, moov_start, moov_end, b"mvex")
    if mvex is None:
        return defaults
    i, hdr, size = mvex
    for ti, thdr, tsize, typ in iter_boxes(data, i + hdr, i + size):
        if typ != b"trex":
            continue
        _, _, p = _fullbox_payload(data, ti, thdr, tsize)
        track_id = _u32(data, p)
        defaults[track_id] = {
            "desc": _u32(data, p + 4),
            "duration": _u32(data, p + 8),
            "size": _u32(data, p + 12),
            "flags": _u32(data, p + 16),
        }
    return defaults


def _parse_moof_samples(
    data: bytes,
    moof_i: int,
    moof_hdr: int,
    moof_size: int,
    *,
    tracks: dict[int, dict],
    trex: dict[int, dict],
) -> list[Mp4Sample]:
    samples: list[Mp4Sample] = []
    moof_end = moof_i + moof_size
    for i, hdr, size, typ in iter_boxes(data, moof_i + moof_hdr, moof_end):
        if typ != b"traf":
            continue
        tfhd = find_child(data, i + hdr, i + size, b"tfhd")
        trun = find_child(data, i + hdr, i + size, b"trun")
        if tfhd is None or trun is None:
            continue
        _, flags, p = _fullbox_payload(data, *tfhd)
        track_id = _u32(data, p)
        p += 4
        base = moof_i if (flags & 0x020000) else 0
        if flags & 0x000001:
            base = int.from_bytes(data[p : p + 8], "big")
            p += 8
        if flags & 0x000002:
            p += 4
        default_duration = trex.get(track_id, {}).get("duration", 0)
        default_size = trex.get(track_id, {}).get("size", 0)
        if flags & 0x000008:
            default_duration = _u32(data, p)
            p += 4
        if flags & 0x000010:
            default_size = _u32(data, p)
            p += 4
        tver, tflags, tp = _fullbox_payload(data, *trun)
        sample_count = _u32(data, tp)
        tp += 4
        data_offset = 0
        if tflags & 0x000001:
            data_offset = int.from_bytes(data[tp : tp + 4], "big", signed=True)
            tp += 4
        if tflags & 0x000004:
            tp += 4
        cursor = base + data_offset
        info = tracks.get(track_id, {"handler": b"", "codec": b"", "nal_length_size": None, "parameter_sets": ()})
        for _ in range(sample_count):
            if tflags & 0x000100:
                tp += 4
            sz = default_size
            if tflags & 0x000200:
                sz = _u32(data, tp)
                tp += 4
            if tflags & 0x000400:
                tp += 4
            if tflags & 0x000800:
                tp += 8 if tver == 1 else 4
            samples.append(
                Mp4Sample(
                    track_id=track_id,
                    handler=info["handler"],
                    offset=cursor,
                    size=sz,
                    codec=info["codec"],
                    nal_length_size=info["nal_length_size"],
                    parameter_sets=info["parameter_sets"],
                )
            )
            cursor += sz
    return samples


def _moov_track_info(data: bytes, moov_start: int, moov_end: int) -> dict[int, dict]:
    info: dict[int, dict] = {}
    for i, hdr, size, typ in iter_boxes(data, moov_start, moov_end):
        if typ != b"trak":
            continue
        tid = _trak_id(data, i + hdr, i + size)
        mdia = find_child(data, i + hdr, i + size, b"mdia")
        handler = b""
        codec = b""
        nal_len = None
        psets: tuple[bytes, ...] = ()
        if mdia:
            mi, mhdr, msize = mdia
            handler = _hdlr_type(data, mi + mhdr, mi + msize)
            minf = find_child(data, mi + mhdr, mi + msize, b"minf")
            if minf:
                ni, nh, ns = minf
                stbl = find_child(data, ni + nh, ni + ns, b"stbl")
                if stbl:
                    si, sh, ss = stbl
                    stsd = find_child(data, si + sh, si + ss, b"stsd")
                    if stsd:
                        entries = parse_stsd(data, *stsd)
                        if entries:
                            codec = entries[0]["codec"]
                            nal_len = entries[0]["nal_length_size"]
                            psets = tuple(entries[0]["parameter_sets"])
        info[tid] = {
            "handler": handler,
            "codec": codec,
            "nal_length_size": nal_len,
            "parameter_sets": psets,
        }
    return info


def parse_mp4(data: bytes) -> Mp4Movie:
    movie = Mp4Movie()
    moov = None
    moofs: list[tuple[int, int, int]] = []
    for i, hdr, size, typ in iter_boxes(data, 0, len(data)):
        if typ == b"moov":
            moov = (i, hdr, size)
        elif typ == b"moof":
            moofs.append((i, hdr, size))
    if moov is None:
        return movie
    mi, mhdr, msize = moov
    moov_end = mi + msize
    tracks = _moov_track_info(data, mi + mhdr, moov_end)
    for psets in (t["parameter_sets"] for t in tracks.values()):
        for nal in psets:
            if nal not in movie.parameter_sets:
                movie.parameter_sets.append(nal)
    for i, hdr, size, typ in iter_boxes(data, mi + mhdr, moov_end):
        if typ != b"trak":
            continue
        tid = _trak_id(data, i + hdr, i + size)
        mdia = find_child(data, i + hdr, i + size, b"mdia")
        if mdia is None:
            continue
        di, dhdr, dsize = mdia
        handler = _hdlr_type(data, di + dhdr, di + dsize)
        minf = find_child(data, di + dhdr, di + dsize, b"minf")
        if minf is None:
            continue
        ni, nh, ns = minf
        stbl = find_child(data, ni + nh, ni + ns, b"stbl")
        if stbl is None:
            continue
        samples, psets = _parse_stbl(data, stbl[0] + stbl[1], stbl[0] + stbl[2], track_id=tid, handler=handler)
        movie.samples.extend(samples)
        for nal in psets:
            if nal not in movie.parameter_sets:
                movie.parameter_sets.append(nal)
    if moofs:
        trex = _parse_trex(data, mi + mhdr, moov_end)
        for fo in moofs:
            movie.samples.extend(_parse_moof_samples(data, *fo, tracks=tracks, trex=trex))
    movie.samples.sort(key=lambda s: s.offset)
    seen: set[int] = set()
    uniq: list[Mp4Sample] = []
    for sample in movie.samples:
        if sample.offset in seen or sample.size <= 0:
            continue
        seen.add(sample.offset)
        uniq.append(sample)
    movie.samples = uniq
    return movie


def sample_bytes(data: bytes, sample: Mp4Sample) -> bytes:
    return data[sample.offset : sample.offset + sample.size]


def leftover_bytes(data: bytes, ranges: list[tuple[int, int]]) -> bytes:
    if not ranges:
        return data
    ordered = sorted(ranges)
    parts: list[bytes] = []
    cursor = 0
    for start, size in ordered:
        end = start + size
        if start > cursor:
            parts.append(data[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(data):
        parts.append(data[cursor:])
    return b"".join(parts)
