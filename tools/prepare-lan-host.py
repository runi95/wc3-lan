"""Prepare pinned public host sources for a Windows build; no downloads or execution."""

import argparse
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--flo", type=Path, required=True)
args = parser.parse_args()
for root, commit in (
    (args.source, "553c9ce798d1971edcda81ec1c3bbb00f046c667"),
    (args.flo, "6db3a4010fab0b0b29824a61f2c9c956f97fd211"),
):
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != commit:
        raise ValueError("External host source commit differs: " + str(root))
manifest = args.source / "host/Cargo.toml"
text = manifest.read_text(encoding="utf-8")
lines = text.splitlines()
for name, folder in (
    ("flo-w3gs", "w3gs"),
    ("flo-w3map", "w3map"),
    ("flo-util", "util"),
):
    index = [i for i, line in enumerate(lines) if line.startswith(name + " = ")]
    if len(index) != 1:
        raise ValueError("No unique host dependency: " + name)
    relative = os.path.relpath(args.flo / "crates" / folder, manifest.parent).replace(
        "\\", "/"
    )
    lines[index[0]] = name + ' = { path = "' + relative + '" }'
manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
discovery = args.source / "host/src/discovery.rs"
text = discovery.read_text(encoding="utf-8")
old = 'socket.send_to(&answer, ("127.0.0.1", from.port())).await.ok();'
new = "socket.send_to(&answer, from).await.ok();"
if old in text and text.count(old) == 1:
    text = text.replace(old, new)
elif text.count(new) != 1:
    raise ValueError("External host discovery source differs")
text = text.replace(
    "// The client listens on its own port on loopback, whatever address it searched from",
    "// Reply to the requesting client, including clients on another LAN machine",
)
discovery.write_text(text, encoding="utf-8")
print(
    "Prepared pinned host dependencies and discovery replies. Build with cargo build --release in host/."
)
