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
python3 -m cascade_dedup video-bench --duration 4 --width 320 --height 240 --fps 12
```

A transcode (`--include-transcode`) must **not** share units with the original encode.

Results are filled in after measurement. A loss versus `container-sample` on cross-format clones means the canonicalizer did not land.
