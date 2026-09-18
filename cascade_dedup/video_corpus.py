"""Synthetic remux clones of one H.264+AAC encode (ffmpeg, lossless -c copy)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def encode_clip(path: Path, *, duration: float, width: int, height: int, fps: int, seed: int) -> None:
    # testsrc2 is more spatially busy; seed via color/tone so clip B differs.
    freq = 220 + (seed % 8) * 55
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size={width}x{height}:rate={fps}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            "-x264-params",
            f"keyint={fps}:min-keyint={fps}:scenecut=0:repeat-headers=0",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-b:a",
            "32k",
            str(path),
        ]
    )


def remux(src: Path, dst: Path, extra: list[str]) -> None:
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-c", "copy", *extra, str(dst)])


def remux_family(src: Path, dest_dir: Path, stem: str) -> dict[str, bytes]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "mp4": dest_dir / f"{stem}.mp4",
        "faststart": dest_dir / f"{stem}.faststart.mp4",
        "mkv": dest_dir / f"{stem}.mkv",
        "ts": dest_dir / f"{stem}.ts",
        "frag": dest_dir / f"{stem}.frag.mp4",
    }
    paths["mp4"].write_bytes(src.read_bytes())
    remux(src, paths["faststart"], ["-movflags", "+faststart"])
    remux(src, paths["mkv"], [])
    remux(src, paths["ts"], [])
    remux(src, paths["frag"], ["-movflags", "frag_keyframe+empty_moov+default_base_moof"])
    return {name: path.read_bytes() for name, path in paths.items()}


def transcode(src: Path, dst: Path) -> bytes:
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "32",
            "-c:a",
            "aac",
            "-b:a",
            "32k",
            str(dst),
        ]
    )
    return dst.read_bytes()


def build_remux_corpus(
    *,
    duration: float = 4.0,
    width: int = 320,
    height: int = 240,
    fps: int = 12,
) -> dict[str, dict[str, bytes]]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to build the remux corpus")
    out: dict[str, dict[str, bytes]] = {}
    with tempfile.TemporaryDirectory(prefix="cascade-video-") as tmp:
        root = Path(tmp)
        for seed, name in ((1, "clip_a"), (7, "clip_b")):
            src = root / f"{name}.src.mp4"
            encode_clip(src, duration=duration, width=width, height=height, fps=fps, seed=seed)
            family = remux_family(src, root / name, name)
            if name == "clip_a":
                family["transcode"] = transcode(src, root / f"{name}.re.mp4")
            out[name] = family
    return out


def remux_blobs(corpus: dict[str, dict[str, bytes]], *, include_transcode: bool = False) -> list[bytes]:
    blobs: list[bytes] = []
    for _clip, files in corpus.items():
        for kind, data in files.items():
            if kind == "transcode" and not include_transcode:
                continue
            blobs.append(data)
    return blobs
