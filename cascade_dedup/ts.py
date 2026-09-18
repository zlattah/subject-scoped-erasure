"""MPEG-TS PES extraction (H.264 Annex-B / AAC ADTS)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TsPacket:
    pid: int
    stream_type: int
    payload: bytes


def _pid(packet: bytes) -> int:
    return ((packet[1] & 0x1F) << 8) | packet[2]


def _payload(packet: bytes) -> bytes | None:
    if packet[0] != 0x47:
        return None
    adapt = (packet[3] >> 4) & 0x03
    start = 4
    if adapt in (2, 3):
        alen = packet[4]
        start = 5 + alen
        if start > 188:
            return None
    if adapt in (1, 3):
        return packet[start:188]
    return None


def _parse_pmt(payload: bytes) -> dict[int, int]:
    """Map PID -> stream_type from a PMT section payload (pointer_field stripped)."""
    if len(payload) < 12:
        return {}
    if payload[0] != 0x02:
        return {}
    section_len = ((payload[1] & 0x0F) << 8) | payload[2]
    prog_info_len = ((payload[10] & 0x0F) << 8) | payload[11]
    i = 12 + prog_info_len
    end = min(len(payload), 3 + section_len - 4)
    out: dict[int, int] = {}
    while i + 5 <= end:
        stype = payload[i]
        epid = ((payload[i + 1] & 0x1F) << 8) | payload[i + 2]
        es_len = ((payload[i + 3] & 0x0F) << 8) | payload[i + 4]
        out[epid] = stype
        i += 5 + es_len
    return out


def _pes_payload(pes: bytes) -> bytes:
    if len(pes) < 9 or pes[:3] != b"\x00\x00\x01":
        return pes
    hdr_len = pes[8]
    start = 9 + hdr_len
    if start > len(pes):
        return b""
    return pes[start:]


def parse_ts(data: bytes) -> list[TsPacket]:
    if len(data) < 188:
        return []
    # Align to sync
    sync = 0
    while sync + 188 <= len(data) and data[sync] != 0x47:
        sync += 1
    pmt_pids: set[int] = set()
    types: dict[int, int] = {}
    pes_buf: dict[int, bytearray] = {}
    packets: list[TsPacket] = []

    def flush(pid: int) -> None:
        buf = pes_buf.get(pid)
        if not buf:
            return
        payload = _pes_payload(bytes(buf))
        if payload:
            packets.append(TsPacket(pid=pid, stream_type=types.get(pid, 0), payload=payload))
        pes_buf[pid] = bytearray()

    for off in range(sync, len(data) - 187, 188):
        pkt = data[off : off + 188]
        if pkt[0] != 0x47:
            continue
        pid = _pid(pkt)
        if pid in (0x1FFF,):
            continue
        payload = _payload(pkt)
        if payload is None:
            continue
        pusi = bool(pkt[1] & 0x40)
        if pid == 0 and pusi:
            # PAT
            section = payload[1:] if payload else b""
            if len(section) >= 16 and section[0] == 0x00:
                slen = ((section[1] & 0x0F) << 8) | section[2]
                i = 8
                end = min(len(section), 3 + slen - 4)
                while i + 4 <= end:
                    prog = int.from_bytes(section[i : i + 2], "big")
                    ppid = ((section[i + 2] & 0x1F) << 8) | section[i + 3]
                    if prog != 0:
                        pmt_pids.add(ppid)
                    i += 4
            continue
        if pid in pmt_pids and pusi:
            section = payload[1:] if payload else b""
            types.update(_parse_pmt(section))
            continue
        if pid not in types and pid not in pes_buf:
            # still capture unknown PIDs after PAT (PMT may come late)
            pass
        if pusi:
            flush(pid)
            pes_buf[pid] = bytearray(payload)
        else:
            if pid in pes_buf:
                pes_buf[pid].extend(payload)
    for pid in list(pes_buf):
        flush(pid)
    return packets
