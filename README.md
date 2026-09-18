# Canonical access-unit dedup for lossless video remuxes

Research prototype for **one idea**: backup should hash **normalized compressed frames**, not file bytes, when the same encode is stored in several containers.

This is **not** a self-hosted cloud, **not** a new FastCDC/SeqCDC family, and **not** RAD-CDC. The thesis claim is:

> Two files that are lossless remuxes of the same H.264/AAC encode (MP4, faststart MP4, MKV, MPEG-TS, fragmented MP4) should share stored media. Opaque CDC does not; **canonical access-unit hashing** does.

- Method: [docs/method.md](docs/method.md)
- Related work (honest): [docs/related-work.md](docs/related-work.md)
- Evaluation: [docs/evaluation.md](docs/evaluation.md)

---

## The scenario (only this)

A **lossless remux / re-export** keeps the same compressed packets and changes the box: `ffmpeg -c copy`, faststart, “save as MKV,” HLS/CMAF fragments of the same encode, some cloud/messenger re-wraps.

It does **not** help a **transcode** (new resolution, CRF, burned-in subs). Those packets are different.

---

## Core idea (one paragraph)

Parse the container, pull video and audio packets, strip length prefixes / Annex-B start codes / ADTS headers, drop AUD and filler NALs, hash the remaining NALs and AAC frames (plus SPS/PPS from `avcC`). Store each unique unit once. Each file keeps container leftover (headers, index) plus a list of unit ids. Compare against **FastCDC** (opaque bytes) and **container-sample** (Dewakar-style samples/blocks/PES as stored).

---

## What is actually new

**Dewakar et al., HotStorage 2015** already hash MP4/3GPP **samples in that file**. They left **across file formats** as future work. **mkvdup** (software, not a paper) already matches elementary-stream packets between an MKV and a DVD/Blu-ray ISO.

This project’s idea is that leftover: **peer remuxes** (no master disc), with an explicit **canonical** unit (framing stripped) and a backup-style comparison to FastCDC and in-file samples. Do not claim a new rolling hash or visual copy detection (ViDeDup, Maze, Content ID).

---

## Objectives

1. Specify canonical access-unit identity for H.264 + AAC in MP4 / fMP4 / MKV / MPEG-TS.
2. Implement it, plus FastCDC and Dewakar-style container-sample baselines.
3. Measure unique bytes and ratio on lossless remux clones; show transcodes do **not** match.
4. (Next) Repeat on real remuxes (phone re-export, `-c copy` rips, HLS vs MP4 of one encode) and a restore path that rebuilds a playable file.
5. Write the report so a loss on transcode or same-`mdat` MP4 clones is expected, not hidden.

---

## Scope

**In scope**

- Format-aware **lossless** video/audio unit hashing for remux-stable backup.
- Baselines: FastCDC, in-container samples.
- Synthetic ffmpeg remux corpus now; real remux corpora next.
- Honest related work: Dewakar 2015, mkvdup, ViDeDup (different problem).

**Out of scope**

- Self-hosted cloud, iPhone clients, “parallel vs serial hashing.”
- A new CDC algorithm (SeqCDC knobs, RAD-CDC, learned skip/Tmax).
- Near-duplicate **after decode** (re-encodes, crops, overlays).
- Competing with YouTube Content ID.
- mkvdup’s disc-rip FUSE product (cite it; do not reimplement ISO matching as the thesis).

---

## Stack (prototype)

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Fingerprints | blake2s-128 |
| Demux | In-repo MP4 / MKV / MPEG-TS parsers (no extra pip deps) |
| Corpus | ffmpeg `libx264` + `aac`, then `-c copy` remuxes |
| Eval | `python -m cascade_dedup bench` |

---

## Success criteria

- On lossless remux clones, canonical-au unique bytes **beat FastCDC** by a large factor and **beat container-sample** by matching MKV/TS to MP4 NALs.
- On a transcode of the same clip, overlap is ~none (the method is remux identity, not perceptual).
- The write-up names Dewakar’s future work and mkvdup so the contribution is not overclaimed.
- Negative results are allowed.

---

## Suggested schedule

| Phase | Focus |
|---|---|
| A | Freeze the claim and related work (Dewakar, mkvdup, FastCDC) |
| B | Parsers + canonical units + remux corpus (this repo) |
| C | Bench vs FastCDC and container-sample; transcode negative test |
| D | Real remux dataset + restore-to-playable |
| E | Thesis write-up: scenario, method, limits |

---

## Run

ffmpeg with `libx264` and `aac` is required for the remux corpus.

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m cascade_dedup bench
```

On two 4 s lavfi clips × five remuxes (848.5 KiB logical): canonical-au unique **152.7 KiB** (ratio **5.556**) vs FastCDC **699.8 KiB** (1.212) vs container-sample **250.0 KiB** (3.394). Tables: [docs/evaluation.md](docs/evaluation.md).
