"""Execute the independently compiled callback against synthetic native objects."""

import ctypes as c
from pathlib import Path
import socket
import sys
import pytest

if sys.platform != "win32":
    pytest.skip("Windows x64 native ABI", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))
from loop_protocol import (
    ABI,
    MAGIC,
    LOOP,
    TCPN,
    Context,
    Endpoint,
    NativeString,
    layout,
)

ROOT = Path(__file__).resolve().parents[1]
CALLBACK = c.WINFUNCTYPE(c.c_uint64, *([c.c_uint64] * 6))
GET_CONTEXT = c.WINFUNCTYPE(c.c_uint64, c.c_uint32)
GET_TID = c.WINFUNCTYPE(c.c_uint32)
REGISTER = c.WINFUNCTYPE(c.c_ubyte, c.c_uint64, c.c_uint32, c.c_uint64)
ADD = c.WINFUNCTYPE(
    c.c_int,
    c.c_uint64,
    c.c_uint64,
    c.c_uint64,
    *([c.c_uint32] * 4),
    c.c_uint64,
    *([c.c_uint32] * 3),
    c.c_uint64,
    c.c_uint64,
    c.c_uint32,
)
CONNECT = c.WINFUNCTYPE(c.c_uint64, c.c_uint32, c.c_uint32, *([c.c_uint64] * 4))


class Fixture:
    def __init__(self):
        self.library = c.WinDLL(str(ROOT / "investigation/loop-bridge/loop_bridge.dll"))
        self.context = Context.in_dll(self.library, "lan_context")
        native_layout = list((c.c_uint32 * 14).in_dll(self.library, "lan_layout"))
        assert native_layout == layout()
        c.memset(c.addressof(self.context), 0, c.sizeof(Context))
        self.owner = c.create_string_buffer(0x40)
        self.data = c.create_string_buffer(0x100)
        self.session = c.create_string_buffer(0xD000)
        self.provider = c.create_string_buffer(0x80)
        self.context_calls = []
        self.original_calls = []
        self.add_calls = []
        self.connect_calls = []
        self.register_calls = []
        self.add_accept = True
        self.registration_ok = True
        self.owner_present = True
        self.set_u64(self.owner, 0x20, c.addressof(self.data))
        self.set_u64(self.data, 0xB8, c.addressof(self.session))
        self.set_u64(self.provider, 0, 0x123456780000)
        self.set_u32(self.provider, 0x30, 1234)
        self.set_u32(self.provider, 0x34, 5678)
        self.set_u32(self.session, 0xC890, LOOP)

        def get_context(slot):
            self.context_calls.append(slot)
            return c.addressof(self.owner) if self.owner_present else 0

        def original(*args):
            self.original_calls.append(args)
            return 0x1234

        def register(*args):
            self.register_calls.append(args)
            return self.registration_ok

        def add(*args):
            self.add_calls.append(args)
            return 100 + len(self.add_calls) if self.add_accept else 0

        def connect(*args):
            self.connect_calls.append((args, self.mode))
            return 0x5678

        self.functions = [
            GET_CONTEXT(get_context),
            GET_TID(lambda: 4242),
            CALLBACK(original),
            REGISTER(register),
            ADD(add),
            CONNECT(connect),
        ]
        pointers = [c.cast(f, c.c_void_p).value for f in self.functions]
        ctx = self.context
        ctx.magic = MAGIC
        ctx.abi = ABI
        ctx.size = c.sizeof(Context)
        ctx.state = 1
        ctx.generation = 8765
        ctx.expected_vtable = 0x123456780000
        (
            ctx.get_context,
            ctx.get_tid,
            ctx.original,
            ctx.rtl_add_table,
            ctx.add_listing,
            ctx.connect,
        ) = pointers
        ctx.runtime_table = 0x11000
        ctx.image_base = 0x10000
        ctx.runtime_count = 1
        ctx.owner_data_offset = 0x20
        ctx.current_session_offset = 0xB8
        ctx.mode_offset = 0xC890
        ctx.context_slot = 13
        ctx.provider_tag_a_offset = 0x30
        ctx.provider_tag_b_offset = 0x34
        self.function = self.library.loop_callback
        self.function.argtypes = [c.c_uint64] * 6
        self.function.restype = c.c_uint64

    @staticmethod
    def set_u64(buffer, offset, value):
        c.c_uint64.from_address(c.addressof(buffer) + offset).value = value

    @staticmethod
    def set_u32(buffer, offset, value):
        c.c_uint32.from_address(c.addressof(buffer) + offset).value = value

    @property
    def mode(self):
        return c.c_uint32.from_address(c.addressof(self.session) + 0xC890).value

    def call(self, argument=0, *tail):
        return self.function(
            c.addressof(self.provider), argument, *(list(tail) + [0] * 4)[:4]
        )

    def prepare_join(self):
        ctx = self.context
        ctx.operation = 2
        ctx.bound_provider = c.addressof(self.provider)
        ctx.bound_session = c.addressof(self.session)
        ctx.target_port = 6112
        ctx.target.family = 2
        ctx.target.port = socket.htons(6112)
        ctx.target.address = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
        self.endpoint = Endpoint.from_buffer_copy(bytes(ctx.target))
        return c.addressof(self.endpoint)


