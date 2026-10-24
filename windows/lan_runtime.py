"""Version data, a fresh read-only game session, and the one-shot LAN service."""

from __future__ import annotations
import ctypes as c
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct

import pefile
import psutil
import pymem
import pymem.memory
import pymem.process

ROOT = Path(__file__).resolve().parent
MENU = re.compile(rb"127\.0\.0\.1:(\d{1,5})/webui/index\.html\?guid=(\d{1,20})")


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def fingerprint(header):
    if header[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", header, 60)[0]
    if not 64 <= pe <= 2048 or header[pe : pe + 4] != b"PE\0\0":
        return None
    return (
        struct.unpack_from("<H", header, pe + 4)[0],
        struct.unpack_from("<I", header, pe + 8)[0],
        struct.unpack_from("<I", header, pe + 80)[0],
    )


@dataclass(frozen=True)
class GameProfile:
    data: dict

    @classmethod
    def for_executable(cls, image):
        with pefile.PE(str(image), fast_load=True) as pe:
            identity = (
                pe.FILE_HEADER.Machine,
                pe.FILE_HEADER.TimeDateStamp,
                pe.OPTIONAL_HEADER.SizeOfImage,
            )
        sha = hashlib.sha256(image.read_bytes()).hexdigest()
        matches = []
        for path in (ROOT / "profiles").glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["schema_version"] != 1 or data["bridge_protocol"] != 2:
                raise ValueError(
                    "Unsupported profile/bridge data version: " + path.name
                )
            if (
                tuple(data["fingerprint"]) == identity
                and data["executable_sha256"] == sha
            ):
                matches.append(data)
        if len(matches) != 1:
            raise ValueError(
                "No unique verified game identity in the local LAN profiles: "
                + str(identity)
            )
        return cls(matches[0])


class GameSession:
    def __init__(self, pid):
        self.pid = pid
        self.process = psutil.Process(pid)
        self.created = self.process.create_time()
        self.image = Path(self.process.exe())
        self.profile = GameProfile.for_executable(self.image)
        self.memory = pymem.Pymem()
        self.memory.process_id = pid
        self.memory.process_handle = pymem.process.open(
            pid, debug=False, process_access=0x410
        )
        if not self.memory.process_handle:
            raise OSError("Opening game for read-only inspection failed")
        try:
            module = next(
                m
                for m in pymem.process.enum_process_module(self.memory.process_handle)
                if m.name.lower() == "warcraft iii.exe"
            )
            self.base = module.lpBaseOfDll
            if fingerprint(self.memory.read_bytes(self.base, 4096)) != tuple(
                self.profile.data["fingerprint"]
            ):
                raise ValueError("Loaded PE identity differs from executable/profile")
            self.alias, self.port, self.guid = self._mapping_and_menu()
        except BaseException:
            self.close()
            raise

    def check_identity(self):
        fresh = psutil.Process(
            self.pid
        )  # Process.create_time()/exe() cache values on an instance.
        if fresh.create_time() != self.created or Path(fresh.exe()) != self.image:
            raise ValueError("Game session changed; reopen it before another operation")

    def _mapping_and_menu(self):
        self.check_identity()
        aliases, menus = [], set()
        listening = {
            row.laddr.port
            for row in self.process.net_connections(kind="tcp")
            if row.status == "LISTEN"
        }
        cursor = 0
        while cursor < 0x7FFFFFFFFFFF:
            try:
                info = pymem.memory.virtual_query(self.memory.process_handle, cursor)
            except (OSError, pymem.exception.WinAPIError):
                break
            start, size = int(info.BaseAddress or 0), info.RegionSize
            if not size:
                break
            cursor = start + size
            if info.State != 0x1000 or info.Protect & 0x101:
                continue
            if info.Type == 0x40000 and size == self.profile.data["fingerprint"][2]:
                if fingerprint(self.memory.read_bytes(start, 4096)) == tuple(
                    self.profile.data["fingerprint"]
                ):
                    aliases.append(start)
            if info.Type == 0x20000 and size <= 16 * 1024 * 1024:
                try:
                    blob = self.memory.read_bytes(start, size)
                except (OSError, pymem.exception.MemoryReadError):
                    continue
                menus.update(
                    (int(m[1]), m[2].decode())
                    for m in MENU.finditer(blob)
                    if int(m[1]) in listening
                )
        if len(aliases) != 1 or not menus:
            raise ValueError(
                "Expected one matching shared image and a live menu endpoint"
            )
        port, guid = max(menus, key=lambda row: len(row[1]))
        return aliases[0], port, guid

    def debugger_present(self):
        kernel = c.WinDLL("kernel32", use_last_error=True)
        fn = kernel.CheckRemoteDebuggerPresent
        fn.argtypes = [c.c_void_p, c.POINTER(c.c_int)]
        present = c.c_int()
        if not fn(self.memory.process_handle, c.byref(present)):
            raise c.WinError(c.get_last_error())
        return bool(present.value)

    def close(self):
        if self.memory.process_handle:
            self.memory.close_process()
