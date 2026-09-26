# How it works

Everything here was found on Warcraft III **3.0.0.24268**.

## The pieces

```
 game's browser                    helper (127.0.0.1:8790)            the game
 page/index.html  ── GET /arm ──▶  arms the switch        ─────────▶  handler selects TCPN once
        │         ◀── {"ok"} ───                                            │
        └── InitializeLocalNetProvider ─────────────────────────────────▶  LAN socket opens,
                                                                            'LOOP' goes back
```

### The menu page (`page/index.html`)

The game draws its menus as a web page: `<game>/_retail_/webui/index.html` loads Blizzard's
`GlueManager.js`, which talks to the game over a websocket. The game only loads a page from that
folder when `"Allow Local Files"` is set (Windows: `HKCU\Software\Blizzard Entertainment\Warcraft III`;
Wine: the same key in the prefix's `user.reg`). W3Champions uses the same folder for its own page.

The page wraps that websocket and changes these messages:

| Message | Direction | Change |
|---|---|---|
| `FeatureFlags` | game → menus | `enableLanMode` set to `true`: the Local Area Network button appears |
| `InitializeNetProvider {"id":"CSDK"}` | menus → game | what the LAN screen asks for; CSDK is off on Battle.net's side. The page asks the helper to arm the switch, then sends `InitializeLocalNetProvider {}` instead |
| `LoggedOut` | game → menus | dropped once the LAN screen has been used, or offline (see below) |
| `LoginDoorClose` | menus → game | with an offline ticket: replaced by the offline start (see below) |

### The LAN switch

`InitializeLocalNetProvider`'s handler selects the provider `'LOOP'` (single player). Changing the
argument to `'TCPN'` for that call gives the real LAN provider: the game opens UDP 16000 (or the
next free port) and lists/hosts LAN games the classic way. In the Windows build the handler is:

```
RVA 0x118bca0   sub  rsp,0x58
      118bca4   call ...
      118bca9   mov  ecx,0x4c4f4f50     ; 'LOOP'  ->  0x5443504e 'TCPN'
      118bcae   call SelectNetProvider
```

**It has to be one-shot.** The game checks its own code: with the change left in, it quit (cleanly,
no crash) 34-35 seconds into every match. The change is made just before the handler runs and
undone as soon as the new LAN socket exists.

- **Linux (`linux/wine-lan.c`).** Under Wine a Linux debugger can't attach (Wine lets only
  wineserver ptrace its processes), so the change is made from inside the game by a preloaded
  library. The game's code is encrypted on disk (entropy 8.0) and its image range is `PROT_NONE`;
  the decrypted image lives in shared memory, with a writable view (`rw-s`, `SizeOfImage` long,
  starting with `MZ`). Writing the immediate there changes the code that runs. The library waits
  for decryption, checks `SizeOfImage`, `TimeDateStamp` and the handler's 19 bytes, and talks to
  the helper through a file per game (`~/.cache/wc3-lan/<pid>`, or `$WC3_LAN_DIR`): created by the
  helper, `armed` written by the library, removed when `'LOOP'` is back.
- **macOS (helper).** A one-shot `lldb` breakpoint on the call (`0x100d3c6a2` in the macOS binary,
  UUID `C26F6D81-...`) rewrites `rdi` from `'LOOP'` to `'TCPN'` and detaches, so the code is never
  modified. This is wc3-slop-lan's verified method; wc3-lan's use of it is untested.

### The helper (`helper/wc3-lan-helper.py`)

The page can't reach the game, so it asks the helper. `/arm` arms every running game that has no
LAN socket yet (the one that asked switches at once; others put their code back after 60 s) and
answers once armed. `/log` prints a line from the page.

## Offline start

The menus send `LoginDoorClose` when the login screen's doors close, which starts the Battle.net
sign-in. Asked for one start (`--offline` leaves a ticket; the page asks the helper's `/offline`,
waiting at most 5 s), the page sends instead:

