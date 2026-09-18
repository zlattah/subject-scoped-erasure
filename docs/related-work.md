# Related work

The research idea is **canonical access-unit identity for peer remuxes**. Cite these; do not claim they do not exist.

## Storage / format-aware (same family)

**Dewakar et al., HotStorage 2015.** *Storage Efficiency Opportunities and Analysis for Video Repositories.*  
Parse ISO BMFF (MP4/3GPP), hash **samples or sequences as stored in that file**, plus metadata. Up to ~45% savings vs naive video-as-opaque; content-aware beat Rabin CDC by ~10%. They **did not** evaluate MP4 vs MKV vs MPEG-TS. Their future work: *deduplication across file formats and different codecs*.  
This repo’s `container-sample` is that method (also applied to MKV blocks and TS PES). `canonical-au` is the cross-format leftover plus framing strip.

**US patent 2015/0227436.** Sample/sequence chunking of ISO media `mdat` via `moov`. Same idea as Dewakar, not a paper.

**mkvdup** ([stuckj/mkvdup](https://github.com/stuckj/mkvdup)). Open-source tool, **not a paper**. Hashes elementary-stream packets so an MKV rip is stored as a map onto a DVD/Blu-ray ISO (example: 3.4 GB MKV → ~50 MB). Closest **packet-matching implementation**. Different setting: one disc is canonical; this project matches **peer remuxes** with no ISO.

**CMAF / HLS+DASH packaging.** Industry: one fragmented-MP4 object, two manifests. Not a backup algorithm for arbitrary WhatsApp/iCloud remuxes.

**FastCDC** (Xia et al., ATC 2016). Opaque byte CDC. Baseline that must lose on remuxes if the claim is true.

## Different problem (do not mix)

**ViDeDup (HotStorage 2011).** Application-aware video dedup **after decode**; different encodes of the same clip can count as duplicates (lossy).

**Maze (ACM MM 2022), TCSVT 2024 localization, MLT-Dedup (2026), FIVR-200K.** Near-duplicate / copy detection with embeddings. Re-encodes, crops, overlays. Not lossless packet identity.

**AA-Dedupe / AppDedupe.** Split the index by file type; still byte-chunk inside each type.

## One-sentence positioning

Dewakar: in-file MP4 samples. mkvdup: packets vs a disc. ViDeDup/Maze: look-alike videos. **This project: same packets, different boxes, no master file.**
