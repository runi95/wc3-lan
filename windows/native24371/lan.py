"""Windows LAN bridge for Warcraft III 3.0.1.24371.

Only menu coordination runs here; native game callbacks own all LAN sockets.
"""

import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import psutil
import pymem
import pymem.process
import re
import struct
import pymem.memory
import pefile
import ipaddress
import socket
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import time
from urllib.parse import urlsplit, parse_qs
from websockets.sync.client import connect


K = c.WinDLL("kernel32", use_last_error=True)
N = c.WinDLL("ntdll", use_last_error=True)
P = c.c_void_p


def api(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype = result
    fn.argtypes = args
    return fn


api(K, "VirtualAllocEx", P, P, P, c.c_size_t, w.DWORD, w.DWORD)
api(K, "VirtualProtectEx", w.BOOL, P, P, c.c_size_t, w.DWORD, c.POINTER(w.DWORD))
api(K, "FlushInstructionCache", w.BOOL, P, P, c.c_size_t)
api(K, "OpenThread", P, w.DWORD, w.BOOL, w.DWORD)
api(K, "SuspendThread", w.DWORD, P)
api(K, "ResumeThread", w.DWORD, P)
api(K, "CloseHandle", w.BOOL, P)
api(K, "GetCurrentProcessId", w.DWORD)
api(K, "GetCurrentThreadId", w.DWORD)
api(K, "GetModuleHandleExW", w.BOOL, w.DWORD, P, c.POINTER(P))
api(K, "GetModuleFileNameW", w.DWORD, P, w.LPWSTR, w.DWORD)


class Memory:
    def __init__(self, pid):
        self.pid = pid
        self.created = psutil.Process(pid).create_time()
        self.memory = pymem.Pymem()
        self.memory.process_id = pid
        self.memory.process_handle = pymem.process.open(pid, debug=False, process_access=0x438)
        if not self.memory.process_handle:
            raise c.WinError(c.get_last_error())
        self.handle = self.memory.process_handle
        self.base = None
        self.report = {}

    def read(self, address, size):
        return self.memory.read_bytes(address, size)

    def write(self, address, data):
        self.memory.write_bytes(address, data, len(data))

    def remote_api(self, lib, name):
        fn = getattr(lib, name)
        address = c.cast(fn, P).value
        owner = P()
        if not K.GetModuleHandleExW(6, address, c.byref(owner)):
            raise c.WinError(c.get_last_error())
        path = c.create_unicode_buffer(32768)
        if not K.GetModuleFileNameW(owner, path, len(path)):
            raise c.WinError(c.get_last_error())
        modules = [
            m
            for m in pymem.process.enum_process_module(self.handle)
            if m.name.lower() == Path(path.value).name.lower()
        ]
        if len(modules) != 1:
            raise ValueError("System module mapping differs")
        return modules[0].lpBaseOfDll + address - owner.value

    def swap(self, slot, expected, replacement):
        if slot % 8:
            raise ValueError("Unaligned data slot")
        suspended = {}
        old = w.DWORD()
        changed = False
        try:
            for attempt in range(4):
                threads = {t.id for t in psutil.Process(self.pid).threads()}
                fresh = threads - suspended.keys()
                if not fresh:
                    break
                for tid in fresh:
                    h = K.OpenThread(2, False, tid)
                    if not h:
                        raise c.WinError(c.get_last_error())
                    if K.SuspendThread(h) == 0xFFFFFFFF:
                        K.CloseHandle(h)
                        raise c.WinError(c.get_last_error())
                    suspended[tid] = h
            else:
                raise RuntimeError("Threads did not stabilize; no slot changed")
            if psutil.Process(self.pid).create_time() != self.created:
                raise ValueError("Process identity changed")
            actual = int.from_bytes(self.read(slot, 8), "little")
            if actual != expected:
                raise ValueError("Method slot changed; refusing to overwrite another owner")
            if not K.VirtualProtectEx(self.handle, slot, 8, 4, c.byref(old)):
                raise c.WinError(c.get_last_error())
            changed = True
            self.write(slot, replacement.to_bytes(8, "little"))
            if int.from_bytes(self.read(slot, 8), "little") != replacement:
                raise RuntimeError("Slot readback differs")
        finally:
            if changed:
                ignored = w.DWORD()
                if not K.VirtualProtectEx(self.handle, slot, 8, old.value, c.byref(ignored)):
                    self.report["protection_restore_failed"] = c.get_last_error()
            for h in reversed(list(suspended.values())):
                if K.ResumeThread(h) == 0xFFFFFFFF:
                    self.report["thread_resume_failed"] = c.get_last_error()
                K.CloseHandle(h)

        if self.report:
            raise RuntimeError("Process state restoration failed: " + repr(self.report))

    def close(self):
        self.memory.close_process()


class LanGame(c.Structure):
    _fields_ = [
        ("address", c.c_ubyte * 16),
        ("info", c.c_ubyte * 376),
        *[(n, c.c_uint32) for n in ("counter", "key", "product", "version", "current", "total")],
    ]


class ProfileStream(c.Structure):
    _fields_ = [
        ("packet", c.c_ubyte * 512),
        ("names", (c.c_ubyte * 64) * 32),
        ("pending", c.c_ubyte * 32),
        *[(n, c.c_uint32) for n in ("used", "total", "remaining", "published", "errors", "own_id")],
    ]


class Host(c.Structure):
    _fields_ = [
        ("magic", c.c_uint64),
        ("size", c.c_uint32),
        ("pid", c.c_uint32),
        *[(n, c.c_int32) for n in ("command", "state", "active", "unwind")],
        *[
            (n, c.c_uint32)
            for n in ("error", "thread", "bind_calls", "unbind_calls", "connect_calls", "port")
        ],
        ("expected_vtable", c.c_uint64),
        ("original", c.c_uint64 * 51),
        *[
            (n, c.c_uint64)
            for n in (
                "get_pid",
                "get_tid",
                "get_context",
                "initialize",
                "shutdown",
                "listen",
                "enable",
                "connect",
                "add_table",
                "table",
                "image_base",
            )
        ],
        *[(n, c.c_uint32) for n in ("table_count", "started", "old_mode", "local_calls")],
        ("provider", c.c_uint64),
        ("session", c.c_uint64),
        ("counts", c.c_uint64),
        ("baseline", c.c_uint32 * 6),
        ("baseline_ready", c.c_uint32),
        *[(n, c.c_uint64) for n in ("connect_callback", "listen_callback", "local_connect", "add_listing")],
        *[(n, c.c_uint64) for n in ("udp_create", "udp_send", "udp_vtable", "udp_handle")],
        *[(n, c.c_uint32) for n in ("udp_port", "udp_requested", "udp_stage", "udp_error")],
        ("udp_closed", c.c_uint32),
        *[(n, c.c_uint32) for n in ("udp_last", "discovery", "discovery_product", "discovery_version")],
        ("discovery_lock", c.c_int32),
        ("poll_lock", c.c_int32),
        *[
            (n, c.c_uint32)
            for n in ("advert_valid", "advert_length", "searches", "queued", "dropped", "listed")
        ],
        ("advert_packet", c.c_ubyte * 432),
        ("advert_game", LanGame),
        ("queue", LanGame * 16),
        ("peers", LanGame * 16),
        ("peer_count", c.c_uint32),
        ("refresh", c.c_int32),
        ("broadcast_count", c.c_uint32),
        ("broadcasts", c.c_uint32 * 16),
        *[(n, c.c_uint64) for n in ("create_timer", "delete_timer", "timer")],
        ("timer_started", c.c_uint32),
        ("timer_deleted", c.c_uint32),
        *[
            (n, c.c_uint64)
            for n in ("create_event", "wait_event", "close_handle", "get_error", "timer_event")
        ],
        ("timer_stopping", c.c_uint32),
        ("remove_listing", c.c_uint64),
        ("get_tick", c.c_uint64),
        ("seen", c.c_uint32 * 16),
        ("expired", c.c_uint32),
        ("profile_enabled", c.c_uint32),
        ("profile_local", c.c_uint32),
        ("profile_handle", c.c_uint64),
        ("own_name", c.c_ubyte * 64),
        ("profile", ProfileStream),
        ("get_manager", c.c_uint64),
        ("get_name", c.c_uint64),
    ]


EXPECTED_EXE = "eb39ab298ae1d84d307aba4d400f2a7dbda2900a46964bb28aeba592f45fa97a"
EXPECTED_LOADER = "ef88b6554036661f5974986b95912b08c8a7042795177f539a67cc4e710d23d7"
IDENTITY = (34404, 1792442231, 236904448)
COUNTS = 0xDE91BA8
MENU = re.compile(rb"127\.0\.0\.1:(\d{1,5})/webui/index\.html\?guid=(\d{1,20})")


def fingerprint(blob):
    if blob[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", blob, 60)[0]
    if not 64 <= pe <= 2048 or blob[pe : pe + 4] != b"PE\0\0":
        return None
    return (
        struct.unpack_from("<H", blob, pe + 4)[0],
        struct.unpack_from("<I", blob, pe + 8)[0],
        struct.unpack_from("<I", blob, pe + 80)[0],
    )


def locate(probe):
    cursor = 0
    aliases = []
    menus = set()
    while cursor < 0x7FFFFFFFFFFF:
        try:
            info = pymem.memory.virtual_query(probe.handle, cursor)
        except (OSError, pymem.exception.WinAPIError):
            break
        start = int(info.BaseAddress or 0)
        size = info.RegionSize
        if not size:
            break
        cursor = start + size
        if info.State != 0x1000 or info.Protect & 0x101:
            continue
        if info.Type == 0x40000 and size == IDENTITY[2]:
            if fingerprint(probe.read(start, 4096)) == IDENTITY:
                aliases.append(start)
        if info.Type == 0x20000 and size <= 16 * 1024 * 1024:
            try:
                blob = probe.read(start, size)
            except (OSError, pymem.exception.MemoryReadError):
                continue
            menus.update((int(m[1]), m[2].decode()) for m in MENU.finditer(blob))
    if len(aliases) != 1 or not menus:
        raise ValueError("Expected one matching shared image and a menu endpoint")
    return aliases[0], max(menus, key=lambda row: len(row[1]))


SIGNATURES = {
    0x198530: "40534883ec",
    0x1F018D0: "e9ebdeffff",
    0x1F01680: "e98bcbffff",
    0x1F01BC0: "0fb7c1488b",
    0x1F01BE0: "4c8bdc4155",
    0x1F01B80: "4883ec4844",
    0x1F011E0: "4883ec384c",
    0x1497F80: "48895c2418",
    0x1F01DF0: "4883ec384c",
    0x1F01D70: "48895c2408",
    0x14984C0: "48895c2410",
    0x111E420: "488b0559cf",
    0x111E5F0: "48895c2408",
}

ROOT = Path(__file__).resolve().parent
DLL = ROOT / "lan.dll"
MAGIC = 0x574333484F535431
LOOP = 0x4C4F4F50
TCPN = 0x5443504E
HOOKS = {
    4: "host_poll",
    15: "host_connect",
    16: "host_bind",
    17: "host_unbind",
    18: "host_advertise",
    19: "host_update",
    20: "host_unadvertise",
    49: "host_identity",
}


def summary(cfg):
    fields = (
        "command",
        "state",
        "active",
        "unwind",
        "error",
        "bind_calls",
        "unbind_calls",
        "connect_calls",
        "local_calls",
        "port",
        "started",
        "old_mode",
        "provider",
        "session",
        "timer",
        "timer_deleted",
        "udp_stage",
        "udp_error",
        "udp_handle",
        "udp_closed",
        "listed",
        "expired",
    )
    return {
        **{n: getattr(cfg, n) for n in fields},
        "profiles": {
            "name": bytes(cfg.own_name).split(b"\0", 1)[0].decode("utf-8", errors="replace"),
            "published": cfg.profile.published,
            "errors": cfg.profile.errors,
        },
    }


class NativeAdapter:
    def __init__(self, pid, game_base):
        self.memory = Memory(pid)
        self.game_base = game_base
        self.pe = pefile.PE(str(DLL))
        self.image = bytearray(self.pe.get_memory_mapped_image())
        self.exports = {e.name.decode(): e.address for e in self.pe.DIRECTORY_ENTRY_EXPORT.symbols}
        assert not hasattr(self.pe, "DIRECTORY_ENTRY_IMPORT")
        assert not self.pe.OPTIONAL_HEADER.DATA_DIRECTORY[5].Size
        size = int.from_bytes(self.pe.get_data(self.exports["host_config_size"], 4), "little")
        if size != c.sizeof(Host):
            raise ValueError("Native adapter ABI differs")
        self.cfg = Host()
        self.cfg.magic = MAGIC
        self.cfg.size = size
        self.cfg.pid = pid
        self.base = None
        self.published = []

    def read(self):
        return Host.from_buffer_copy(
            self.memory.read(self.base + self.exports["host_config"], c.sizeof(Host))
        )

    def prepare(self):
        p = self.memory
        base = self.game_base
        cfg = self.cfg
        cfg.counts = base + 0xDE91BA8
        cfg.expected_vtable = base + 0x287A238
        values = p.read(cfg.expected_vtable, 51 * 8)
        for i in range(51):
            cfg.original[i] = int.from_bytes(values[i * 8 : i * 8 + 8], "little")
        for i, rva in (
            (4, 0x149AE70),
            (15, 0x149AB80),
            (16, 0x149AC40),
            (17, 0x149ADB0),
            (18, 0x149AAE0),
            (19, 0x149AB00),
            (20, 0x149AAF0),
            (49, 0x149A880),
        ):
            if cfg.original[i] != base + rva:
                raise ValueError("Unexpected original method " + str(i))
        broadcasts = {0xFFFFFFFF}
        statuses = psutil.net_if_stats()
        for name, addresses in psutil.net_if_addrs().items():
            if not statuses.get(name) or not statuses[name].isup:
                continue
            for address in addresses:
                if (
                    address.family == socket.AF_INET
                    and address.netmask
                    and not address.address.startswith("127.")
                ):
                    network = ipaddress.IPv4Network((address.address, address.netmask), strict=False)
                    if network.prefixlen < 31:
                        broadcasts.add(int.from_bytes(network.broadcast_address.packed, "little"))
        if len(broadcasts) > 16:
            raise ValueError("More than 16 active IPv4 broadcast networks")
        cfg.broadcast_count = len(broadcasts)
        for i, address in enumerate(sorted(broadcasts)):
            cfg.broadcasts[i] = address
        cfg.get_pid = p.remote_api(K, "GetCurrentProcessId")
        cfg.get_tid = p.remote_api(K, "GetCurrentThreadId")
        for name, rva in [
            ("get_context", 0x198530),
            ("initialize", 0x1F018D0),
            ("shutdown", 0x1F01680),
            ("listen", 0x1F01BC0),
            ("enable", 0x1F01BE0),
            ("connect", 0x1F01B80),
            ("local_connect", 0x1F011E0),
            ("add_listing", 0x1497F80),
        ]:
            setattr(cfg, name, base + rva)
        cfg.udp_create = base + 0x1F01DF0
        cfg.udp_send = base + 0x1F01D70
        cfg.udp_vtable = base + 0x2979E68
        cfg.add_table = p.remote_api(N, "RtlAddFunctionTable")
        cfg.create_timer = p.remote_api(K, "CreateTimerQueueTimer")
        cfg.delete_timer = p.remote_api(K, "DeleteTimerQueueTimer")
        cfg.remove_listing = base + 0x14984C0
        cfg.get_tick = p.remote_api(K, "GetTickCount")
        cfg.get_manager = base + 0x111E420
        cfg.get_name = base + 0x111E5F0
        for field, name in [
            ("create_event", "CreateEventW"),
            ("wait_event", "WaitForSingleObject"),
            ("close_handle", "CloseHandle"),
            ("get_error", "GetLastError"),
        ]:
            setattr(cfg, field, p.remote_api(K, name))
        self.base = K.VirtualAllocEx(p.handle, None, self.pe.OPTIONAL_HEADER.SizeOfImage, 0x3000, 4)
        if not self.base:
            raise c.WinError(c.get_last_error())
        directory = self.pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        cfg.table = self.base + directory.VirtualAddress
        cfg.table_count = directory.Size // 12
        cfg.image_base = self.base
        offset = self.exports["host_config"]
        self.image[offset : offset + c.sizeof(Host)] = bytes(cfg)
        p.write(self.base, bytes(self.image))
        for section in self.pe.sections:
            if section.Characteristics & 0x20000000:
                old = w.DWORD()
                if not K.VirtualProtectEx(
                    p.handle, self.base + section.VirtualAddress, section.Misc_VirtualSize, 0x20, c.byref(old)
                ):
                    raise c.WinError(c.get_last_error())
        if not K.FlushInstructionCache(p.handle, self.base, len(self.image)):
            raise c.WinError(c.get_last_error())

    def command(self, value):
        self.memory.write(
            self.base + self.exports["host_config"] + Host.command.offset, value.to_bytes(4, "little")
        )

    def publish(self):
        for index, name in HOOKS.items():
            self.memory.swap(
                self.cfg.expected_vtable + 8 * index, self.cfg.original[index], self.base + self.exports[name]
            )
            self.published.append(index)

    def restore(self):
        self.command(3)
        for index in reversed(self.published):
            self.memory.swap(
                self.cfg.expected_vtable + 8 * index,
                self.base + self.exports[HOOKS[index]],
                self.cfg.original[index],
            )
        self.published = []

    def close(self):
        self.pe.close()
        self.memory.close()


class Game:
    def __init__(self, pid):
        self.process = psutil.Process(pid)
        self.exe = Path(self.process.exe())
        if hashlib.sha256(self.exe.read_bytes()).hexdigest() != EXPECTED_EXE:
            raise ValueError("Unsupported Warcraft III executable")
        if hashlib.sha256((self.exe.parent / "war3_loader.dll").read_bytes()).hexdigest() != EXPECTED_LOADER:
            raise ValueError("Unsupported Warcraft III loader")
        self.memory = Memory(pid)
        self.created = self.process.create_time()
        self.base = next(
            m.lpBaseOfDll
            for m in pymem.process.enum_process_module(self.memory.handle)
            if m.name.lower() == "warcraft iii.exe"
        )
        if fingerprint(self.memory.read(self.base, 4096)) != IDENTITY:
            raise ValueError("Loaded image differs")
        self.alias, self.menu = locate(self.memory)
        with pefile.PE(str(self.exe), fast_load=True) as pe:
            for rva, signature in SIGNATURES.items():
                if self.memory.read(self.alias + rva, 5) not in (
                    pe.get_data(rva, 5),
                    bytes.fromhex(signature),
                ):
                    raise ValueError(f"Native interface differs at {rva:x}")
        for slot, rva in ((0, 0x1EFB35C), (2, 0x1F02FB0), (6, 0x1EFD150), (8, 0x1EFF6B0), (9, 0x1EFE1E0)):
            if (
                int.from_bytes(self.memory.read(self.base + 0x2979E68 + slot * 8, 8), "little")
                != self.base + rva
            ):
                raise ValueError("Native UDP interface differs")
        if int.from_bytes(self.memory.read(self.base + 0x2979EC0 + 8, 8), "little") != self.base + 0x1F02EE0:
            raise ValueError("Native UDP send interface differs")
        self.adapter = None

    def alive(self):
        try:
            return psutil.Process(self.process.pid).create_time() == self.created
        except psutil.NoSuchProcess:
            return False

    def counts(self):
        return list(struct.unpack("<6I", self.memory.read(self.base + COUNTS, 24)))

    def socket(self):
        port, guid = self.menu
        return connect(
            f"ws://127.0.0.1:{port}/webui-socket/{guid}",
            origin=f"http://127.0.0.1:{port}",
            proxy=None,
            compression=None,
            ping_interval=None,
            close_timeout=1,
        )

    def arm(self):
        self.release()
        adapter = NativeAdapter(self.process.pid, self.base)
        self.adapter = adapter
        adapter.prepare()
        adapter.cfg.discovery = adapter.cfg.profile_enabled = 1
        adapter.cfg.udp_port, adapter.cfg.udp_last = 6112, 6127
        adapter.memory.write(adapter.base + adapter.exports["host_config"], bytes(adapter.cfg))
        adapter.publish()
        adapter.command(1)

    def activate(self):
        if not self.adapter:
            raise ValueError("LAN has not been armed")
        with self.socket() as ws:
            ws.send(json.dumps({"type": "webui", "message": "SendGameListing", "payload": {}}))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                cfg = self.adapter.read()
                if cfg.state == 2 and cfg.udp_stage == 1 and not cfg.active:
                    return
                if cfg.error or cfg.udp_error:
                    raise RuntimeError("Native LAN initialization failed")
                try:
                    ws.recv(timeout=0.05)
                except TimeoutError:
                    pass
        raise TimeoutError("Native LAN initialization did not complete")

    def release(self):
        adapter = self.adapter
        if not adapter:
            return
        if not self.alive():
            adapter.close()
            self.adapter = None
            return
        if not adapter.published:
            adapter.close()
            self.adapter = None
            return
        adapter.command(2)
        cfg = adapter.read()
        # Restore the owned identity/mode before the native list callback drops
        # the matching network reference. The page waits for us before re-init.
        if 49 in adapter.published:
            adapter.memory.swap(
                cfg.expected_vtable + 49 * 8, adapter.base + adapter.exports[HOOKS[49]], cfg.original[49]
            )
            adapter.published.remove(49)
        if (
            cfg.session
            and cfg.provider
            and int.from_bytes(self.memory.read(cfg.provider, 8), "little") == cfg.expected_vtable
        ):
            current = int.from_bytes(self.memory.read(cfg.session + 0xC890, 8), "little")
            if current & 0xFFFFFFFF == TCPN:
                adapter.memory.swap(
                    cfg.session + 0xC890, current, (current & 0xFFFFFFFF00000000) | cfg.old_mode
                )
        request = json.dumps({"type": "webui", "message": "SendGameListing", "payload": {}})
        with self.socket() as ws:
            deadline = time.monotonic() + 10
            ws.send(request)
            last_trigger = time.monotonic()
            while time.monotonic() < deadline:
                cfg = adapter.read()
                if cfg.state == 3 and not cfg.active and not cfg.started:
                    break
                if cfg.state == 6 and not cfg.active and time.monotonic() - last_trigger >= 0.25:
                    ws.send(request)
                    last_trigger = time.monotonic()
                try:
                    ws.recv(timeout=0.05)
                except TimeoutError:
                    pass
            else:
                raise RuntimeError("Native cleanup did not finish")
        adapter.restore()
        if cfg.baseline_ready and self.counts() != list(cfg.baseline):
            raise RuntimeError("Native network references did not return to baseline")
        print(json.dumps({"pid": self.process.pid, "released": summary(adapter.read())}), flush=True)
        adapter.close()
        self.adapter = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    games = {}

    def select(port):
        for game in games.values():
            if game.alive() and game.menu[0] == port:
                return game
        for process in psutil.process_iter(["name"]):
            if (process.info["name"] or "").lower() != "warcraft iii.exe":
                continue
            if process.pid not in games or not games[process.pid].alive():
                games[process.pid] = Game(process.pid)
            if games[process.pid].menu[0] == port:
                return games[process.pid]
        raise ValueError("No verified game matches the menu origin")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def reply(self, value, status=200):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "null"))
            self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlsplit(self.path)
            origin = urlsplit(self.headers.get("Origin", ""))
            if origin.scheme != "http" or origin.hostname != "127.0.0.1" or not origin.port:
                self.reply({"ok": False, "error": "Expected a local game menu origin"}, 403)
                return
            if url.path == "/offline":
                self.reply({"native": True, "offline": args.offline, "name": "Local Player"})
                return
            if url.path not in ("/arm", "/activate"):
                self.reply({"ok": False}, 404)
                return
            game = None
            try:
                game = select(origin.port)
                if url.path == "/activate":
                    game.activate()
                elif parse_qs(url.query).get("lan", ["1"]) == ["0"]:
                    game.release()
                else:
                    game.arm()
                self.reply({"ok": True, "native": True})
            except Exception as error:
                print(f"Menu switch failed: {error!r}", flush=True)
                if game:
                    game.release()
                self.reply({"ok": False, "native": True, "error": str(error)}, 409)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/log" or not 0 <= length <= 4096:
                self.reply({"ok": False}, 400)
                return
            print(self.rfile.read(length).decode("utf-8", errors="replace"), flush=True)
            self.reply({"ok": True})

    server = HTTPServer(("127.0.0.1", 8790), Handler)
    server.timeout = 0.2
    print("Ready. Click Local Area Network. Keep this window open until the game closes.", flush=True)
    try:
        while True:
            server.handle_request()
            for pid, game in list(games.items()):
                if not game.alive():
                    game.release()
                    game.memory.close()
                    del games[pid]
                elif game.adapter:
                    cfg = game.adapter.read()
                    if cfg.error or cfg.udp_error:
                        raise RuntimeError(
                            f"Native adapter error in process {game.process.pid}: {summary(cfg)}"
                        )
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for game in games.values():
            game.release()
            game.memory.close()


if __name__ == "__main__":
    main()