1. `RemoveAuthenticationModal`: closes the game's login window (a browser window the game draws
   itself, over the menus),
2. `InitializeLocalNetProvider`: the local provider, no Battle.net,
3. `SetLocalPlayerName`: "Local Player" ("Local Player 2", ... for more copies),

and tells the menus the game is at `MAIN_MENU` (a copy of the last real `SetGlueScreen`, with the
screen changed). The game still starts a sign-in of its own a moment later; while offline the page
drops its "Login Queue" dialog and answers its `SetOverlayScreen AUTHENTICATION_OVERLAY` with another
`RemoveAuthenticationModal` (the menus get `NO_OVERLAY`). That sign-in never completes.

This comes from a modified `playOffline` handler shared in the community, which does the same and
then starts and leaves a throwaway local game (Booty Bay) to get to the main menu; telling the menus
directly turned out to be enough. With the game's `-editor` flag the saved-token sign-in happens
regardless, so an offline start has to go without it.

## Two copies on one machine

- **Same account.** Battle.net allows one session per account, and the menus' own "Play offline"
  signs in too. Started with the offline start, neither copy signs in. Otherwise the second copy's
  sign-in logs the first out, which covers its menus with a "Disconnected" box; the page drops that
  `LoggedOut` once the LAN screen has been used (not before, so normal online play still hears about
  it). A copy that lost its session plays LAN normally.
- **Finding the lobby.** Linux doesn't deliver a machine's own broadcasts back to it, so the second
  copy's search never reaches the first. While two or more copies run, the helper sends each LAN
  port on loopback (16000-16003) a `SearchGame` every second and passes every `GameInfo` answer to
  the other ports. A client connects to the answer's sender (127.0.0.1) at the TCP port inside it.
- **Starting the second copy** depends on the launcher. Plain Wine: just start it again (same
  wineserver). umu/Proton: both need `UMU_CONTAINER_NSENTER=1`, or the second waits for the first to
  exit; a second container on the same wineserver (`PROTON_VERB=run`) broke the game's browser.

## Windows

The page and `"Allow Local Files"` are the same as elsewhere. The switch is **`windows/lan-switch.ps1`**,
the macOS method done with Windows' debugging API (untested: written without a Windows PC):

1. Search the game's executable memory (read-only) for the handler,
   `48 83 EC 58 E8 ?? ?? ?? ?? B9 50 4F 4F 4C E8`. The code runs from a decrypted copy, not from the
   image on disk, so it is found at runtime rather than as module base + RVA.
2. Attach (`DebugActiveProcess`, with `DebugSetProcessKillOnExit(false)`) and, at the attach
   breakpoint while every thread is stopped, set a hardware breakpoint (`Dr0`, `Dr7` bit 0) on the
   `call` after `mov ecx,'LOOP'` in every thread.
3. When it fires (`EXCEPTION_SINGLE_STEP` at that address), change `rcx` from `0x4c4f4f50` to
   `0x5443504e` if it holds that, clear the breakpoint everywhere and detach
   (`DebugActiveProcessStop`). Other exceptions go back to the game unhandled.

It is run by hand, not through the helper, so the page's request to `/arm` fails and it sends
`InitializeLocalNetProvider` at once, which is what the breakpoint waits for.

Not tried: an in-process DLL doing the Linux method (find the writable view of the decrypted image,
change the immediate, put it back). It would need to be native code loaded into the game, e.g. as a
proxy DLL in the game folder, and whether Windows has the same writable view is unknown.

## Things that were tried and don't work

- Leaving `'TCPN'` in the code: the game quits 34-35 s into a match.
- The menus' `PlayOffline` to avoid the second sign-in: it signs in too (the offline start above
  avoids it by never sending `PlayOffline` or `LoginDoorClose`).
- `PlayOffline` from the online main menu: ignored.
- Starting a second Proton container on the same prefix (`PROTON_VERB=run`): the game's browser
  crashes (Fontconfig "out of memory").
