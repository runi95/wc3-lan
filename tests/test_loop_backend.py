"""Real memory mapping, unwind registration, and pointer/protection restoration."""

import ctypes as c
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import psutil
import pytest

if sys.platform != "win32":
    pytest.skip("Windows native callback integration", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
from loop_protocol import MAGIC, ABI, Context, LOOP, layout
from loop_backend import NativeProcess, OwnedImage, SlotLease
from loop_service import LoopService


def wait_for(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("Native fixture did not reach the expected phase")


@pytest.mark.parametrize("mode", ["query", "cancel", "foreign_slot", "reuse"])
def test_remote_callback_transaction(tmp_path, mode, monkeypatch):
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tests/loop_slot_fixture.py"), str(tmp_path)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    memory = None
    lease = None
    try:
        wait_for(lambda: (tmp_path / "fixture.json").exists())
        identity = json.loads((tmp_path / "fixture.json").read_text())
        created = psutil.Process(process.pid).create_time()
        with pytest.raises(ValueError, match="creation identity"):
            NativeProcess(process.pid, created + 1)
        memory = NativeProcess(process.pid, created)
        # An existing psutil.Process caches creation time. Simulate PID reuse after opening.
        with monkeypatch.context() as patch:
            from types import SimpleNamespace

            patch.setattr(
                psutil,
                "Process",
                lambda pid: SimpleNamespace(create_time=lambda: created + 1),
            )
            with pytest.raises(ValueError, match="creation identity"):
                memory.identity()
        if mode == "query":
            # Separate publications must keep separate original-method bindings,
            # even when a previous caller has fetched its callback but not entered.
            from types import SimpleNamespace

            service = LoopService.__new__(LoopService)
            service.session = SimpleNamespace(pid=process.pid, created=created)
            service.memory = memory
            service.dll = ROOT / "investigation/loop-bridge/loop_bridge.dll"
            service.state_directory = tmp_path
            image = service._image()
            other_image = service._image()
            assert image.base != other_image.base
            assert image.exports["lan_context"] != other_image.exports["lan_context"]
            journal = json.loads(
                (tmp_path / ("loop-retained-%d.json" % process.pid)).read_text()
            )
            assert len(journal["images"]) == 2
        else:
            image = OwnedImage(
                memory, ROOT / "investigation/loop-bridge/loop_bridge.dll"
            )
        assert memory.query(image.exports["loop_callback"]).protect == 0x20
        assert memory.query(image.exports["lan_context"]).protect == 4
        assert (
            list(struct.unpack("<14I", memory.read(image.exports["lan_layout"], 56)))
            == layout()
        )
        ctx = Context()
        ctx.magic = MAGIC
        ctx.abi = ABI
        ctx.size = c.sizeof(Context)
        ctx.state = 1
        ctx.generation = 1234567
        ctx.original = identity["original"]
        ctx.expected_vtable = identity["expected_vtable"]
        ctx.get_context = identity["get_context"]
        ctx.get_tid = memory.remote_api("kernel32", "GetCurrentThreadId")
        ctx.rtl_add_table = memory.remote_api("ntdll", "RtlAddFunctionTable")
        ctx.runtime_table = image.runtime_table
        ctx.runtime_count = image.runtime_count
        ctx.image_base = image.base
        ctx.owner_data_offset = 0x20
        ctx.current_session_offset = 0xB8
        ctx.mode_offset = 0xC890
        ctx.context_slot = 13
        ctx.provider_tag_a_offset = 0x30
        ctx.provider_tag_b_offset = 0x34
        memory.write(image.exports["lan_context"], bytes(ctx))
        lease = SlotLease(
            memory,
            identity["slot"],
            identity["original"] + (8 if mode == "foreign_slot" else 0),
            image.exports["loop_callback"],
            image,
        )
        if mode == "foreign_slot":
            with pytest.raises(ValueError, match="already owned"):
                lease.publish()
        else:
            lease.publish()
            assert memory.query(identity["slot"]).protect == 2
            assert (
                struct.unpack("<Q", memory.read(identity["slot"], 8))[0]
                == image.exports["loop_callback"]
            )
            if mode == "cancel":
                with memory.stopped():
                    memory.write(
                        image.exports["lan_context"] + Context.state.offset,
                        struct.pack("<i", 5),
                    )
                lease.restore()
        (tmp_path / "trigger").touch()
        wait_for(lambda: (tmp_path / "calls.json").exists())
        calls = json.loads((tmp_path / "calls.json").read_text())
        result = Context.from_buffer_copy(
            memory.read(image.exports["lan_context"], c.sizeof(Context))
        )
        if mode in ("query", "reuse"):
            assert (
                calls["result"] == 0
                and calls["context_calls"] == [13]
                and not calls["original_calls"]
            )
            assert (
                result.state,
                result.error,
                result.active_calls,
                result.unwind_state,
            ) == (3, 0, 0, 2)
            assert result.entered_tid == identity["tid"]
            assert (
                result.output_provider == identity["provider"]
                and result.output_session == identity["session"]
            )
            lease.restore()
            if mode == "reuse":
                result.state = 1
                result.generation += 1
                memory.write(image.exports["lan_context"], bytes(result))
                lease = SlotLease(
                    memory,
                    identity["slot"],
                    identity["original"],
                    image.exports["loop_callback"],
                    image,
                )
                lease.publish()
                (tmp_path / "trigger-2").touch()
                wait_for(lambda: (tmp_path / "calls-2.json").exists())
                calls2 = json.loads((tmp_path / "calls-2.json").read_text())
                result2 = Context.from_buffer_copy(
                    memory.read(image.exports["lan_context"], c.sizeof(Context))
                )
                assert (
                    calls2["context_calls"] == [13, 13] and not calls2["original_calls"]
                )
                assert (
                    result2.state,
                    result2.error,
                    result2.active_calls,
                    result2.unwind_state,
                ) == (3, 0, 0, 2)
                lease.restore()
        else:
            assert calls["result"] == 0x1234 and not calls["context_calls"]
            assert calls["original_calls"] == [[identity["provider"], 2, 3, 4, 5, 6]]
            assert result.active_calls == 0 and result.unwind_state == 0
        assert calls["mode"] == LOOP
        assert memory.query(identity["slot"]).protect == 2
        assert (
            struct.unpack("<Q", memory.read(identity["slot"], 8))[0]
            == identity["original"]
        )
        (tmp_path / "finish").touch()
        process.wait(timeout=5)
        assert process.returncode == 0
    finally:
        if lease is not None:
            lease.restore()
        if memory is not None:
            memory.close()
        (tmp_path / "finish").touch()
        (tmp_path / "trigger").touch()
        if process.poll() is None:
            process.wait(timeout=5)
