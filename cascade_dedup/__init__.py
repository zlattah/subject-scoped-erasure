"""Subject-scoped erasure in a deduplicated immutable backup."""

from cascade_dedup.chunking import FastCDC
from cascade_dedup.erase import EraseStore, FileClass, MixedPolicy, WrapMode
from cascade_dedup.store import ChunkStore
from cascade_dedup.video import ingest_video_files
from cascade_dedup.video_corpus import build_remux_corpus

__all__ = [
    "ChunkStore",
    "EraseStore",
    "FastCDC",
    "FileClass",
    "MixedPolicy",
    "WrapMode",
    "build_remux_corpus",
    "ingest_video_files",
]
