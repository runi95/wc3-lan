#!/usr/bin/env bash
# Installs wc3-lan on macOS (untested as a whole; see README.md).
#
#   macos/install.sh [path to "Warcraft III" folder]    default: /Applications/Warcraft III
#   macos/install.sh --uninstall [path]
#
# Puts page/index.html into <game>/_retail_/webui/ (keeping a page that was there as
# index.html.before-wc3-lan) and sets "Allow Local Files" in the game's preferences. The LAN switch
# is a one-shot lldb breakpoint the helper sets when the menus ask (macos/wc3-lan-start).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$here")"

uninstall=0
[[ ${1:-} == --uninstall ]] && { uninstall=1; shift; }
game="${1:-/Applications/Warcraft III}"
webui="$game/_retail_/webui"
[[ -d "$game/_retail_" ]] || { echo "no Warcraft III at $game (pass its folder)" >&2; exit 1; }

if (( uninstall )); then
  if [[ -f "$webui/index.html.before-wc3-lan" ]]; then
    mv "$webui/index.html.before-wc3-lan" "$webui/index.html"
  elif grep -qs 'wc3-lan:' "$webui/index.html"; then
    rm "$webui/index.html"
  fi
  echo "done"
  exit 0
fi

pgrep -x 'Warcraft III' >/dev/null && { echo "close Warcraft III first" >&2; exit 1; }
mkdir -p "$webui"
if [[ -f "$webui/index.html" ]] && ! grep -qs 'wc3-lan:' "$webui/index.html" \
   && [[ ! -e "$webui/index.html.before-wc3-lan" ]]; then
  cp "$webui/index.html" "$webui/index.html.before-wc3-lan"
fi
cp "$root/page/index.html" "$webui/index.html"
# Unverified on macOS: the game keeps its settings under this domain, as its Windows build does in
# HKCU\Software\Blizzard Entertainment\Warcraft III
defaults write "com.blizzard.Warcraft III" "Allow Local Files" -int 1

command -v lldb >/dev/null || echo "note: lldb is missing; install the Xcode command line tools (xcode-select --install)"
cat <<EOF
Installed into $webui.

Before starting the game, start the helper (and leave it running):
  $here/wc3-lan-start
If lldb can't attach to the game the first time: sudo DevToolsSecurity -enable
EOF
