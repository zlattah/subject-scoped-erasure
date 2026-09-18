"""Format-aware video ingest: Dewakar samples vs canonical access units."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from cascade_dedup.chunking import FastCDC, fingerprint
from cascade_dedup.media import audio_units, parse_avcc, video_units
from cascade_dedup.mkv import parse_mkv
from cascade_dedup.mp4 import leftover_bytes, parse_mp4, sample_bytes
from cascade_dedup.store import ChunkStore
from cascade_dedup.ts import parse_ts


VIDEO_MODES = ("fastcdc", "container-sample", "canonical-au")


@dataclass
class Extracted:
    units: list[bytes]
    leftover: bytes
    dropped_aud: int
    n_param_sets: int
    container: str


def sniff_container(data: bytes) -> str:
    if len(data) >= 8 and data[4:8] in {b"ftyp", b"moof", b"mdat", b"free", b"moov"}:
        return "mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "mkv"
    if b"ftyp" in data[:64]:
        return "mp4"
    # MPEG-TS sync
    if len(data) >= 188 and data[0] == 0x47:
        return "ts"
    for i in range(0, min(188, max(0, len(data) - 188))):
        if data[i] == 0x47 and i + 188 < len(data) and data[i + 188] == 0x47:
            return "ts"
    return "opaque"


def _units_from_video_sample(sample: bytes, length_size: int | None, canonical: bool) -> tuple[list[bytes], int]:
    if not canonical:
        return ([sample] if sample else [], 0)
    aus, dropped = video_units(sample, length_size=length_size)
    return [au.payload for au in aus], dropped


def _units_from_audio_sample(sample: bytes, canonical: bool) -> list[bytes]:
    if not canonical:
        return [sample] if sample else []
    return [au.payload for au in audio_units(sample)]


def extract_mp4(data: bytes, *, canonical: bool) -> Extracted:
    movie = parse_mp4(data)
    units: list[bytes] = []
    dropped = 0
    ranges: list[tuple[int, int]] = []
    if canonical:
        for nal in movie.parameter_sets:
            units.append(nal)
    for sample in movie.samples:
        raw = sample_bytes(data, sample)
        ranges.append((sample.offset, sample.size))
        if sample.handler == b"soun" or sample.codec in {b"mp4a", b"mp4a"}:
            units.extend(_units_from_audio_sample(raw, canonical))
        else:
            u, d = _units_from_video_sample(raw, sample.nal_length_size, canonical)
            units.extend(u)
            dropped += d
    leftover = leftover_bytes(data, ranges)
    return Extracted(units, leftover, dropped, len(movie.parameter_sets), "mp4")


def _sized_unique_leftover(data: bytes, leftover_len: int) -> bytes:
    """Container overhead of leftover_len bytes that does not collide across files."""
    if leftover_len <= 0:
        return b""
    ident = fingerprint(data)
    return (ident * ((leftover_len // len(ident)) + 1))[:leftover_len]


def extract_ts(data: bytes, *, canonical: bool) -> Extracted:
    from cascade_dedup.media import looks_like_adts, looks_like_annexb

    packets = parse_ts(data)
    units: list[bytes] = []
    dropped = 0
    covered = 0
    for pkt in packets:
        covered += len(pkt.payload)
        st = pkt.stream_type
        is_video = st in {0x1B, 0x20, 0x24} or looks_like_annexb(pkt.payload)
        is_audio = st in {0x0F, 0x11, 0x03, 0x04} or looks_like_adts(pkt.payload)
        if is_video:
            if canonical:
                u, d = _units_from_video_sample(pkt.payload, None, True)
                units.extend(u)
                dropped += d
            else:
                units.append(pkt.payload)
        elif is_audio:
            units.extend(_units_from_audio_sample(pkt.payload, canonical) if canonical else [pkt.payload])
        elif pkt.payload:
            units.append(pkt.payload)
    leftover = _sized_unique_leftover(data, max(len(data) - covered, 0))
    return Extracted(units, leftover, dropped, 0, "ts")


def extract_mkv(data: bytes, *, canonical: bool) -> Extracted:
    movie = parse_mkv(data)
    units: list[bytes] = []
    dropped = 0
    if canonical:
        units.extend(movie.parameter_sets)
    for block in movie.blocks:
        codec = block.codec
        raw = block.payload
        if codec.startswith(b"V_MPEG4/ISO/AVC"):
            length_size, _ = parse_avcc(block.codec_private)
            u, d = _units_from_video_sample(raw, length_size if canonical else length_size, canonical)
            if canonical:
                units.extend(u)
                dropped += d
            else:
                units.append(raw)
        elif codec.startswith(b"V_MPEGH/ISO/HEVC") or codec.startswith(b"V_MPEG4/ISO/HEVC"):
            if canonical:
                u, d = _units_from_video_sample(raw, 4, True)
                units.extend(u)
                dropped += d
            else:
                units.append(raw)
        elif codec.startswith(b"A_"):
            units.extend(_units_from_audio_sample(raw, canonical) if canonical else [raw])
        else:
            units.append(raw)
    leftover = leftover_bytes(data, movie.ranges)
    return Extracted(units, leftover, dropped, len(movie.parameter_sets), "mkv")


def extract_media(data: bytes, *, canonical: bool) -> Extracted:
    kind = sniff_container(data)
    if kind == "mp4":
        return extract_mp4(data, canonical=canonical)
    if kind == "ts":
        return extract_ts(data, canonical=canonical)
    if kind == "mkv":
        return extract_mkv(data, canonical=canonical)
    return Extracted([data], b"", 0, 0, "opaque")


@dataclass
class VideoIngestStats:
    name: str
    logical_bytes: int = 0
    unique_bytes: int = 0
    media_unique_bytes: int = 0
    leftover_bytes: int = 0
    units: int = 0
    exact_hits: int = 0
    dropped_aud: int = 0
    elapsed_s: float = 0.0

    @property
    def dedup_ratio(self) -> float:
        if self.unique_bytes == 0:
            return float("inf") if self.logical_bytes else 1.0
        return self.logical_bytes / self.unique_bytes

    def as_row(self) -> dict[str, float | int | str]:
        return {
            "name": self.name,
            "logical_KiB": round(self.logical_bytes / 1024, 1),
            "unique_KiB": round(self.unique_bytes / 1024, 1),
            "media_KiB": round(self.media_unique_bytes / 1024, 1),
            "leftover_KiB": round(self.leftover_bytes / 1024, 1),
            "dedup_ratio": round(self.dedup_ratio, 3),
            "units": self.units,
            "exact_hits": self.exact_hits,
            "dropped_aud": self.dropped_aud,
            "MB_s": round((self.logical_bytes / (1024 * 1024)) / self.elapsed_s, 2) if self.elapsed_s else 0.0,
        }


def ingest_video_files(blobs: list[bytes], *, mode: str) -> tuple[ChunkStore, VideoIngestStats]:
    if mode not in VIDEO_MODES:
        raise ValueError(f"unknown video mode {mode!r}")
    store = ChunkStore()
    stats = VideoIngestStats(name=mode)
    t0 = perf_counter()
    media_store = ChunkStore()
    leftover_acc = 0
    if mode == "fastcdc":
        cdc = FastCDC()
        for blob in blobs:
            stats.logical_bytes += len(blob)
            prev = 0
            for end in cdc.cuts(blob):
                chunk = blob[prev:end]
                stats.units += 1
                fp = fingerprint(chunk)
                if store.lookup(fp) is not None:
                    stats.exact_hits += 1
                else:
                    store.put_unique(chunk, fp=fp)
                prev = end
        stats.unique_bytes = store.unique_bytes
        stats.media_unique_bytes = store.unique_bytes
        stats.elapsed_s = perf_counter() - t0
        return store, stats

    canonical = mode == "canonical-au"
    for blob in blobs:
        stats.logical_bytes += len(blob)
        extracted = extract_media(blob, canonical=canonical)
        stats.dropped_aud += extracted.dropped_aud
        for unit in extracted.units:
            stats.units += 1
            fp = fingerprint(unit)
            if media_store.lookup(fp) is not None:
                stats.exact_hits += 1
            else:
                media_store.put_unique(unit, fp=fp)
            if store.lookup(fp) is None:
                store.put_unique(unit, fp=fp)
        if extracted.leftover:
            leftover_acc += len(extracted.leftover)
            lfp = fingerprint(extracted.leftover)
            if store.lookup(lfp) is None:
                store.put_unique(extracted.leftover, fp=lfp)
    stats.media_unique_bytes = media_store.unique_bytes
    stats.leftover_bytes = leftover_acc
    stats.unique_bytes = store.unique_bytes
    stats.elapsed_s = perf_counter() - t0
    return store, stats
