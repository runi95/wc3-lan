# Windows 3.0.1.24371

24371 no longer exposes the old TCPN provider. This adapter uses the game's own
TCP/UDP interfaces, with a resident helper on `127.0.0.1:8790` coordinating menu
initialization and cleanup. It does not run an external game server.

Requires 64-bit Python 3.10+ and LLVM (`clang-cl` and `lld-link` on PATH):

```powershell
python -m pip install -r windows\native24371\requirements.txt
```

Close the game, then install the menu through the original entry point:

```powershell
powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Game "E:\Warcraft III"
```

Start the helper before launching the game for offline play:

```powershell
powershell -ExecutionPolicy Bypass -File windows\lan-switch.ps1 -Native24371 -Offline
```

The script builds the adapter if needed. Start your usual launcher, click
**Local Area Network**, then create/join/start through the original game screens.
One helper handles both copies on the same PC. Keep its console open until the
games close, then press Ctrl+C. If 24371 is already at the main menu, running
`windows\lan-switch.ps1` automatically selects this adapter.

Both PCs need the adapter and the same game build. Discovery uses active IPv4
subnets, and the game owns the TCP connections. Executable/loader hashes and
interfaces are checked before data pointers change; no debugger or game-code
patching is used. The original 24268 switch is unchanged.

Uninstall through `windows\install.ps1 -Uninstall` after closing the game.

## Validation

Validated on the user-provided **3.0.1.24371 installation**, called 学习版 by the
user, started through its custom `Warcraft III Launcher.exe` with the helper's
`-Offline` option. **Two simultaneous clients on one PC** passed hosting,
discovery, join/start, gameplay, re-entry and cleanup. This installation shares
the registered game directory; clean official and separate offline installations
were not tested independently. **Separate physical PCs have not been tested.**

Automated hosting used the original CreateLobby request; automated room-name
text entry was not verified. The cause of other installations' reported
35-second crashes has not been established.
