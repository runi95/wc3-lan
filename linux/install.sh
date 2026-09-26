#!/usr/bin/env bash
# Installs wc3-lan for Warcraft III in one or more Wine/Proton prefixes.
#
#   linux/install.sh                  find Warcraft III in the usual places and install
#   linux/install.sh <path>           a Wine prefix, or anything inside the game folder
#   linux/install.sh --list           only show what would be used
#   linux/install.sh --service        also run the helper as a systemd user service (for launchers
#                                     that can only set LD_PRELOAD, not wrap the command)
#   linux/install.sh --uninstall      put back the pages that were there before
#
# For each game it puts page/index.html into <game>/_retail_/webui/ (keeping a page that was there
# as index.html.before-wc3-lan) and sets "Allow Local Files" in the prefix's user.reg, without which
# the game ignores a local page. It builds linux/wine-lan.so and writes
# ~/.config/wc3-lan/config for linux/wc3-lan-run. Close the game (and Battle.net) first.
set -euo pipefail
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
root="$(dirname "$here")"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/wc3-lan"
config="$config_dir/config"
exe_tail="_retail_/x86_64/Warcraft III.exe"

die() { echo "install.sh: $*" >&2; exit 1; }

# Warcraft III.exe files under the usual prefix locations. find doesn't follow symlinks, so
# dosdevices/z: (a link to /) is not searched.
find_games() {
  local base
  for base in "$HOME/.wine" "$HOME/Games" "$HOME/.local/share/lutris" \
              "$HOME/.local/share/bottles/bottles" "$HOME/.var/app/com.usebottles.bottles/data/bottles/bottles" \
              "$HOME/.local/share/Steam/steamapps/compatdata" "$HOME/.steam/steam/steamapps/compatdata" \
              "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata" \
              "$HOME/Games/Heroic/Prefixes" "$HOME/.local/share/umu"; do
    [[ -d "$base" ]] || continue
    find "$base" -maxdepth 10 -path "*/drive_c/*/$exe_tail" -type f 2>/dev/null
  done | sort -u
}

# The game's Warcraft III.exe for a path given on the command line
game_from_path() {
  local path
  path="$(realpath -e -- "$1")" || die "no such path: $1"
  if [[ -f "$path" && "$path" == *"/$exe_tail" ]]; then echo "$path"; return; fi
  if [[ "$path" == *"/drive_c/"* ]]; then
    local up="$path"
    while [[ "$up" != "/" ]]; do
      [[ -f "$up/$exe_tail" ]] && { echo "$up/$exe_tail"; return; }
      up="$(dirname "$up")"
    done
  fi
  find -L "$path" -maxdepth 8 -path "*/drive_c/*/$exe_tail" -type f 2>/dev/null | head -1 | grep . \
    || die "no Warcraft III ($exe_tail) under $path"
}

set_allow_local_files() {
  python3 - "$1" <<'PY'
import pathlib, re, sys, time
reg = pathlib.Path(sys.argv[1])
text = reg.read_text(encoding='utf-8', errors='surrogateescape')
header = '[Software\\\\Blizzard Entertainment\\\\Warcraft III]'
value = '"Allow Local Files"=dword:00000001'
start = text.find('\n' + header)
if start < 0:
    text = text.rstrip('\n') + f'\n\n{header} {int(time.time())}\n{value}\n'
else:
    end = text.find('\n\n', start + 1)
    end = len(text) if end < 0 else end
    section = text[start:end]
    if re.search(r'^"Allow Local Files"=.*$', section, re.M):
        section = re.sub(r'^"Allow Local Files"=.*$', value, section, flags=re.M)
    else:
        section += '\n' + value
    text = text[:start] + section + text[end:]
reg.write_text(text, encoding='utf-8', errors='surrogateescape')
PY
}

mode=install
service=0
unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/wc3-lan-helper.service"
paths=()
for arg in "$@"; do
  case "$arg" in
    --list) mode=list ;;
    --uninstall) mode=uninstall ;;
    --service) service=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) paths+=("$arg") ;;
  esac
done

