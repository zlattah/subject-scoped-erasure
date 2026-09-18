"""Canonical access-unit dedup for lossless H.264/AAC remuxes."""

from cascade_dedup.chunking import FastCDC
from cascade_dedup.store import ChunkStore
from cascade_dedup.video import ingest_video_files
from cascade_dedup.video_corpus import build_remux_corpus

__all__ = [
    "ChunkStore",
    "FastCDC",
    "build_remux_corpus",
    "ingest_video_files",
]
