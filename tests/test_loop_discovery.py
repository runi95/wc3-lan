import sys
from pathlib import Path
import struct
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))
from loop_discovery import decode_game_info


def packet(name=b"Local test", password=b"", stat=b"\x01\x03\x05", tail=None):
    tail = struct.pack("<5IH", 24, 0x100000, 1, 23, 100, 6112) if tail is None else tail
    value = (
        b"\xf7\x30\0\0PX3W"
        + struct.pack("<III", 10200, 3, 42)
        + name
        + b"\0"
        + password
        + b"\0"
        + stat
        + b"\0"
        + tail
    )
    return value[:2] + struct.pack("<H", len(value)) + value[4:]


def test_native_layout_and_creation_timestamp():
    row = decode_game_info(packet(), "127.0.0.1", received_at=1700000000)
    native = row.native()
    assert list(native.native_tags) == [3, 42, 1, 23, 1699999900]
    assert bytes(native.information) == b"Local test".ljust(32, b"\0") + bytes(
        16
    ) + b"\x01\x03\x05".ljust(320, b"\0") + struct.pack("<II", 24, 0x100000)
    assert bytes(native.endpoint) == b"\x02\0\x17\xe0\x7f\0\0\x01" + bytes(8)


@pytest.mark.parametrize(
    "value",
    [
        packet(name=b""),
        packet(name=b"x" * 32),
        packet(name=b"\xff"),
        packet(password=b"x" * 16),
        packet(stat=b""),
        packet(stat=b"\x02"),
        packet(stat=b"\x01" * 320),
        packet(tail=struct.pack("<5IH", 29, 1, 1, 23, 100, 6112)),
        packet(tail=struct.pack("<5IH", 24, 1, 1, 25, 100, 6112)),
        packet(tail=struct.pack("<5IH", 24, 1, 1, 23, 100, 0)),
        packet(tail=b"x" * 23),
        packet()[:-1],
        b"\xf7\x30",
    ],
)
def test_malformed_datagrams_never_produce_native_listing(value):
    with pytest.raises((ValueError, UnicodeError)):
        decode_game_info(value, "127.0.0.1")
