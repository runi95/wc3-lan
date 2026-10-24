"""Disposable process for real, debugger-free remote callback publication tests."""

import ctypes as c
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "contract_fixture", root / "tests/test_loop_bridge.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
f = module.Fixture()
kernel = c.WinDLL("kernel32", use_last_error=True)
kernel.VirtualAlloc.restype = c.c_void_p
kernel.VirtualAlloc.argtypes = [c.c_void_p, c.c_size_t, c.c_ulong, c.c_ulong]
kernel.VirtualProtect.argtypes = [
    c.c_void_p,
    c.c_size_t,
    c.c_ulong,
    c.POINTER(c.c_ulong),
]
slot = kernel.VirtualAlloc(None, 4096, 0x3000, 4)
if not slot:
    raise c.WinError(c.get_last_error())
original = c.cast(f.functions[2], c.c_void_p).value
c.c_uint64.from_address(slot).value = original
old = c.c_ulong()
assert kernel.VirtualProtect(slot, 4096, 2, c.byref(old))
directory = Path(sys.argv[1])
directory.mkdir(parents=True, exist_ok=True)
data = dict(
    pid=os.getpid(),
    tid=kernel.GetCurrentThreadId(),
    slot=slot,
    original=original,
    expected_vtable=f.context.expected_vtable,
    get_context=c.cast(f.functions[0], c.c_void_p).value,
    provider=c.addressof(f.provider),
    session=c.addressof(f.session),
)
(directory / "fixture.json").write_text(json.dumps(data))
deadline = time.monotonic() + 40
while not (directory / "trigger").exists() and time.monotonic() < deadline:
    time.sleep(0.02)
if (directory / "trigger").exists():
    pointer = c.c_uint64.from_address(slot).value
    callback = module.CALLBACK(pointer)
    result = callback(c.addressof(f.provider), 2, 3, 4, 5, 6)
    (directory / "calls.json").write_text(
        json.dumps(
            dict(
                result=result,
                context_calls=f.context_calls,
                original_calls=f.original_calls,
                mode=f.mode,
            )
        )
    )
called_twice = False
while not (directory / "finish").exists() and time.monotonic() < deadline:
    if not called_twice and (directory / "trigger-2").exists():
        callback = module.CALLBACK(c.c_uint64.from_address(slot).value)
        result = callback(c.addressof(f.provider), 2, 3, 4, 5, 6)
        (directory / "calls-2.json").write_text(
            json.dumps(
                dict(
                    result=result,
                    context_calls=f.context_calls,
                    original_calls=f.original_calls,
                    mode=f.mode,
                )
            )
        )
        called_twice = True
    time.sleep(0.02)
