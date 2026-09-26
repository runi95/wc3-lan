# Linux launchers

wc3-lan needs two things when the game runs: `linux/wine-lan.so` preloaded into it, and the helper
running. `linux/wc3-lan-run <command>` does both, so wherever your launcher lets you put something
in front of the command, use it. Where it only lets you set environment variables, set
`LD_PRELOAD` yourself and run the helper as a service (`linux/install.sh --service`).

Games started by Battle.net inherit the preload, so wrapping Battle.net is enough.

Only the umu setup below has been tested. The others follow from how each launcher works; if one
needs something different, please report it.

| Launcher | Where | What |
|---|---|---|
| Plain Wine | your command | `linux/wc3-lan-run wine "C:/Program Files (x86)/Battle.net/Battle.net Launcher.exe"` (with `WINEPREFIX=...`) |
| umu | your command | `linux/wc3-lan-run umu-run <exe>` |
| Lutris | game → Configure → System options → **Command prefix** | `/path/to/wc3-lan/linux/wc3-lan-run` |
| Steam (non-Steam game with Proton) | game → Properties → **Launch options** | `/path/to/wc3-lan/linux/wc3-lan-run %command%` |
| Heroic | game settings → Advanced → **Wrapper command** | `/path/to/wc3-lan/linux/wc3-lan-run` |
| Bottles | bottle → Settings → **Environment variables** | `LD_PRELOAD=/path/to/wc3-lan/linux/wine-lan.so`, plus `linux/install.sh --service` |

`wine-lan.so` is built by `install.sh` (or on the first `wc3-lan-run`). If you set `LD_PRELOAD`
yourself, build it once with `linux/install.sh`.

## Flatpak (Steam, Bottles)

A Flatpak app sees a different home folder, so the library and the helper would look for their
request files in different places. Give both the same folder the app can reach, e.g.
`WC3_LAN_DIR=$HOME/.var/app/<app id>/cache/wc3-lan` for the game (launch options / environment)
and for the helper (systemd `Environment=`, or when starting it by hand). Untested.

## Two copies on one machine

| Launcher | How |
|---|---|
| Plain Wine, Lutris, Bottles | start the game a second time; both run on the prefix's one wineserver |
| umu / Proton | set `UMU_CONTAINER_NSENTER=1` for **both** copies (the first included); umu then starts the second inside the first's container. Without it the second waits for the first to exit |
| Steam | Steam starts one copy of a game; start the second outside Steam (e.g. umu with the same prefix and `UMU_CONTAINER_NSENTER=1`, which the first then also needs) |

Start both with `wc3-lan-run --offline` and the order doesn't matter; without it, host from the
first copy's Local Area Network screen before starting the second (see README).

For an offline start the game has to be started directly (`Warcraft III.exe`, without `-editor`);
a start through Battle.net signs in. With umu, for example:

```sh
export WINEPREFIX=/path/to/prefix GAMEID=umu-warcraft3 UMU_CONTAINER_NSENTER=1
export PROTONPATH=/path/to/GE-Proton11-7-x86_64   # any Proton with the 3.0 login fix
linux/wc3-lan-run --offline umu-run "C:/Program Files (x86)/Warcraft III/_retail_/x86_64/Warcraft III.exe"
```

(and the same command again for the second copy).
