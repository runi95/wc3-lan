#!/usr/bin/env python3
"""wc3-lan's helper: arms the one-shot LAN switch when the menus' "Local Area Network" screen asks.

The page (page/index.html) runs inside the game's browser and can't touch the game, so it asks here
over HTTP on 127.0.0.1:8790:

    GET  /arm   switch the running game's InitializeLocalNetProvider handler to TCPN for one call;
                answers {"ok": true} once the switch is in place, and the page then sends it
    GET  /offline  {"offline": true, "name": ...} once per ticket left by `--offline` (in the
                request folder as offline-*, valid 3 min): that game's page skips the Battle.net
                sign-in and goes straight to the main menu. Otherwise {"offline": false}.
    POST /log   one line from the page, printed here

How /arm works depends on the platform:
    Linux (Wine/Proton)  file handshake with linux/wine-lan.so, which is preloaded into the game
    macOS                a one-shot lldb breakpoint that rewrites the argument (needs lldb)
    Windows              not here: windows/lan-switch.ps1 is run by hand instead

With several games running, every game without a LAN socket yet is armed: the one that asked
switches at once, the others put their code back after 60 s.

Relay: Linux doesn't deliver a machine's own LAN broadcasts back to it, so a second game on this
machine never hears the first one's lobby. While two or more games run, this asks each LAN port on
loopback (16000-16003) for its game every second and passes the answers to the other ports.

    python3 wc3-lan-helper.py [--port 8790]
"""
import argparse
import json
import os
import pathlib
import platform
import socket
import struct
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SYSTEM = platform.system()
LAN_PORTS = (16000, 16001, 16002, 16003)
# W3GS SearchGame as a 3.0.0.24268 client sends it: product PX3W, protocol version 10200
SEARCH = bytes([0xF7, 0x2F, 0x10, 0x00]) + b'PX3W' + struct.pack('<II', 10200, 0)


def run(*command):
    return subprocess.run(command, capture_output=True, text=True).stdout


# --- which games run, and which already have a LAN socket ----------------------------------------

def games():
    name = {'Linux': 'Warcraft III.ex', 'Darwin': 'Warcraft III'}.get(SYSTEM)
    return run('pgrep', '-x', name).split() if name else []


def lan_ports(pid):
    """The UDP ports 16000-16099 the game holds."""
    if SYSTEM == 'Linux':
        lines = [line.split() for line in run('ss', '-uanpH').splitlines() if f'pid={pid},' in line]
        ports = [fields[3].rsplit(':', 1)[1] for fields in lines if len(fields) > 3]
    else:
        ports = [line.split()[8].rsplit(':', 1)[1] for line in run('lsof', '-a', '-nP', '-p', pid, '-iUDP').splitlines()[1:]
                 if len(line.split()) > 8]
    return [int(port) for port in ports if port.isdigit() and 16000 <= int(port) < 16100]


# --- Linux: handshake with wine-lan.so ------------------------------------------------------------

REQUESTS = pathlib.Path(os.environ.get('WC3_LAN_DIR') or pathlib.Path.home() / '.cache' / 'wc3-lan')


def take_offline_ticket():
    """The oldest ticket under 3 minutes old; older ones belong to games that never reached their
    login screen and must not send a later normal start offline."""
    for ticket in sorted(REQUESTS.glob('offline-*'), key=lambda path: path.stat().st_mtime):
        fresh = time.time() - ticket.stat().st_mtime < 180
        ticket.unlink(missing_ok=True)
        if fresh:
            return True
    return False


def arm_linux(pids):
    REQUESTS.mkdir(parents=True, exist_ok=True)
    requests = [REQUESTS / pid for pid in pids]
    for _ in range(600):
        # A game still armed from an earlier request keeps its file; a missing file means its last
        # switch is over, so it is asked again
        states = []
        for request in requests:
            try:
                states.append('armed' in request.read_text())
            except FileNotFoundError:
                request.write_text('')
                states.append(False)
        if all(states):
            return None
        time.sleep(0.25)
    for request in requests:
        request.unlink(missing_ok=True)
    return 'the game never armed the switch: was it started through linux/wc3-lan-run?'


# --- macOS: a one-shot lldb breakpoint (the method of wc3-slop-lan's harness/activate.sh) ----------

