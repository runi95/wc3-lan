# Windows 3.0.1.24371 (experimental)

Build 24371 no longer initializes the legacy LTCP provider. Changing the old
LOOP-to-TCPN selector is insufficient. This adapter publishes external W3GS rooms
through LOOP and changes the actual session to TCPN when joining.

The adapter is pinned to the exact EXE and `war3_loader.dll` hashes in
`windows/profiles/3.0.1.24371.json`. It attaches no debugger and changes no game
`.text`. Run the game through Battle.net.

## Setup

Needs 64-bit Python, LLVM (`clang-cl`, `lld-link`), and, for the external host,
Rust plus its Windows C/C++ build tools.

```powershell
python -m pip install -r .\windows\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build-loop-bridge.ps1
```

Close the game, then install the menu page:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\install.ps1 -Game 'C:\Games\Warcraft III'
```

Prepare the public host sources at the tested commits:

```powershell
git clone https://github.com/Promises/wc3-slop-lan .\investigation\references\wc3-slop-lan
git -C .\investigation\references\wc3-slop-lan checkout 553c9ce798d1971edcda81ec1c3bbb00f046c667
git clone https://github.com/BogdanW3/W3C-Flo .\investigation\references\W3C-Flo
git -C .\investigation\references\W3C-Flo checkout 6db3a4010fab0b0b29824a61f2c9c956f97fd211
python .\tools\prepare-lan-host.py --source .\investigation\references\wc3-slop-lan --flo .\investigation\references\W3C-Flo
cargo build --release --manifest-path .\investigation\references\wc3-slop-lan\host\Cargo.toml
```

For existing checkouts, verify their commits and run the preparation/build steps.
The preparation script uses local Flo dependencies to avoid unused private
submodule fetches, and replies to the actual UDP discovery requester.

## Host and join

Put the same map at the same relative Maps path on each client. Launch the game
through Battle.net and leave it at the main menu. In another PowerShell window:

```powershell
.\windows\lan-host.ps1 -Map 'C:\Maps\Example.w3x' -Name 'Local room' -PlayerNames 'One','Two'
```

Each client joins with:

```powershell
.\windows\loop-lan.ps1 -Action join -Name 'Local room'
```

For a host on another machine, add `-HostAddress <host IPv4>`. All configured
players must join and confirm the map before the automatic countdown. Discovery
uses an explicit host address. Cross-machine play remains unverified.

For a one-client stability test, configure one player and add `-OpponentSeat 1`
on a map with that seat available. This is an idle host seat, not an AI. A melee
map with only one player and no opposing seat normally ends in immediate victory.

Use `-Action list` to inspect rooms, or `-Action query` for a callback query.
Leave an existing match before initializing another room. Use the scripts to
host/join: the native Create Game flow still creates a LOOP single-player game.
The Windows page gives instructions instead of silently entering that flow.

## Validation and lifecycle

On one official Battle.net-launched 24371 client, local testing verified room
listing, TCPN readback, W3GS handshake/map checks, map loading, action forwarding,
a roughly 30-minute match, and process exit with code 0 and no new crash dump.
The same core binaries also passed a seven-minute offline-started join/exit test.

Two independent local clients joined the same room/map and both sent actions.
The user observed normal synchronized gameplay, while the relay logged checksum
disagreements after several minutes. Deterministic synchronization needs further
investigation before this is treated as production-ready multiplayer support.
Cross-machine behavior and comparative performance remain untested.
This does not establish the cause or resolution of an unrelated 35-second crash
report. Earlier debugger experiments and an intermediate cleanup failure were
retained locally as failed tests.

Every operation checks the process creation identity, build guards and original
slot pointer. Join additionally binds the current provider/session and endpoint.
Data slots and page permissions are restored; failed/uncertain operations are not
replayed. Each publication keeps its own callback image and unwind metadata until
process exit, including callers that fetched a slot before restoration. A bounded
process journal limits retained allocations. Evidence is written under
`investigation/runs/`, which is excluded from Git.

Tests (Windows x64, with pytest and Node.js installed):

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_loop_bridge.py tests/test_loop_backend.py tests/test_loop_discovery.py tests/test_loop_service.py
node tests/test_windows_page.cjs
```

The 38 tests cover native ABI contracts, rejected sessions/endpoints, real OS
mapping and restoration, independent operation images, and stale list replies;
the page fixture checks visible failure instead of single-player fallback.

Native ABI research was informed by W3Champions 1.6.25. The callback is independently
implemented; no game binaries, launcher binaries or extracted callbacks are included.
