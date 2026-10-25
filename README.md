# wc3-lan

Disclaimer: This repository has been written by an AI agent. Parts of the setup and idea comes from W3Champions and [wc3-slop-lan](https://github.com/Promises/wc3-slop-lan) with additional help from sotzaii_shuen to get offline mode working.

Brings back **LAN games** in Warcraft III: Reforged, through the game's own (hidden) **Local
Area Network** button. Host a game there and anyone else on your network with wc3-lan can find it
and join; two copies of the game on one machine can play each other too. Optionally the game
starts **offline**, straight to the main menu without a Battle.net sign-in.

Not affiliated with Blizzard. It changes the game's menu page and, for a moment, one value in the
running game (in its code on Linux, in a CPU register through a debugger on macOS and Windows 24268).
Windows 24371 uses native callbacks and data-interface pointers; see [Risks](#risks).

## Status

|                           | Menu button | LAN switch                                                                  | Tested                                                                                                                                                                                                                                                         |
| ------------------------- | ----------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Linux** (Wine / Proton) | yes         | yes (`linux/wine-lan.c`)                                                    | the same page, switch and helper on one setup (Arch, GE-Proton 11-7 through umu): host, join from a second copy, offline start, full matches. This repository's `install.sh`/`wc3-lan-run` only on a test copy so far; Lutris, Bottles, Steam, Heroic: not yet |
| **macOS**                 | yes         | yes (one-shot `lldb` breakpoint)                                            | **no**: built from the method of the macOS test harness it came from, which was verified there, but not tried as a whole                                                                                                                                       |
| **Windows (24268)**       | yes         | by hand: `windows/lan-switch.ps1` (a debugger script), once per LAN session | **no**: the script was written without a Windows PC and has never been run                                                                                                                                                                                     |
| **Windows (24371)**       | yes         | `windows/lan-switch.ps1` starts a resident menu helper and in-game adapter | offline installation and two clients on one PC; separate-PC tests pending |

The original switch supports **3.0.0.24268**. Windows **3.0.1.24371** uses an adapter with a resident helper.
After a game patch it needs new values; `tools/` has what was used to find them.

## Why it's needed

In **3.0.0.24268**, Reforged still has LAN, but it's switched off three times over:

1. Battle.net tells the menus `enableLanMode: false`, so the Local Area Network button is hidden.
2. That button's screen asks for a newer network provider ("CSDK") that Battle.net has turned off,
   so it would list online games.
3. The classic LAN provider ("TCPN") still works, but no menu selects it. The only way in is to
   change which provider the game's `InitializeLocalNetProvider` handler selects, `'LOOP'` →
   `'TCPN'`, for one call. It must go straight back: the game checks its own code and quits about
   35 seconds into a match if the change is still there.

wc3-lan handles all three. Details: [docs/how-it-works.md](docs/how-it-works.md).

## Install

### Linux

Needs: Warcraft III 3.0.0.24268 in a Wine/Proton prefix that can already play it (3.0 needs
Wine 11.6+ or GE-Proton 11-7+ for its login), `gcc`, `python3`, `ss` (iproute2).

```sh
git clone <this repository> && cd wc3-lan
linux/install.sh --list      # which Warcraft III installs it finds
linux/install.sh             # install for those (or: linux/install.sh <prefix or game folder>)
```

It searches `~/.wine`, `~/Games`, Lutris, Bottles, Steam's `compatdata`, Heroic and umu. Close the
game and Battle.net first; it edits the prefix's registry (`"Allow Local Files"`, without which the
game ignores a local menu page).

Then start the game, or Battle.net, **through `linux/wc3-lan-run`**:

```sh
linux/wc3-lan-run <the command you start it with>
```

For Lutris, Steam, Bottles, Heroic and umu see [docs/linux-launchers.md](docs/linux-launchers.md).

### macOS (untested)

Needs: the Xcode command line tools (`xcode-select --install`) for `lldb`, and `python3`.

```sh
macos/install.sh            # or: macos/install.sh "/path/to/Warcraft III"
macos/wc3-lan-start         # the helper; start it before the game
```

If `lldb` can't attach to the game: `sudo DevToolsSecurity -enable`.

### Windows

For **3.0.1.24371**, use [Windows 24371](docs/windows-24371.md).
The following instructions describe the older 24268 debugger switch.

Install the menu page and `"Allow Local Files"`:

```powershell
powershell -ExecutionPolicy Bypass -File windows\install.ps1
```

Windows has no automatic LAN switch; it is done by hand each time you open the Local Area Network
screen. Read `windows/lan-switch.ps1` first, then, with the game on the main menu:

```powershell
powershell -ExecutionPolicy Bypass -File windows\lan-switch.ps1
```

When it says **Ready**, click Local Area Network. It attaches to the game as a debugger, changes one
CPU register for that one call (no game code is changed) and detaches.

## Use

1. Start the game (on Linux through `wc3-lan-run`; on Windows, run `windows/lan-switch.ps1` once
   it's on the main menu).
2. Press **Local Area Network**. The first time after the game starts this can take up to a minute
   (the game decrypts its code at startup, and the switch waits for that).
3. **Host**: create a game there. **Join**: pick it from the list.

### Offline start

Start `Warcraft III.exe` directly (not through Battle.net) with `--offline`, and the game skips the
Battle.net sign-in and goes straight to the main menu, as "Local Player":

```sh
linux/wc3-lan-run --offline umu-run "C:/Program Files (x86)/Warcraft III/_retail_/x86_64/Warcraft III.exe"
macos/wc3-lan-start --offline      # then start the game within 3 minutes (untested)
```

Don't add the game's `-editor` flag: it signs in with a saved token anyway. On Windows 24371, use
`windows\lan-switch.ps1 -Native24371 -Offline` as described in the Windows guide.

### Two copies on one machine

For example to test a map. Start both **offline**: neither signs in, so they can't log each other
out, and the order doesn't matter (the second is "Local Player 2"). Host from one copy's Local Area
Network screen and join from the other. How to start a second copy depends on the launcher; see
[docs/linux-launchers.md](docs/linux-launchers.md).

Two signed-in copies also work if the first has already used its LAN screen before the second
signs in: Battle.net allows one session per account, and the second sign-in logs the first out,
which the first copy's menus then ignore.

## Uninstall

`linux/install.sh --uninstall`, `macos/install.sh --uninstall` or `windows\install.ps1 -Uninstall`
put back the menu page that was there before. W3Champions also replaces the page every time it
starts; on Linux `wc3-lan-run` puts ours back on the next start, elsewhere run the installer again.

## Troubleshooting

The helper logs what happens: Linux `~/.cache/wc3-lan/helper.log` (or
`journalctl --user -u wc3-lan-helper` with `--service`), macOS `~/Library/Logs/wc3-lan-helper.log`.
On Windows, `lan-switch.ps1` prints what it did.

| What you see                                 | Likely cause                                                                                                                                                                  |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No Local Area Network button                 | The page isn't installed (or W3Champions replaced it), or `"Allow Local Files"` isn't set                                                                                     |
| The LAN screen lists online games            | Linux/macOS: the game wasn't started through `wc3-lan-run`, or the helper isn't running. Windows: `lan-switch.ps1` wasn't running (or didn't say "switched") when you clicked |
| `not armed: ...` in the log                  | Read the reason; `never armed` usually means another game build                                                                                                               |
| "Disconnected" box when a second copy starts | Start both copies `--offline`; or let the first use its LAN screen before the second signs in                                                                                 |
| `--offline` start still signs in             | The game was started with `-editor`, or not directly (Battle.net signs in)                                                                                                    |
| The game quits ~35 s into a match            | The code change wasn't put back; please report it with the log                                                                                                                |

## Risks

wc3-lan replaces the game's menu page and, only while the LAN screen sets up, changes one value in
the running game: on Linux in its code in memory, on macOS and Windows 24268 in a CPU register while a
debugger holds the game. Windows 24371 keeps native adapter callbacks in the game and a local menu
helper running; it replaces checked data-interface pointers without patching game code.
W3Champions does comparable things to its players' games. Still, it's not
something Blizzard offers, and you use it at your own risk.

## Layout

```
page/index.html            the menu page (Blizzard's menus + the LAN fixes + the offline start)
helper/wc3-lan-helper.py   arms the switch when the page asks; relays lobbies between local copies
linux/wine-lan.c           the Linux LAN switch, preloaded into the game
linux/wc3-lan-run          starts a launcher command with the switch and the helper
linux/install.sh           finds the game, installs the page, sets the registry value
macos/                     installer and helper start for macOS
windows/install.ps1        installs the page on Windows
windows/lan-switch.ps1     Windows entry: 24268 debugger switch or 24371 adapter/helper
tools/                     for a new game build: dump the decrypted code, find the LAN site
docs/                      how it works, Linux launchers
```

## Credits

Worked out while porting [wc3-slop-lan](https://github.com/Promises/wc3-slop-lan), a LAN test
harness for Warcraft III maps, to Linux; its macOS activation method is what `helper/` uses on
macOS. W3Champions' LAN mode showed the provider switch is possible.

## License

MIT; see [LICENSE](LICENSE).
