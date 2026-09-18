# Canonical access-unit video dedup (remux clones)

Opaque CDC hashes **file bytes**. A lossless remux (`ffmpeg -c copy`) of the same H.264/AAC encode into MP4 / faststart MP4 / MKV / MPEG-TS / fragmented MP4 is a new byte stream, so FastCDC stores it again.

This prototype compares three ingest modes on that remux family:

| Mode | What is hashed |
|---|---|
| `fastcdc` | Gear FastCDC cuts of the whole file (existing baseline) |
| `container-sample` | Dewakar-style: MP4 samples / MKV blocks / TS PES payloads **as stored** plus container leftover |
| `canonical-au` | H.264 NALs and AAC frames after stripping length prefixes, Annex-B start codes, and ADTS headers. AUD/filler NALs are dropped. SPS/PPS from `avcC` are included. |

This is Dewakar’s missing cross-format experiment, not a new CDC family. mkvdup already hashes packets against a disc image; here the files are **peer remuxes** with no master ISO.

```bash
python3 -m pytest
python3 -m cascade_dedup video-bench --duration 4 --width 320 --height 240 --fps 12
```

## Results

`python3 -m pytest`: **37 passed**.

Corpus: two `testsrc` clips × five lossless remuxes (10 files, 848.5 KiB logical). Encode once with libx264+AAC, then `ffmpeg -c copy` to MP4, faststart MP4, MKV, MPEG-TS, fragmented MP4.

| mode | unique KiB | media KiB | leftover KiB | ratio |
|---|---:|---:|---:|---:|
| FastCDC | 699.8 | 699.8 | 0 | 1.212 |
| container-sample (Dewakar-style) | 250.0 | 191.6 | 58.4 | 3.394 |
| **canonical-au** | **152.7** | **94.3** | 58.4 | **5.556** |

On this remux set the results **are a significant measured improvement**:

- vs FastCDC: unique bytes 699.8 → 152.7 KiB (**4.6×** less stored; ratio 1.212 → 5.556)
- vs container-sample: unique 250.0 → 152.7 KiB (**1.6×**); media unique roughly halves because MKV/TS packets match MP4 NALs after canonicalize. ISO-BMFF clones already share under Dewakar; the extra win is cross-container.

A re-encode (`--include-transcode`, CRF 32) shares **1 / 111** canonical units with the source on a 2 s clip. Adding that file dilutes ratio to 4.514. This method does not treat transcodes as duplicates.

Laptop-scale lavfi clips only. Bit-identical file restore is not implemented (stored size includes leftover wrappers). Not evaluated against mkvdup disc rips.