MAC_GAME = '/Applications/Warcraft III/_retail_/x86_64/Warcraft III.app/Contents/MacOS/Warcraft III'
MAC_UUID = 'C26F6D81-E702-3F44-B57E-91DD7C438B22'
MAC_SITE = '0x100d3c6a2'  # call SelectNetProvider; the mov edi,'LOOP' is the 5 bytes before
MAC_BYTES = (0xd3c69d, bytes.fromhex('bf504f4f4ce8092b4f00'))


def arm_macos(pids):
    game = os.environ.get('WC3_LAN_GAME', MAC_GAME)
    if MAC_UUID not in run('dwarfdump', '--uuid', game):
        return f'{game} is not Warcraft III 3.0.0.24268 (the build the address was taken from)'
    offset, expected = MAC_BYTES
    with open(game, 'rb') as binary:
        binary.seek(offset)
        if binary.read(len(expected)) != expected:
            return 'the provider handler bytes differ from what was verified'
    for pid in pids:
        script = tempfile.NamedTemporaryFile('w', suffix='.lldb', delete=False)
        script.write(f"breakpoint set --shlib \"Warcraft III\" --address {MAC_SITE} --one-shot true "
                     f"--condition '(unsigned)$rdi == 0x4c4f4f50'\ncontinue\n"
                     f"register write rdi 0x5443504e\nprocess detach\n")
        script.close()
        lldb = subprocess.Popen(['lldb', '--batch', '-p', pid, '-s', script.name],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        attached = threading.Event()

        def watch(lldb=lldb, attached=attached, script=script.name):
            for line in lldb.stdout:
                if line.startswith('(lldb) continue'):
                    attached.set()
                if 'detached' in line:
                    print(f'game {pid}: switched to the LAN provider; lldb detached', flush=True)
            os.unlink(script)
        threading.Thread(target=watch, daemon=True).start()
        if not attached.wait(30):
            lldb.terminate()
            return 'lldb did not attach (Xcode command line tools? `sudo DevToolsSecurity -enable`?)'
        # The page sends the trigger right after this answer; stop waiting if it never comes
        threading.Timer(60, lambda lldb=lldb: lldb.poll() is None and lldb.terminate()).start()
    return None


def arm():
    running = games()
    if SYSTEM == 'Windows':
        return {'ok': False, 'error': 'on Windows the switch is windows/lan-switch.ps1, run by hand'}
    if len(running) > 1:
        running = [pid for pid in running if not lan_ports(pid)]
    if not running:
        return {'ok': False, 'error': 'no Warcraft III waiting for LAN'}
    error = arm_linux(running) if SYSTEM == 'Linux' else arm_macos(running)
    if error:
        return {'ok': False, 'error': error}
    print(f'armed: {", ".join(running)}', flush=True)
    return {'ok': True}


# --- relay for two games on one machine ------------------------------------------------------------

def relay():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    sock.settimeout(0.1)
    seen = set()
    while True:
        time.sleep(1)
        if len(games()) < 2:
            continue
        for port in LAN_PORTS:
            sock.sendto(SEARCH, ('127.0.0.1', port))
        answers, end = {}, time.time() + 0.4
        while time.time() < end:
            try:
                data, (_, source) = sock.recvfrom(4096)
            except (socket.timeout, ConnectionResetError):
                continue
            if data[:2] == b'\xf7\x30':
                answers[source] = data
        for source, info in answers.items():
            if source not in seen:
                name = info[20:info.index(b'\0', 20)].decode(errors='replace')
                print(f'relaying the LAN game {name!r} on port {source}', flush=True)
            for port in LAN_PORTS:
                if port != source:
                    sock.sendto(info, ('127.0.0.1', port))
        seen = set(answers)


class Handler(BaseHTTPRequestHandler):
    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page went away (a match started, the menus reloaded)

    def do_GET(self):
        if self.path.startswith('/arm'):
            self.reply(arm())
        elif self.path.startswith('/offline'):
            offline = take_offline_ticket()
            count = len(games())  # each copy its own name, to tell them apart in a lobby
            name = 'Local Player' if count <= 1 else f'Local Player {count}'
            if offline:
                print(f'offline start as {name!r}', flush=True)
            self.reply({'offline': offline, 'name': name})
        else:
            self.reply({'ok': True})

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        print('page: ' + self.rfile.read(length).decode(errors='replace')[:2000], flush=True)
        self.reply({'ok': True})

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='wc3-lan helper')
    parser.add_argument('--port', type=int, default=8790, help='the page expects 8790')
    port = parser.parse_args().port
    threading.Thread(target=relay, daemon=True).start()
    print(f'wc3-lan helper on 127.0.0.1:{port} ({SYSTEM})', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
