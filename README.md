# Canonical access-unit dedup for lossless video remuxes

A laptop-scale experiment: backup of remuxed H.264/AAC video should share **the same compressed frames**, even when those frames sit in different containers.

- Method: [docs/method.md](docs/method.md)
- Related work: [docs/related-work.md](docs/related-work.md)
- Evaluation: [docs/evaluation.md](docs/evaluation.md)

---

## Problem

Deduplicating video files by hashing **opaque bytes** (CDC such as FastCDC) or **packets as stored in one container** (MP4 samples, Matroska blocks, MPEG-TS PES) fails on a common, lossless change: **remux**.

A remux (`ffmpeg -c copy`, faststart, “save as MKV,” HLS/CMAF fragments of one encode) **does not re-encode**. The H.264 NALs and AAC frames stay the same. Only the box changes: ISO BMFF, faststart MP4, fragmented MP4, Matroska, MPEG-TS.

That box change is enough to break byte-oriented backup:

| What stays the same | What changes |
|---|---|
| Compressed pictures (VCL NALs) and AAC frames | File headers (`moov`, EBML, PAT/PMT) |
| | NAL framing: MP4 **AVCC length prefixes** vs MPEG-TS **Annex-B start codes** |
| | AAC wrapping: raw frames in MP4/MKV vs **ADTS** in MPEG-TS |
| | Where SPS/PPS live: `avcC` / CodecPrivate vs in-band |
| | Optional AUD (type 9) and filler (type 12) NALs muxers insert or drop |

So two remuxes of one encode are **the same media** and **different files**. FastCDC almost never matches them. Hashing in-container samples can share ISO-BMFF clones that keep the same `mdat` layout, but still misses MKV and MPEG-TS, because those packets are the same NALs with different wrappers.

**This experiment’s improvement:** parse each container, strip that wrapper, and hash **canonical access units** (framing-free NALs and AAC frames). Remuxes of one encode then share stored media. A transcode (new encode) does not — those packets are different, and the method is not meant to catch them.

---

## Method (this experiment)

1. Sniff MP4 / fMP4 / MKV / MPEG-TS.
2. Extract video and audio packets.
3. Canonicalize: split AVCC or Annex-B; drop AUD and filler; keep VCL, SPS, PPS, SEI; add SPS/PPS from `avcC` when they are out-of-band; strip ADTS from AAC.
4. Fingerprint each unit (blake2s-128) into an exact chunk store. Store leftover container bytes per file.

Baselines in the same ingest path: **FastCDC** on the whole file, and **container-sample** (packets hashed as stored, Dewakar-style).

---

## Related work (for this problem only)

**Dewakar et al., HotStorage 2015** hash MP4/3GPP samples *inside one file*. They named matching **across file formats** as future work. **mkvdup** matches elementary-stream packets between an MKV and a DVD/Blu-ray ISO (software, not a paper).

This prototype is that leftover on **peer remuxes** (no master disc): an explicit canonical unit, and a backup-style comparison to FastCDC and in-file samples. It is not a new rolling hash and not perceptual copy detection.

---

## Objectives

1. Specify canonical access-unit identity for H.264 + AAC in MP4 / fMP4 / MKV / MPEG-TS.
2. Implement it plus FastCDC and container-sample baselines.
3. Measure unique bytes and ratio on lossless remux clones; show transcodes do not match.
4. (Next) Repeat on real remuxes and a restore path that rebuilds a playable file.

---

## Scope

**In**

- Format-aware lossless unit hashing so remuxes of one encode share storage.
- Baselines: FastCDC, in-container samples.
- Synthetic ffmpeg remux corpus now; real remuxes next.

**Out**

- Near-duplicates after decode (re-encodes, crops, overlays).
- HEVC/AV1 as a first-class path (claim is H.264 + AAC).
- Bit-identical restore of the original container (not implemented yet).

---

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Fingerprints | blake2s-128 |
| Demux | In-repo MP4 / MKV / MPEG-TS parsers |
| Corpus | ffmpeg `libx264` + `aac`, then `-c copy` remuxes |
| Eval | `python -m cascade_dedup bench` |

---

## Success criteria

- On lossless remux clones, canonical-au unique bytes beat FastCDC by a large factor, and beat container-sample by matching MKV/TS to MP4 NALs.
- On a transcode of the same clip, overlap is ~none.
- Write-up names Dewakar’s cross-format future work and mkvdup.

---

## Schedule

| Phase | Focus |
|---|---|
| A | Claim and related work (Dewakar, mkvdup, FastCDC) |
| B | Parsers + canonical units + remux corpus (this repo) |
| C | Bench vs FastCDC and container-sample; transcode negative test |
| D | Real remux dataset + restore-to-playable |
| E | Write-up: scenario, method, limits |

---

## Run

ffmpeg with `libx264` and `aac` is required for the remux corpus.

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m cascade_dedup bench
```

On two 4 s lavfi clips × five remuxes (848.5 KiB logical): canonical-au unique **152.7 KiB** (ratio **5.556**) vs FastCDC **699.8 KiB** (1.212) vs container-sample **250.0 KiB** (3.394). Tables: [docs/evaluation.md](docs/evaluation.md).