if [[ $mode == uninstall ]]; then
  [[ -f "$config" ]] || die "nothing installed ($config is missing)"
  # shellcheck source=/dev/null
  source "$config"
  for webui in "${WEBUI_DIRS[@]}"; do
    if [[ -f "$webui/index.html.before-wc3-lan" ]]; then
      mv "$webui/index.html.before-wc3-lan" "$webui/index.html"; echo "restored $webui/index.html"
    elif grep -qs 'wc3-lan:' "$webui/index.html"; then
      rm "$webui/index.html"; echo "removed $webui/index.html"
    fi
  done
  rm -f "$config" "$here/wine-lan.so"
  if grep -qs 'wc3-lan helper' "$unit"; then
    systemctl --user disable --now wc3-lan-helper.service || true
    rm "$unit"
    systemctl --user daemon-reload
  fi
  echo "done. \"Allow Local Files\" stays set (W3Champions sets it too)."
  exit 0
fi

games=()
if (( ${#paths[@]} )); then
  for path in "${paths[@]}"; do games+=("$(game_from_path "$path")"); done
else
  mapfile -t games < <(find_games)
fi
(( ${#games[@]} )) || die "found no Warcraft III in the usual places; pass the prefix or game folder: $0 <path>"

echo "Warcraft III found:"
printf '  %s\n' "${games[@]}"
[[ $mode == list ]] && exit 0

for tool in gcc python3 ss pgrep; do command -v "$tool" >/dev/null || die "needs $tool"; done
if pgrep -x 'Warcraft III.ex' >/dev/null || pgrep -f 'Battle\.net\.exe' >/dev/null; then
  die "close Warcraft III and Battle.net first (the prefix's registry is edited)"
fi

webuis=()
for game in "${games[@]}"; do
  retail="${game%/x86_64/Warcraft III.exe}"
  prefix="${game%%/drive_c/*}"
  webui="$retail/webui"
  mkdir -p "$webui"
  if [[ -f "$webui/index.html" ]] && ! grep -qs 'wc3-lan:' "$webui/index.html" \
     && [[ ! -e "$webui/index.html.before-wc3-lan" ]]; then
    cp "$webui/index.html" "$webui/index.html.before-wc3-lan"
    echo "kept the page that was there: $webui/index.html.before-wc3-lan"
  fi
  cp "$root/page/index.html" "$webui/index.html"
  [[ -f "$prefix/user.reg" ]] || die "no user.reg in $prefix: is that the Wine prefix?"
  set_allow_local_files "$prefix/user.reg"
  echo "installed for $prefix"
  webuis+=("$webui")
done

gcc -O2 -Wall -shared -fPIC -fvisibility=hidden -o "$here/wine-lan.so" "$here/wine-lan.c"
mkdir -p "$config_dir"
{
  echo "# Written by wc3-lan's linux/install.sh; read by linux/wc3-lan-run"
  printf 'WEBUI_DIRS=('; printf ' %q' "${webuis[@]}"; printf ' )\n'
} > "$config"

if (( service )); then
  if [[ -e "$unit" ]] && ! grep -qs 'wc3-lan helper' "$unit"; then
    die "$unit exists and isn't wc3-lan's; not replacing it"
  fi
  mkdir -p "$(dirname "$unit")"
  printf '%s\n' '[Unit]' "Description=wc3-lan helper (arms Warcraft III's LAN switch)" '' '[Service]' \
    "ExecStart=/usr/bin/env python3 $root/helper/wc3-lan-helper.py" 'Restart=on-failure' '' \
    '[Install]' 'WantedBy=default.target' > "$unit"
  systemctl --user daemon-reload
  systemctl --user enable --now wc3-lan-helper.service
  echo "helper service installed and started (journalctl --user -u wc3-lan-helper)"
fi

cat <<EOF

Done. Now start the game (or Battle.net) through wc3-lan-run:

  $here/wc3-lan-run <the command you start it with>

See docs/linux-launchers.md for Lutris, Steam, Bottles, Heroic and umu. In the game, press
"Local Area Network" and host or join there.
EOF
