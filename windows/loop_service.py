"""Profile-backed LOOP capability service. All target addresses come from GameProfile."""

from __future__ import annotations
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import time
from websockets.sync.client import connect
from lan_runtime import save_json
from loop_backend import NativeProcess, OwnedImage, SlotLease
from loop_protocol import MAGIC, ABI, LOOP, TCPN, Context, layout


class LoopService:
    def __init__(self, session, dll, output):
        self.session = session
        self.dll = Path(dll)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.memory = self.socket = None
        self.lock = None
        self.state_directory = (
            Path(__file__).resolve().parents[1] / "investigation/runs"
        )
        self.state_directory.mkdir(parents=True, exist_ok=True)
        self.data = session.profile.data["native_loop"]
        self.report = dict(
            pid=session.pid,
            created=session.created,
            game=session.profile.data["game_version"],
            executable_sha256=session.profile.data["executable_sha256"],
            loader_sha256=session.profile.data["loader_sha256"],
            tool_version="0.1-local",
            bridge_protocol=ABI,
            adapter=session.profile.data["adapter_id"],
            adapter_version=session.profile.data["adapter_version"],
            fingerprint=session.profile.data["fingerprint"],
            events=[],
            operations=[],
        )
        try:
            import msvcrt

            self.lock = open(
                self.state_directory / ("loop-%d.lock" % session.pid), "a+b"
            )
            self.lock.seek(0)
            self.lock.write(b"0")
            self.lock.flush()
            self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            session.check_identity()
            loader = session.image.parent / "war3_loader.dll"
            if (
                hashlib.sha256(loader.read_bytes()).hexdigest()
                != session.profile.data["loader_sha256"]
            ):
                raise ValueError("Loader hash differs from the LOOP profile")
            if session.debugger_present():
                raise ValueError("Another debugger is attached")
            self.memory = NativeProcess(session.pid, session.created)
            self.verify()
            self.socket = connect(
                "ws://127.0.0.1:%d/webui-socket/%s" % (session.port, session.guid),
                origin="http://127.0.0.1:%d" % session.port,
                proxy=None,
                compression=None,
                close_timeout=2,
            )
        except BaseException:
            self.close()
            raise

    def verify(self):
        s = self.session
        d = self.data
        s.check_identity()
        if d["bridge_abi"] != ABI:
            raise ValueError("Profile LOOP ABI differs")
        for guard in d["checks"]:
            accepted = [bytes.fromhex(value) for value in guard["accepted_hex"]]
            actual = s.memory.read_bytes(s.alias + guard["rva"], len(accepted[0]))
            if actual not in accepted:
                raise ValueError("LOOP code guard differs at RVA 0x%X" % guard["rva"])
        for kind in ("listing", "join"):
            slot = s.base + d[kind + "_slot_rva"]
            target = struct.unpack("<Q", self.memory.read(slot, 8))[0]
            if target != s.base + d[kind + "_original_rva"]:
                raise ValueError(kind + " data slot already has a foreign owner")
            if self.memory.query(slot).protect != 2:
                raise ValueError(kind + " data slot protection differs")

    def send(self, name, payload=None):
        self.session.check_identity()
        self.socket.send(
            json.dumps(dict(type="webui", message=name, payload=payload or {}))
        )

    def receive(self, timeout=0.05):
        try:
            event = json.loads(self.socket.recv(timeout=timeout))
        except TimeoutError:
            return None
        if event.get("messageType") in (
            "OnNetProviderChanged",
            "RequestError",
            "SetGlueScreen",
            "GameList",
            "GameListUpdate",
            "GameInfo",
            "GameLobbySetup",
            "GameLobbyUpdate",
        ):
            self.report["events"].append(event)
        return event

    def initialize(self):
        journal = self.state_directory / ("loop-retained-%d.json" % self.session.pid)
        if journal.exists():
            data = json.loads(journal.read_text(encoding="utf-8"))
            peer = (
                data.get("last_peer")
                if data.get("created") == self.session.created
                else None
            )
            if peer and any(
                x.status == "ESTABLISHED" and x.raddr and list(x.raddr) == peer
                for x in self.session.process.net_connections("tcp")
            ):
                raise ValueError(
                    "A LAN match is still connected; leave the match before initializing again"
                )
        self.send("InitializeLocalNetProvider")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            event = self.receive(0.1)
            if event and event.get("messageType") == "OnNetProviderChanged":
                mode = event.get("payload", {}).get("providerId")
                if mode != "LOOP":
                    raise ValueError("Expected LOOP provider initialization")
                self.report["initialized_provider"] = mode
                return
        raise TimeoutError("LOOP initialization had no game readback")

    def game_list(self, timeout=5, expected=()):
        self.send("GetGameList")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.receive(0.1)
            if event and event.get("messageType") == "GameList":
                games = event.get("payload", {}).get("games", [])
                # The UI may have older list requests in flight when LOOP is
                # initialized. Accept only a readback of this publication.
                if all(
                    sum(
                        game.get("id") == identity and game.get("name") == name
                        for game in games
                    )
                    == 1
                    for identity, name in expected
                ):
                    return games
        raise TimeoutError("Game list had no matching menu readback")

    def _image(self):
        # A process-scoped journal limits lifetime-retained executable allocations.
        s = self.session
        # Each publication owns an immutable original-method binding. A thread may
        # have fetched a slot pointer before restoration without entering yet;
        # active_calls==0 therefore does not permit reusing that context for a
        # different virtual method or generation.
        journal = self.state_directory / ("loop-retained-%d.json" % s.pid)
        record = json.loads(journal.read_text()) if journal.exists() else {}
        if record.get("created") != s.created:
            record = dict(created=s.created, images=[])
        if (
            len(record["images"]) >= 64
            or sum(x["size"] for x in record["images"]) >= 8 * 1024 * 1024
        ):
            raise ValueError(
                "LOOP callback retention budget reached; restart game through Battle.net"
            )
        image = OwnedImage(self.memory, self.dll)
        initial = Context.from_buffer_copy(
            self.memory.read(image.exports["lan_context"], c.sizeof(Context))
        )
        if (
            initial.magic != MAGIC
            or initial.abi != ABI
            or initial.size != c.sizeof(Context)
        ):
            raise ValueError("Native callback identity/ABI differs; rebuild the bridge")
        if (
            list(
                struct.unpack("<14I", self.memory.read(image.exports["lan_layout"], 56))
            )
            != layout()
        ):
            raise ValueError("Mapped native callback layout differs")
        record["images"].append(
            dict(base=image.base, size=image.size, sha256=image.sha256)
        )
        save_json(journal, record)
        return image

    def run(
        self,
        operation,
        *,
        listings=(),
        bound=None,
        target=None,
        trigger=None,
        timeout=8,
    ):
        self.verify()
        s = self.session
        d = self.data
        m = self.memory
        image = self._image()
        address = image.exports["lan_context"]
        previous = Context.from_buffer_copy(m.read(address, c.sizeof(Context)))
        ctx = Context()
        ctx.magic = MAGIC
        ctx.abi = ABI
        ctx.size = c.sizeof(Context)
        ctx.state = 1
        ctx.unwind_state = previous.unwind_state
        ctx.operation = operation
        ctx.generation = time.time_ns()
        ctx.expected_vtable = s.base + d["vtable_rva"]
        kind = "join" if operation == 2 else "listing"
        ctx.original = s.base + d[kind + "_original_rva"]
        for field in ("get_context", "add_listing", "connect"):
            setattr(ctx, field, s.base + d[field + "_rva"])
        for field in (
            "owner_data_offset",
            "current_session_offset",
            "mode_offset",
            "provider_tag_a_offset",
            "provider_tag_b_offset",
            "context_slot",
        ):
            setattr(ctx, field, d[field])
        ctx.get_tid = m.remote_api("kernel32", "GetCurrentThreadId")
        ctx.rtl_add_table = m.remote_api("ntdll", "RtlAddFunctionTable")
        ctx.runtime_table = image.runtime_table
        ctx.runtime_count = image.runtime_count
        ctx.image_base = image.base
        if operation == 1:
            if not 1 <= len(listings) <= 32:
                raise ValueError("Expected one to 32 native listings")
            ctx.listing_count = len(listings)
            for i, value in enumerate(listings):
                ctx.listings[i] = value.native()
        if operation == 2:
            if bound is None or target is None:
                raise ValueError(
                    "Join needs fresh provider/session and an advertisement"
                )
            ctx.bound_provider, ctx.bound_session = bound
            ctx.target = target.native().endpoint
            ctx.target_port = target.port
            if (
                struct.unpack("<I", m.read(ctx.bound_session + d["mode_offset"], 4))[0]
                != LOOP
            ):
                raise ValueError("Bound session no longer uses LOOP")
            if (
                struct.unpack("<Q", m.read(ctx.bound_provider, 8))[0]
                != ctx.expected_vtable
            ):
                raise ValueError("Bound provider class changed")
            journal = self.state_directory / ("loop-retained-%d.json" % s.pid)
            record = json.loads(journal.read_text(encoding="utf-8"))
            record["last_peer"] = [target.address, target.port]
            save_json(journal, record)
        m.write(address, bytes(ctx))
        lease = SlotLease(
            m,
            s.base + d[kind + "_slot_rva"],
            ctx.original,
            image.exports["loop_callback"],
            image,
        )
        evidence = dict(
            operation=operation,
            image_base=image.base,
            callback_sha256=image.sha256,
            started=time.time(),
        )
        self.report["operations"].append(evidence)
        result = None
        try:
            lease.publish()
            if trigger:
                trigger()
            else:
                self.send("SendGameListing")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                result = Context.from_buffer_copy(m.read(address, c.sizeof(Context)))
                if result.state in (3, 4):
                    break
                self.receive(0.025)
            else:
                raise TimeoutError(
                    "Native callback did not complete; operation was not replayed"
                )
            evidence.update(
                state=result.state,
                error=result.error,
                tid=result.entered_tid,
                provider=result.output_provider,
                session=result.output_session,
                unwind=result.unwind_state,
                result=result.result,
                listing_results=[
                    x.native_result for x in result.listings[: result.listing_count]
                ],
            )
            if result.state != 3:
                raise RuntimeError("Native LOOP callback error %d" % result.error)
            evidence["mode_readback"] = struct.unpack(
                "<I", m.read(result.output_session + d["mode_offset"], 4)
            )[0]
            expected_mode = TCPN if operation == 2 else LOOP
            if evidence["mode_readback"] != expected_mode:
                raise RuntimeError("Session provider readback differs")
            if operation == 2 and result.result == 0:
                raise RuntimeError(
                    "Native connect returned failure; operation was not replayed"
                )
            return result
        finally:
            # Stop new dispatches first; registered images remain alive until game exit.
            try:
                lease.restore()
                evidence["slot_restored"] = lease.restored
                with m.stopped():
                    state = struct.unpack(
                        "<i", m.read(address + Context.state.offset, 4)
                    )[0]
                    if state == 1:
                        m.write(address + Context.state.offset, struct.pack("<i", 5))
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    calls = struct.unpack(
                        "<i", m.read(address + Context.active_calls.offset, 4)
                    )[0]
                    if not calls:
                        break
                    time.sleep(0.01)
                evidence["active_calls_after_restore"] = calls
                if calls:
                    raise RuntimeError(
                        "Callback still running; no further operation permitted"
                    )
            finally:
                evidence["finished"] = time.time()
                save_json(self.output / "loop-report.json", self.report)

    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None
        if self.memory:
            self.memory.close()
            self.memory = None
        if self.lock:
            self.lock.close()
            self.lock = None
