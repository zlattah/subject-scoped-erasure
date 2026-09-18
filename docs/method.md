# Method: canonical access-unit hashing

Backup of **lossless remuxes** should not hash the file. It should hash **normalized compressed frames**.

## Pipeline

1. **Sniff** the container (ISO BMFF / Matroska / MPEG-TS).
2. **Extract packets as stored** (MP4 samples, MKV SimpleBlocks, TS PES payloads).
3. **Canonicalize**
   - H.264: split AVCC (length-prefixed) or Annex-B (start codes) into NALs; drop AUD (type 9) and filler (type 12); keep VCL, SPS, PPS, SEI.
   - Include SPS/PPS from `avcC` / MKV `CodecPrivate` so in-band TS sets can match out-of-band MP4 sets.
   - AAC: strip ADTS headers; MP4/MKV raw frames stay as-is.
4. **Fingerprint** each unit (blake2s-128) into an exact chunk store.
5. **Leftover** bytes (headers, `moov`, EBML, TS packing) are stored per file. They are not expected to match across containers.

Modes in `ingest_video_files`:

| Mode | Hash |
|---|---|
| `fastcdc` | Gear FastCDC on the whole file (Xia et al., ATC 2016) |
| `container-sample` | Extracted packets **with framing still on** (Dewakar-style) |
| `canonical-au` | This method |

## What a stored file is

Unique media = unique canonical units.  
Unique with wrappers = that plus leftover container bytes.  
The prototype counts leftover size for a fair “cover the files” comparison; it does **not** yet rebuild a bit-identical original file.

## Limits (by design)

- Transcode → new NALs → no match.
- Same MP4 with only `moov` moved and identical `mdat` → container-sample already shares; canonical-au adds little.
- HEVC/AV1 not the first-class path (H.264 + AAC is the claim).
