/* Writes Warcraft III's decrypted image to a file, for finding the LAN site in a new game build
 * with tools/find-lan-site.py. Linux/Wine only. LD_PRELOAD it into the game:
 *
 *   gcc -O2 -shared -fPIC -o dump-image.so tools/dump-image.c
 *   WC3_DUMP=/tmp/wc3-image.bin LD_PRELOAD=$PWD/dump-image.so <start the game as usual>
 *
 * 60 s after start (WC3_DUMP_DELAY), the game process writes its writable image view: an rw-s
 * mapping that starts with "MZ" and is as long as the image's SizeOfImage. Only reads the game's
 * own memory; the game keeps running. */
#define _GNU_SOURCE
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void *dump(void *arg)
{
    char cmdline[4096] = {0}, line[4096];
    const char *out = getenv("WC3_DUMP");
    const char *delay = getenv("WC3_DUMP_DELAY");
    (void)arg;
    sleep(delay ? (unsigned)atoi(delay) : 60);

    FILE *f = fopen("/proc/self/cmdline", "r");
    if (f) { if (!fread(cmdline, 1, sizeof(cmdline) - 1, f)) cmdline[0] = 0; fclose(f); }
    if (strncmp(cmdline, "C:\\", 3) || !strstr(cmdline, "\\x86_64\\Warcraft III.exe")) return NULL;

    FILE *maps = fopen("/proc/self/maps", "r");
    while (maps && fgets(line, sizeof(line), maps)) {
        unsigned long start, end;
        char perms[8];
        uint32_t pe, size;
        if (sscanf(line, "%lx-%lx %7s", &start, &end, perms) != 3 || strcmp(perms, "rw-s")) continue;
        const unsigned char *view = (const unsigned char *)start;
        if (end - start < 0x1000 || view[0] != 'M' || view[1] != 'Z') continue;
        memcpy(&pe, view + 0x3c, 4);
        if (pe > 0x1000) continue;
        memcpy(&size, view + pe + 24 + 56, 4);
        if (size != end - start) continue;
        FILE *o = fopen(out, "wb");
        if (o) { fwrite(view, 1, end - start, o); fclose(o); }
        fprintf(stderr, "dump-image: wrote %lx-%lx (%lu bytes) to %s\n", start, end, end - start, out);
        break;
    }
    if (maps) fclose(maps);
    return NULL;
}

__attribute__((constructor)) static void start(void)
{
    sigset_t all, old;
    pthread_t thread;
    if (!getenv("WC3_DUMP")) return;
    sigfillset(&all);
    pthread_sigmask(SIG_BLOCK, &all, &old);
    if (!pthread_create(&thread, NULL, dump, NULL)) pthread_detach(thread);
    pthread_sigmask(SIG_SETMASK, &old, NULL);
}
