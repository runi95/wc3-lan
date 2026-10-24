"""Menu responses may race with LOOP initialization; never consume stale results."""

from collections import deque
from pathlib import Path
import sys
import pytest

if sys.platform != "win32":
    pytest.skip("Windows LOOP service", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))
import loop_service
from loop_service import LoopService


def menu(games):
    return dict(messageType="GameList", payload=dict(games=games))


def fake_service(monkeypatch, events):
    clock = [0.0]
    queue = deque(events)
    sent = []
    service = LoopService.__new__(LoopService)
    service.send = lambda *args: sent.append(args)

    def receive(timeout):
        clock[0] += timeout
        return queue.popleft() if queue else None

    service.receive = receive
    monkeypatch.setattr(loop_service.time, "monotonic", lambda: clock[0])
    return service, sent


def test_list_waits_for_own_publication_without_sending_another_request(monkeypatch):
    selected = dict(id=7, name="Local room", mapFile="maps/test.w3x")
    service, sent = fake_service(
        monkeypatch,
        [
            menu([]),
            menu([dict(id=7, name="Old room")]),
            dict(messageType="OnNetProviderChanged", payload=dict(providerId="LOOP")),
            menu([dict(id=8, name="Local room")]),
            menu([selected]),
        ],
    )
    assert service.game_list(expected=[(7, "Local room")]) == [selected]
    assert sent == [("GetGameList",)]


def test_duplicate_or_stale_listings_timeout_without_a_replay(monkeypatch):
    selected = dict(id=7, name="Local room")
    service, sent = fake_service(
        monkeypatch, [menu([selected, selected]), menu([dict(id=8, name="Local room")])]
    )
    with pytest.raises(TimeoutError, match="matching menu readback"):
        service.game_list(timeout=0.5, expected=[(7, "Local room")])
    assert sent == [("GetGameList",)]


def test_all_requested_listings_must_have_one_matching_native_identity(monkeypatch):
    first = dict(id=1, name="One")
    second = dict(id=2, name="Two")
    service, sent = fake_service(monkeypatch, [menu([first]), menu([first, second])])
    assert service.game_list(expected=[(1, "One"), (2, "Two")]) == [first, second]
    assert sent == [("GetGameList",)]
