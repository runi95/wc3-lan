#!/usr/bin/env python3
"""Finds the LAN site in a decrypted Warcraft III image (tools/dump-image.c), for a new game build.

    python3 tools/find-lan-site.py /tmp/wc3-image.bin

Lists every `mov ecx,'LOOP'; call` (b9 50 4f 4f 4c e8), the Windows-x64 way of passing the provider
id to the function that selects it, with the code before it. On 3.0.0.24268 there were two:
  - one inside a general "select provider" function that first compares the id against NONE, BNET
    and LOOP (cmp edx,...);
  - a small stand-alone function that selects LOOP unconditionally: the InitializeLocalNetProvider
    handler, which is the one to use.
Then prints the values linux/wine-lan.c needs. Disassembly needs objdump (binutils).
"""
import re
import shutil
import struct
import subprocess
import sys

data = open(sys.argv[1], 'rb').read()
if data[:2] != b'MZ':
    sys.exit('not an image dump (no MZ header)')
pe = struct.unpack_from('<I', data, 0x3c)[0]
time_date = struct.unpack_from('<I', data, pe + 8)[0]
size_of_image = struct.unpack_from('<I', data, pe + 24 + 56)[0]
print(f'SIZE_OF_IMAGE 0x{size_of_image:x}  TIME_DATE 0x{time_date:x}')

for match in re.finditer(re.escape(bytes.fromhex('b9504f4f4ce8')), data):
    site = match.start()
    # The function start: the last run of int3 padding (cc) before the site
    pad = data.rfind(b'\xcc\xcc', max(0, site - 0x80), site)
    handler = pad + 2 if pad >= 0 else site - 9
    while data[handler] == 0xcc:
        handler += 1
    print(f'\nmov ecx,\'LOOP\' at RVA 0x{site:x} (immediate at 0x{site + 1:x}); function starts near 0x{handler:x}')
    print(f'  bytes from there to the call: {data[handler:site + 10].hex()}')
    if shutil.which('objdump'):
        listing = subprocess.run(['objdump', '-D', '-b', 'binary', '-m', 'i386:x86-64', '--no-show-raw-insn',
                                  f'--start-address={handler}', f'--stop-address={site + 15}', sys.argv[1]],
                                 capture_output=True, text=True).stdout
        print('\n'.join('  ' + line for line in listing.splitlines()[7:]))

print('\nFor the stand-alone handler, set in linux/wine-lan.c: SIZE_OF_IMAGE, TIME_DATE, HANDLER_RVA (its start),'
      '\nIMMEDIATE_RVA (the mov + 1) and handler[] (its bytes through the call after the mov).')
