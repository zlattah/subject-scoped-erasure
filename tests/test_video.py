import shutil

import pytest

from cascade_dedup.mp4 import parse_mp4, sample_bytes
from cascade_dedup.video import extract_media, ingest_video_files
from cascade_dedup.video_corpus import build_remux_corpus, remux_blobs

ffmpeg = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(ffmpeg is None, reason="ffmpeg required")


def test_mp4_samples_cover_mdat() -> None:
    corpus = build_remux_corpus(duration=1.0, width=160, height=120, fps=10)
    data = corpus["clip_a"]["mp4"]
    movie = parse_mp4(data)
    assert movie.samples
    total = sum(s.size for s in movie.samples)
    assert total > 0
    for s in movie.samples:
        raw = sample_bytes(data, s)
        assert len(raw) == s.size


def test_canonical_shares_across_remux() -> None:
    corpus = build_remux_corpus(duration=1.0, width=160, height=120, fps=10)
    kinds = ("mp4", "faststart", "mkv", "ts", "frag")
    sets = []
    for kind in kinds:
        extracted = extract_media(corpus["clip_a"][kind], canonical=True)
        assert extracted.units
        sets.append(set(extracted.units))
    shared = sets[0]
    for other in sets[1:]:
        shared &= other
    # VCL/AAC identity should survive remux for a large majority of units.
    assert len(shared) >= max(1, int(0.5 * min(len(s) for s in sets)))


def test_ingest_canonical_beats_fastcdc_on_remuxes() -> None:
    corpus = build_remux_corpus(duration=1.5, width=160, height=120, fps=10)
    blobs = remux_blobs(corpus, include_transcode=False)
    _, fast = ingest_video_files(blobs, mode="fastcdc")
    _, dewakar = ingest_video_files(blobs, mode="container-sample")
    _, canon = ingest_video_files(blobs, mode="canonical-au")
    assert canon.unique_bytes < fast.unique_bytes
    assert canon.dedup_ratio > fast.dedup_ratio
    assert dewakar.units > 0
    assert canon.units > 0
