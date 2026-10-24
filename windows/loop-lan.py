"""Experimental debugger-free LOOP LAN adapter; launch the game through Battle.net."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import traceback
import psutil
from lan_runtime import GameSession, save_json
from loop_discovery import discover
from loop_service import LoopService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--action", choices=("query", "list", "join"), default="query")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--host-address", default="127.0.0.1")
    parser.add_argument("--name")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--watch-seconds", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--dll",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "investigation/loop-bridge/loop_bridge.dll",
    )
    args = parser.parse_args()
    if args.pid is None:
        games = [
            p.pid
            for p in psutil.process_iter(["name"])
            if p.info["name"].lower() == "warcraft iii.exe"
        ]
        if len(games) != 1:
            raise ValueError("Expected one game; use --pid to select")
        args.pid = games[0]
    output = args.output or Path(__file__).resolve().parents[
        1
    ] / "investigation/runs" / ("loop-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=True)
    session = GameSession(args.pid)
    service = None
    try:
        service = LoopService(session, args.dll, output)
        print(
            "Validated EXE, loader, code guards, LOOP slots and callback ABI.",
            flush=True,
        )
        if args.initialize:
            service.initialize()
        if args.action == "query":
            result = service.run(0, timeout=args.timeout)
        else:
            listings = discover(args.host_address)
            if args.name:
                listings = [row for row in listings if row.name == args.name]
            if not listings:
                raise ValueError("No valid host advertisement received")
            if args.action == "join" and len(listings) != 1:
                raise ValueError("Join requires one selected listing; use --name")
            print("Discovered: " + ", ".join(row.name for row in listings), flush=True)
            result = service.run(1, listings=listings, timeout=args.timeout)
            games = service.game_list(
                expected=[
                    (result.listings[i].native_result, row.name)
                    for i, row in enumerate(listings)
                ]
            )
            if args.action == "join":
                target = listings[0]
                matches = [
                    game
                    for game in games
                    if game.get("name") == target.name
                    and game.get("id") == result.listings[0].native_result
                ]
                if len(matches) != 1:
                    raise ValueError(
                        "Native game list did not uniquely confirm the selected listing"
                    )
                game = matches[0]
                result = service.run(
                    2,
                    bound=(result.output_provider, result.output_session),
                    target=target,
                    trigger=lambda: service.send(
                        "JoinGame",
                        dict(gameId=game["id"], password="", mapFile=game["mapFile"]),
                    ),
                    timeout=args.timeout,
                )
        print(
            "Native callback completed on thread %d; slot restored."
            % result.entered_tid,
            flush=True,
        )
        deadline = time.monotonic() + args.watch_seconds
        while time.monotonic() < deadline:
            service.receive(0.1)
        save_json(output / "loop-report.json", service.report)
        print("Evidence: " + str(output.resolve()), flush=True)
    except BaseException:
        (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        if service:
            service.close()
        session.close()


if __name__ == "__main__":
    main()
