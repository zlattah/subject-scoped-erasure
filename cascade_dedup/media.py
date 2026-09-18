"""Canonical H.264 NAL / AAC frame identity for remux-stable hashing.

This is not Dewakar sample hashing and not mkvdup. A unit is a NAL or AAC
frame with container length prefixes / start codes / ADTS headers removed.
AUD (9) and filler (12) are dropped; SEI is kept so we do not over-claim.
"""

from __future__ import annotations

from dataclasses import dataclass

# H.264 nal_unit_type (nal_unit_header & 0x1F)
NAL_SEI = 6
NAL_SPS = 7
NAL_PPS = 8
NAL_AUD = 9
NAL_FILLER = 12

DROP_NAL_TYPES = {NAL_AUD, NAL_FILLER}


@dataclass(frozen=True)
class AccessUnit:
    kind: str  # "vnal" | "anal" | "aac" | "other"
    payload: bytes


def split_avcc(sample: bytes, length_size: int) -> list[bytes]:
    if length_size not in {1, 2, 3, 4} or not sample:
        return [sample] if sample else []
    nals: list[bytes] = []
    i = 0
    n = len(sample)
    while i + length_size <= n:
        size = int.from_bytes(sample[i : i + length_size], "big")
        i += length_size
        if size < 0 or i + size > n:
            break
        if size:
            nals.append(sample[i : i + size])
        i += size
    return nals


def split_annexb(data: bytes) -> list[bytes]:
    if not data:
        return []
    starts: list[tuple[int, int]] = []
    i = 0
    n = len(data)
    while i + 3 <= n:
        if data[i] == 0 and data[i + 1] == 0:
            if data[i + 2] == 1:
                starts.append((i, 3))
                i += 3
                continue
            if i + 3 < n and data[i + 2] == 0 and data[i + 3] == 1:
                starts.append((i, 4))
                i += 4
                continue
        i += 1
    if not starts:
        return [data]
    nals: list[bytes] = []
    for k, (pos, sc) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else n
        nal = data[pos + sc : end]
        if nal:
            nals.append(nal)
    return nals


def looks_like_annexb(data: bytes) -> bool:
    if len(data) < 4:
        return False
    return data[:3] == b"\x00\x00\x01" or data[:4] == b"\x00\x00\x00\x01"


def looks_like_adts(data: bytes) -> bool:
    return len(data) >= 7 and data[0] == 0xFF and (data[1] & 0xF0) == 0xF0


def split_adts(data: bytes) -> list[bytes]:
    """Return raw AAC payloads with ADTS headers stripped."""
    frames: list[bytes] = []
    i = 0
    n = len(data)
    while i + 7 <= n:
        if data[i] != 0xFF or (data[i + 1] & 0xF0) != 0xF0:
            break
        hdr_len = 9 if (data[i + 1] & 0x01) == 0 else 7
        frame_len = ((data[i + 3] & 0x03) << 11) | (data[i + 4] << 3) | (data[i + 5] >> 5)
        if frame_len < hdr_len or i + frame_len > n:
            break
        payload = data[i + hdr_len : i + frame_len]
        if payload:
            frames.append(payload)
        i += frame_len
    if not frames and data:
        return [data]
    return frames


def parse_avcc(avcc: bytes) -> tuple[int, list[bytes]]:
    """Return (nal_length_size, parameter-set NALs) from an AVCDecoderConfigurationRecord."""
    if len(avcc) < 7:
        return 4, []
    length_size = (avcc[4] & 0x03) + 1
    nals: list[bytes] = []
    i = 5
    n_sps = avcc[i] & 0x1F
    i += 1
    for _ in range(n_sps):
        if i + 2 > len(avcc):
            break
        ln = int.from_bytes(avcc[i : i + 2], "big")
        i += 2
        nals.append(avcc[i : i + ln])
        i += ln
    if i >= len(avcc):
        return length_size, nals
    n_pps = avcc[i]
    i += 1
    for _ in range(n_pps):
        if i + 2 > len(avcc):
            break
        ln = int.from_bytes(avcc[i : i + 2], "big")
        i += 2
        nals.append(avcc[i : i + ln])
        i += ln
    return length_size, nals


def h264_nal_type(nal: bytes) -> int:
    if not nal:
        return 0
    return nal[0] & 0x1F


def filter_nals(nals: list[bytes]) -> tuple[list[bytes], int]:
    kept: list[bytes] = []
    dropped = 0
    for nal in nals:
        if h264_nal_type(nal) in DROP_NAL_TYPES:
            dropped += 1
            continue
        kept.append(nal)
    return kept, dropped


def video_units(sample: bytes, *, length_size: int | None) -> tuple[list[AccessUnit], int]:
    if not sample:
        return [], 0
    if length_size is not None:
        nals = split_avcc(sample, length_size)
    elif looks_like_annexb(sample):
        nals = split_annexb(sample)
    else:
        nals = [sample]
    kept, dropped = filter_nals(nals)
    return [AccessUnit("vnal", nal) for nal in kept], dropped


def audio_units(sample: bytes) -> list[AccessUnit]:
    if not sample:
        return []
    if looks_like_adts(sample):
        return [AccessUnit("aac", frame) for frame in split_adts(sample)]
    return [AccessUnit("aac", sample)]