def test_read_only_query_contract():
    f = Fixture()
    assert f.call() == 0
    x = f.context
    assert (x.state, x.error, x.active_calls, x.entered_tid, x.entered_count) == (
        3,
        0,
        0,
        4242,
        1,
    )
    assert x.output_provider == c.addressof(
        f.provider
    ) and x.output_session == c.addressof(f.session)
    assert f.context_calls == [13] and len(f.register_calls) == 1
    assert not f.add_calls and not f.connect_calls and f.mode == LOOP


def test_idle_delegates_all_six_original_arguments():
    f = Fixture()
    f.context.state = 0
    assert f.call(2, 3, 4, 5, 6) == 0x1234
    assert f.original_calls == [(c.addressof(f.provider), 2, 3, 4, 5, 6)]
    assert f.context.active_calls == 0 and not f.register_calls


@pytest.mark.parametrize(
    "case,error",
    [
        ("wrong_layout", 1),
        ("wrong_abi", 1),
        ("zero_context_slot", 1),
        ("bad_context_slot", 1),
        ("wrong_provider", 2),
        ("missing_context", 3),
        ("wrong_mode", 4),
        ("bad_count", 5),
        ("rejected_listing", 6),
        ("stale_session", 7),
        ("wrong_endpoint", 8),
        ("unwind_failure", 9),
        ("unknown_operation", 10),
    ],
)
def test_rejected_contract_has_no_join_side_effect(case, error):
    f = Fixture()
    x = f.context
    if case == "wrong_layout":
        x.size -= 8
    elif case == "wrong_abi":
        x.abi = ABI - 1
    elif case == "zero_context_slot":
        x.context_slot = 0
    elif case == "bad_context_slot":
        x.context_slot = 65
    elif case == "wrong_provider":
        x.expected_vtable += 8
    elif case == "missing_context":
        f.owner_present = False
    elif case == "wrong_mode":
        f.set_u32(f.session, 0xC890, 0x424E4554)
    elif case == "bad_count":
        x.operation = 1
        x.listing_count = 33
    elif case == "rejected_listing":
        x.operation = 1
        x.listing_count = 1
        x.listings[0].endpoint.family = 2
        x.listings[0].endpoint.port = socket.htons(6112)
        f.add_accept = False
    elif case == "stale_session":
        argument = f.prepare_join()
        x.bound_session += 8
    elif case == "wrong_endpoint":
        argument = f.prepare_join()
        f.endpoint.port = socket.htons(6113)
    elif case == "unwind_failure":
        f.registration_ok = False
    elif case == "unknown_operation":
        x.operation = 99
    f.call(argument if case in ("stale_session", "wrong_endpoint") else 0)
    assert (x.state, x.error, x.active_calls) == (4, error, 0)
    assert not f.connect_calls
    assert f.mode == (0x424E4554 if case == "wrong_mode" else LOOP)


def test_listing_call_passes_native_identity_and_bounded_owned_buffers_once():
    f = Fixture()
    x = f.context
    x.operation = 1
    x.listing_count = 1
    row = x.listings[0]
    row.native_tags[:] = [10, 20, 30, 40, 50]
    row.endpoint.family = 2
    row.endpoint.port = socket.htons(6112)
    f.call()
    assert (x.state, x.error, x.active_calls) == (3, 0, 0)
    args = f.add_calls[0]
    assert (
        args[3:7] == (10, 20, 1234, 5678)
        and args[8:11] == (30, 40, 50)
        and args[-1] == 999
    )
    assert args[2] == args[7] == c.addressof(row) + 48 and row.native_result == 101
    for pointer in args[11:13]:
        value = NativeString.from_address(pointer)
        assert value.length == 0 and value.capacity == 0x800000000000000F
        assert value.pointer == pointer + 24
    f.call()
    assert len(f.add_calls) == 1 and f.mode == LOOP


def test_join_binds_listing_session_and_changes_network_mode_at_connect_only():
    f = Fixture()
    argument = f.prepare_join()
    assert f.call(argument, 11, 22, 33, 44) == 0x5678
    assert f.connect_calls == [((0x0100007F, 6112, 11, 22, 33, 44), TCPN)]
    assert f.mode == TCPN and f.context.result == 0x5678
    assert (f.context.state, f.context.error, f.context.active_calls) == (3, 0, 0)
