# Evaluation

ffmpeg with libx264 and aac is required.

```bash
python3 -m pytest
python3 -m cascade_dedup bench --duration 4 --width 320 --height 240 --fps 12
```

Corpus: encode two `testsrc` clips (different sine tones), then lossless remux each to MP4, faststart MP4, MKV, MPEG-TS, fragmented MP4 (`ffmpeg -c copy`). Ten files, 848.5 KiB logical.

`python3 -m pytest`: **15 passed** (canonical units, remux ingest, FastCDC baseline).

| mode | unique KiB | media KiB | leftover KiB | ratio |
|---|---:|---:|---:|---:|
| FastCDC | 699.8 | 699.8 | 0 | 1.212 |
| container-sample (Dewakar-style) | 250.0 | 191.6 | 58.4 | 3.394 |
| **canonical-au** | **152.7** | **94.3** | 58.4 | **5.556** |

On this remux set:

- vs FastCDC: unique 699.8 → 152.7 KiB (**4.6×** less; ratio 1.212 → 5.556).
- vs container-sample: unique 250.0 → 152.7 KiB (**1.6×**). ISO-BMFF clones already share under Dewakar; the extra win is MKV/TS after canonicalize.

A CRF 32 re-encode shares **1 / 111** canonical units with the source on a 2 s clip. `--include-transcode` dilutes ratio to 4.514. The method does not treat transcodes as duplicates.

Laptop-scale lavfi only. Bit-identical restore is not implemented. Not evaluated against mkvdup disc rips. Next: real remuxes (phone re-export, `-c copy` rips, HLS vs MP4).
