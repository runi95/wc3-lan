"""Fixed ABI for this project's independent native LOOP callback."""

import ctypes as c

MAGIC = 0x57434C414E303031
ABI = 2
LOOP = 0x4C4F4F50
TCPN = 0x5443504E


class Endpoint(c.Structure):
    _fields_ = [
        ("family", c.c_uint16),
        ("port", c.c_uint16),
        ("address", c.c_uint32),
        ("zero", c.c_ubyte * 8),
    ]


class NativeString(c.Structure):
    _fields_ = [
        ("pointer", c.c_uint64),
        ("length", c.c_uint64),
        ("capacity", c.c_uint64),
        ("small", c.c_ubyte * 16),
    ]


class Listing(c.Structure):
    _fields_ = [
        ("native_tags", c.c_uint32 * 5),
        ("native_result", c.c_int32),
        ("reserved", c.c_uint64),
        ("endpoint", Endpoint),
        ("information", c.c_ubyte * 376),
        ("name_a", NativeString),
        ("name_b", NativeString),
        ("padding", c.c_uint64),
    ]


class Context(c.Structure):
    _fields_ = [
        ("magic", c.c_uint64),
        ("abi", c.c_uint32),
        ("size", c.c_uint32),
        ("state", c.c_int32),
        ("error", c.c_uint32),
        ("active_calls", c.c_int32),
        ("unwind_state", c.c_int32),
        ("operation", c.c_uint32),
        ("listing_count", c.c_uint32),
        ("generation", c.c_uint64),
        ("entered_tid", c.c_uint32),
        ("entered_count", c.c_uint32),
        *[
            (name, c.c_uint64)
            for name in (
                "expected_vtable",
                "original",
                "get_context",
                "add_listing",
                "connect",
                "get_tid",
                "rtl_add_table",
                "runtime_table",
                "image_base",
            )
        ],
        ("runtime_count", c.c_uint32),
        ("reserved", c.c_uint32),
        *[
            (name, c.c_uint32)
            for name in (
                "owner_data_offset",
                "current_session_offset",
                "mode_offset",
                "provider_tag_a_offset",
                "provider_tag_b_offset",
                "context_slot",
            )
        ],
        *[
            (name, c.c_uint64)
            for name in (
                "output_provider",
                "output_session",
                "bound_provider",
                "bound_session",
            )
        ],
        ("target_port", c.c_uint32),
        ("reserved_port", c.c_uint32),
        ("target", Endpoint),
        ("result", c.c_uint64),
        ("listings", Listing * 32),
    ]


def layout():
    return [
        c.sizeof(Context),
        c.sizeof(Listing),
        Context.state.offset,
        Context.operation.offset,
        Context.generation.offset,
        Context.expected_vtable.offset,
        Context.runtime_count.offset,
        Context.owner_data_offset.offset,
        Context.output_provider.offset,
        Context.bound_provider.offset,
        Context.target_port.offset,
        Context.target.offset,
        Context.result.offset,
        Context.listings.offset,
    ]
