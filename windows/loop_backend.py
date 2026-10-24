"""Owned native image mapping and a reversible data-slot lease; no debugger API.

Executable allocations are retained after publication/registration until the game
exits. Closing a host handle never releases an image a callback might still use.
"""

from __future__ import annotations
from contextlib import contextmanager
import ctypes as c
import hashlib
from pathlib import Path
import struct
import pefile
import psutil
import pymem.process
from lan_runtime import fingerprint

P = c.c_void_p
Z = c.c_size_t
U = c.c_ulong


class MemoryInfo(c.Structure):
    _fields_ = [
        ("base", P),
        ("allocation", P),
        ("allocation_protect", U),
        ("partition", U),
        ("size", Z),
        ("state", U),
        ("protect", U),
        ("kind", U),
        ("padding", U),
    ]


class NativeProcess:
    def __init__(self, pid, created):
        self.pid, self.created = pid, created
        self.process = psutil.Process(pid)
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.nt = c.WinDLL("ntdll", use_last_error=True)
        self._api(self.kernel, "OpenProcess", P, U, c.c_bool, U)
        self._api(self.kernel, "CloseHandle", c.c_bool, P)
        self._api(self.kernel, "ReadProcessMemory", c.c_bool, P, P, P, Z, c.POINTER(Z))
        self._api(self.kernel, "WriteProcessMemory", c.c_bool, P, P, P, Z, c.POINTER(Z))
        self._api(self.kernel, "VirtualAllocEx", P, P, P, Z, U, U)
        self._api(self.kernel, "VirtualProtectEx", c.c_bool, P, P, Z, U, c.POINTER(U))
        self._api(self.kernel, "VirtualQueryEx", Z, P, P, P, Z)
        self._api(self.kernel, "FlushInstructionCache", c.c_bool, P, P, Z)
        self._api(self.nt, "NtSuspendProcess", c.c_long, P)
        self._api(self.nt, "NtResumeProcess", c.c_long, P)
        self.handle = self.kernel.OpenProcess(0xC38, False, pid)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        try:
            self.identity()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _api(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.restype = result
        fn.argtypes = args
        return fn

    def identity(self):
        if psutil.Process(self.pid).create_time() != self.created:
            raise ValueError("Native process creation identity changed")

    def read(self, address, size):
        self.identity()
        buffer = c.create_string_buffer(size)
        read = Z()
        if (
            not self.kernel.ReadProcessMemory(
                self.handle, address, buffer, size, c.byref(read)
            )
            or read.value != size
        ):
            raise c.WinError(c.get_last_error())
        return buffer.raw

    def write(self, address, data):
        self.identity()
        buffer = c.create_string_buffer(data)
        written = Z()
        if not self.kernel.WriteProcessMemory(
            self.handle, address, buffer, len(data), c.byref(written)
        ) or written.value != len(data):
            raise c.WinError(c.get_last_error())
        if self.read(address, len(data)) != data:
            raise OSError("Native write readback differs")

    def query(self, address):
        row = MemoryInfo()
        if self.kernel.VirtualQueryEx(
            self.handle, address, c.byref(row), c.sizeof(row)
        ) != c.sizeof(row):
            raise c.WinError(c.get_last_error())
        return row

    def protect(self, address, size, protect):
        self.identity()
        old = U()
        if not self.kernel.VirtualProtectEx(
            self.handle, address, size, protect, c.byref(old)
        ):
            raise c.WinError(c.get_last_error())
        return old.value

    @contextmanager
    def stopped(self):
        self.identity()
        status = self.nt.NtSuspendProcess(self.handle)
        if status < 0:
            raise OSError("NtSuspendProcess status 0x%08X" % (status & 0xFFFFFFFF))
        try:
            yield
        finally:
            status = self.nt.NtResumeProcess(self.handle)
            if status < 0:
                raise OSError("NtResumeProcess status 0x%08X" % (status & 0xFFFFFFFF))

    def remote_api(self, module, name):
        library = c.WinDLL(module)
        function = getattr(library, name)
        address = c.cast(function, P).value
        owner = P()
        get_owner = self._api(
            self.kernel, "GetModuleHandleExW", c.c_bool, U, P, c.POINTER(P)
        )
        if not get_owner(6, address, c.byref(owner)):
            raise c.WinError(c.get_last_error())
        path = c.create_unicode_buffer(32768)
        get_path = self._api(self.kernel, "GetModuleFileNameW", U, P, c.c_wchar_p, U)
        if not get_path(owner, path, len(path)):
            raise c.WinError(c.get_last_error())
        name_in_target = Path(path.value).name.lower()
        modules = list(pymem.process.enum_process_module(self.handle))
        found = [m for m in modules if m.name.lower() == name_in_target]
        if len(found) != 1:
            raise ValueError("No unique system module for " + name)
        target = found[0].lpBaseOfDll
        if fingerprint(self.read(target, 4096)) != fingerprint(
            c.string_at(owner, 4096)
        ):
            raise ValueError("System API module identity differs for " + name)
        remote = target + address - owner.value
        row = self.query(remote)
        if row.allocation != target or not row.protect & 0xF0 or row.protect & 0x100:
            raise ValueError("System API has no executable module mapping: " + name)
        if self.read(remote, 16) != c.string_at(address, 16):
            raise ValueError("System API entry bytes differ: " + name)
        return remote

    def close(self):
        if getattr(self, "handle", None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class OwnedImage:
    def __init__(self, memory, dll):
        self.memory = memory
        self.path = Path(dll)
        data = self.path.read_bytes()
        self.sha256 = hashlib.sha256(data).hexdigest()
        pe = pefile.PE(data=data, fast_load=False)
        try:
            if pe.FILE_HEADER.Machine != 0x8664 or hasattr(
                pe, "DIRECTORY_ENTRY_IMPORT"
            ):
                raise ValueError("Native LOOP image must be x64 with no imports")
            self.size = pe.OPTIONAL_HEADER.SizeOfImage
            if self.size > 256 * 1024:
                raise ValueError("Native LOOP image exceeds the image budget")
            directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
            if not directory.Size or directory.Size % 12:
                raise ValueError("Native LOOP image has no complete unwind table")
            exports = {
                s.name.decode(): s.address
                for s in pe.DIRECTORY_ENTRY_EXPORT.symbols
                if s.name
            }
            if set(exports) != {"loop_callback", "lan_context", "lan_layout"}:
                raise ValueError("Native LOOP exports differ from the protocol")
            self.base = memory.kernel.VirtualAllocEx(
                memory.handle, None, self.size, 0x3000, 4
            )
            if not self.base:
                raise c.WinError(c.get_last_error())
            mapped = pe.get_memory_mapped_image(ImageBase=self.base)
            memory.write(self.base, mapped[: self.size])
            self.exports = {name: self.base + rva for name, rva in exports.items()}
            self.runtime_table = self.base + directory.VirtualAddress
            self.runtime_count = directory.Size // 12
            for section in pe.sections:
                size = max(section.Misc_VirtualSize, section.SizeOfRawData)
                if not size:
                    continue
                writable = bool(section.Characteristics & 0x80000000)
                executable = bool(section.Characteristics & 0x20000000)
                if executable and writable:
                    raise ValueError("Native image has an executable writable section")
                memory.protect(
                    self.base + section.VirtualAddress,
                    size,
                    0x20 if executable else (4 if writable else 2),
                )
            memory.protect(self.base, pe.OPTIONAL_HEADER.SizeOfHeaders, 2)
            if not memory.kernel.FlushInstructionCache(
                memory.handle, self.base, self.size
            ):
                raise c.WinError(c.get_last_error())
            self.published = False
        finally:
            pe.close()


class SlotLease:
    def __init__(self, memory, slot, expected, replacement, image):
        if slot % 8:
            raise ValueError("Native callback data slot is not aligned")
        self.memory, self.slot, self.expected, self.replacement, self.image = (
            memory,
            slot,
            expected,
            replacement,
            image,
        )
        self.original_protect = None
        self.published = False
        self.restored = False

    def publish(self):
        memory = self.memory
        with memory.stopped():
            if struct.unpack("<Q", memory.read(self.slot, 8))[0] != self.expected:
                raise ValueError(
                    "Native callback slot is already owned by another component"
                )
            self.original_protect = memory.protect(self.slot, 8, 4)
            try:
                memory.write(self.slot, struct.pack("<Q", self.replacement))
                self.published = True
                self.image.published = True
            except BaseException:
                memory.write(self.slot, struct.pack("<Q", self.expected))
                raise
            finally:
                memory.protect(self.slot, 8, self.original_protect)
            if memory.query(self.slot).protect != self.original_protect:
                raise OSError("Native callback slot page protection readback differs")

    def restore(self):
        if not self.published or self.restored:
            return
        memory = self.memory
        with memory.stopped():
            current = struct.unpack("<Q", memory.read(self.slot, 8))[0]
            if current not in (self.expected, self.replacement):
                raise ValueError(
                    "Native callback slot changed while the operation owned it"
                )
            old = memory.protect(self.slot, 8, 4)
            if old != self.original_protect:
                memory.protect(self.slot, 8, old)
                raise ValueError("Native callback slot protection changed while owned")
            try:
                memory.write(self.slot, struct.pack("<Q", self.expected))
            finally:
                memory.protect(self.slot, 8, self.original_protect)
            if memory.query(self.slot).protect != self.original_protect:
                raise OSError("Restored callback page protection readback differs")
            self.restored = True
