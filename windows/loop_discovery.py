"""Strict W3GS LAN advertisement decoding for the native LOOP listing ABI."""

from dataclasses import dataclass
import ipaddress
import socket
import struct
import time
from loop_protocol import Listing

SEARCH = b"\xf7\x2f\x10\0PX3W" + struct.pack("<II", 10200, 0)


@dataclass(frozen=True)
class Advertisement:
    name: str
    address: str
    port: int
    host_counter: int
    entry_key: int
    total_slots: int
    flags: int
    parameter: int
    open_slots: int
    uptime: int
    received_at: float
    information: bytes

    def native(self, now=None):
        row = Listing()
        now = self.received_at if now is None else now
        # The native ABI takes creation time, not elapsed uptime.
        row.native_tags[:] = [
            self.host_counter,
            self.entry_key,
            self.parameter,
            self.open_slots,
            min(0xFFFFFFFF, max(0, int(now) - self.uptime)),
        ]
        row.endpoint.family = 2
        row.endpoint.port = socket.htons(self.port)
        row.endpoint.address = struct.unpack("<I", socket.inet_aton(self.address))[0]
        row.information[:] = self.information
        return row


def decode_game_info(packet, address, *, received_at=None):
    address = str(ipaddress.IPv4Address(address))
    if len(packet) < 46 or packet[:2] != b"\xf7\x30":
        raise ValueError("Not a W3GS GAMEINFO")
    if struct.unpack_from("<H", packet, 2)[0] != len(packet):
        raise ValueError("GAMEINFO length differs")
    if packet[4:12] != b"PX3W" + struct.pack("<I", 10200):
        raise ValueError("Unsupported product/protocol")
    host, key = struct.unpack_from("<II", packet, 12)
    fields = []
    cursor = 20
    for limit in (32, 16, 320):
        end = packet.find(b"\0", cursor)
        if end < 0 or end - cursor >= limit:
            raise ValueError("GAMEINFO string exceeds native bounds")
        value = packet[cursor:end]
        if limit != 16 and not value:
            raise ValueError("Empty GAMEINFO name/stat string")
        if limit == 32:
            value.decode("utf-8", errors="strict")
        if limit == 320 and any(not byte & 1 for byte in value):
            raise ValueError("Invalid encoded stat string")
        fields.append(value)
        cursor = end + 1
    if len(packet) - cursor != 22:
        raise ValueError("GAMEINFO tail size differs")
    total, flags, parameter, opened, uptime, port = struct.unpack_from(
        "<5IH", packet, cursor
    )
    if not port or not 1 <= total <= 28 or opened > total:
        raise ValueError("GAMEINFO slots/port are invalid")
    # Native 376 bytes end with total slots and flags, before the unknown parameter.
    info = (
        b"".join(
            value.ljust(limit, b"\0") for value, limit in zip(fields, (32, 16, 320))
        )
        + packet[cursor : cursor + 8]
    )
    return Advertisement(
        fields[0].decode("utf-8"),
        address,
        port,
        host,
        key,
        total,
        flags,
        parameter,
        opened,
        uptime,
        time.time() if received_at is None else received_at,
        info,
    )


def discover(host="127.0.0.1", port=16000, timeout=3):
    # Explicit destinations only; no automatic Internet lookup or scanning.
    destination = str(ipaddress.IPv4Address(host))
    found = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind(("0.0.0.0", 0))
        client.sendto(SEARCH, (destination, port))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            client.settimeout(max(0.01, deadline - time.monotonic()))
            try:
                packet, peer = client.recvfrom(2048)
            except socket.timeout:
                break
            if peer[0] != destination:
                continue
            try:
                row = decode_game_info(packet, peer[0])
            except (ValueError, UnicodeError):
                continue
            found[(row.address, row.port, row.host_counter, row.entry_key)] = row
    return list(found.values())
