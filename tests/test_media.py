from cascade_dedup.media import (
    filter_nals,
    looks_like_adts,
    parse_avcc,
    split_adts,
    split_annexb,
    split_avcc,
    video_units,
)


def test_split_avcc_and_annexb_same_nals() -> None:
    nals = [bytes([0x65, 1, 2, 3, 4]), bytes([0x41, 9, 9])]
    avcc = b"".join(len(n).to_bytes(4, "big") + n for n in nals)
    annex = b"".join(b"\x00\x00\x00\x01" + n for n in nals)
    assert split_avcc(avcc, 4) == nals
    assert split_annexb(annex) == nals


def test_drop_aud_keeps_vcl() -> None:
    aud = bytes([0x09, 0xF0])
    vcl = bytes([0x65, 0, 1, 2])
    kept, dropped = filter_nals([aud, vcl])
    assert dropped == 1
    assert kept == [vcl]


def test_video_units_match_across_framing() -> None:
    vcl = bytes([0x65, 7, 7, 7])
    avcc = (4).to_bytes(4, "big") + vcl
    annex = b"\x00\x00\x01" + vcl
    a, _ = video_units(avcc, length_size=4)
    b, _ = video_units(annex, length_size=None)
    assert [u.payload for u in a] == [u.payload for u in b] == [vcl]


def test_parse_avcc_length_and_sps() -> None:
    sps = bytes([0x67, 0x42, 0xC0, 0x0A])
    pps = bytes([0x68, 0xCE, 0x38, 0x80])
    rec = bytearray(b"\x01\x42\xc0\x0a\xff")
    rec.append(0xE1)
    rec.extend(len(sps).to_bytes(2, "big") + sps)
    rec.append(1)
    rec.extend(len(pps).to_bytes(2, "big") + pps)
    length, nals = parse_avcc(bytes(rec))
    assert length == 4
    assert nals == [sps, pps]


def test_adts_strip() -> None:
    payload = bytes(range(16))
    # 7-byte ADTS, protection absent (bit1 of byte1 = 1), frame_len = 7+16=23
    hdr = bytearray(7)
    hdr[0] = 0xFF
    hdr[1] = 0xF1
    frame_len = 23
    hdr[3] = (frame_len >> 11) & 0x03
    hdr[4] = (frame_len >> 3) & 0xFF
    hdr[5] = (frame_len & 0x07) << 5
    pkt = bytes(hdr) + payload
    assert looks_like_adts(pkt)
    assert split_adts(pkt) == [payload]
