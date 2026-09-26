/* wc3-lan's LAN switch for Warcraft III 3.0.0.24268 under Wine/Proton (Linux). LD_PRELOADed into
 * the game by linux/wc3-lan-run; see docs/how-it-works.md.
 *
 * The game's InitializeLocalNetProvider handler selects the provider 'LOOP'; 'TCPN' is the real LAN
 * provider. This changes the handler's `mov ecx,'LOOP'` (RVA 0x118bca9) to 'TCPN' when asked, and
 * back as soon as the game has opened a LAN socket: the game checks its own code, and with the
 * change left in it quits 34-35 s into a match. No debugger: under Wine only wineserver may ptrace.
 *
 * The code is encrypted on disk and the image range is PROT_NONE; the decrypted image lives in
 * shared memory, with a writable view (rw-s, SizeOfImage long, starting with MZ). Writing there
 * changes the code that runs.
 *
 * Handshake through $WC3_LAN_DIR/<pid> (default ~/.cache/wc3-lan):
 *  1. The helper creates the file.
 *  2. A thread here checks the build (SizeOfImage, TimeDateStamp) and the exact bytes around the
 *     site (they appear once decryption is done), notes the game's LAN sockets, makes the change
 *     and writes "armed" into the file.
 *  3. The page lets the menus' request through.
 *  4. Once there is a new UDP socket on 16000-16099, 'LOOP' goes back and the file is removed
 *     (after 60 s without one, too).
 * Other processes, builds or bytes are left alone. Messages go to stderr. */
#define _GNU_SOURCE
#include <dirent.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define SIZE_OF_IMAGE  0xe155000u
#define TIME_DATE      0x6aa4de70u
#define HANDLER_RVA    0x118bca0u /* sub rsp,0x58; call ...; mov ecx,'LOOP'; call SelectNetProvider */
#define IMMEDIATE_RVA  0x118bcaau
static const unsigned char handler[] = {
    0x48, 0x83, 0xec, 0x58, 0xe8, 0x37, 0xbd, 0x39, 0x00,
    0xb9, 0x50, 0x4f, 0x4f, 0x4c, 0xe8, 0x8d, 0xe3, 0x39, 0x00,
};
static const unsigned char loop_id[] = { 0x50, 0x4f, 0x4f, 0x4c }; /* 'LOOP' as an imm32 */
static const unsigned char tcpn_id[] = { 0x4e, 0x50, 0x43, 0x54 }; /* 'TCPN' */

enum { WAIT, NOT_GAME, GAME };

static int which_process(void)
{
    static int known;
    char cmdline[4096] = {0};
    /* Decided once: the game's main thread exits early under Wine, and from then on
     * /proc/self/cmdline reads empty while the game runs on */
    if (known) return known;
    FILE *f = fopen("/proc/self/cmdline", "r");
    if (!f) return WAIT;
    if (!fread(cmdline, 1, sizeof(cmdline) - 1, f)) cmdline[0] = 0;
    fclose(f);
    if (!cmdline[0]) return WAIT;
    /* Wine replaces argv with the Windows command line once the process is up; until then
     * argv[0] is Wine's loader */
    if (strncmp(cmdline, "C:\\", 3) && strncmp(cmdline, "c:\\", 3)) {
        const char *base = strrchr(cmdline, '/');
        base = base ? base + 1 : cmdline;
        return strncmp(base, "wine", 4) || !strcmp(base, "wineserver") ? NOT_GAME : WAIT;
    }
    known = strstr(cmdline, "\\x86_64\\Warcraft III.exe") ? GAME : NOT_GAME;
    return known;
}

/* The writable view of the decrypted image, or NULL while there is none yet. */
static unsigned char *find_image(void)
{
    char line[4096];
    unsigned char *found = NULL;
    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return NULL;
    while (!found && fgets(line, sizeof(line), maps)) {
        unsigned long start, end;
        char perms[8];
        if (sscanf(line, "%lx-%lx %7s", &start, &end, perms) != 3) continue;
        if (strcmp(perms, "rw-s") || end - start != SIZE_OF_IMAGE) continue;
        unsigned char *view = (unsigned char *)start;
        if (view[0] != 'M' || view[1] != 'Z') continue;
        uint32_t pe, time_date, size;
        memcpy(&pe, view + 0x3c, 4);
        if (pe > 0x1000) continue;
        memcpy(&time_date, view + pe + 8, 4);
        memcpy(&size, view + pe + 24 + 56, 4);
        if (time_date == TIME_DATE && size == SIZE_OF_IMAGE) found = view;
    }
    fclose(maps);
    return found;
}

/* The inodes of this process's UDP sockets on LAN ports (16000-16099), at most `max`. */
static int lan_sockets(unsigned long *out, int max)
{
    unsigned long lan[64];
    int count = 0, found = 0;
    char line[512];
    FILE *udp = fopen("/proc/self/net/udp", "r");
    if (!udp) return 0;
    while (count < 64 && fgets(line, sizeof(line), udp)) {
        unsigned port;
        unsigned long inode;
        if (sscanf(line, " %*d: %*x:%x %*x:%*x %*x %*x:%*x %*x:%*x %*x %*u %*u %lu", &port, &inode) == 2 &&
            port >= 16000 && port < 16100)
            lan[count++] = inode;
    }
    fclose(udp);
    DIR *fds = opendir("/proc/self/fd");
    struct dirent *entry;
    while (count && found < max && fds && (entry = readdir(fds))) {
        char path[300], target[64];
        unsigned long inode;
        snprintf(path, sizeof(path), "/proc/self/fd/%s", entry->d_name);
        ssize_t len = readlink(path, target, sizeof(target) - 1);
        if (len <= 0) continue;
        target[len] = 0;
        if (sscanf(target, "socket:[%lu]", &inode) != 1) continue;
        for (int i = 0; i < count; i++)
            if (lan[i] == inode) out[found++] = inode;
    }
    if (fds) closedir(fds);
    return found;
}

/* Has a LAN socket appeared that is not among the `count` in `before`? */
static int new_lan_socket(const unsigned long *before, int count)
{
    unsigned long now[16];
    int n = lan_sockets(now, 16);
    for (int i = 0; i < n; i++) {
        int old = 0;
        for (int j = 0; j < count; j++) old |= now[i] == before[j];
        if (!old) return 1;
    }
    return 0;
}

static void switch_once(const char *request)
{
    unsigned char *image = NULL;
    int tries;

    /* The view appears before decryption is done: wait for the verified bytes */
    for (tries = 0; tries < 1200; tries++, usleep(250000)) {
        if ((image = find_image()) && !memcmp(image + HANDLER_RVA, handler, sizeof(handler))) break;
        image = NULL;
    }
    if (!image) {
        fprintf(stderr, "wine-lan: pid %d: the provider handler never showed the verified bytes; "
                        "not switching to LAN\n", (int)getpid());
        unlink(request);
        return;
    }
    unsigned long before[16];
    int old = lan_sockets(before, 16);
    memcpy(image + IMMEDIATE_RVA, tcpn_id, sizeof(tcpn_id));
    FILE *armed = fopen(request, "w");
    if (armed) {
        fputs("armed\n", armed);
        fclose(armed);
    }
    for (tries = 0; tries < 600 && !new_lan_socket(before, old); tries++) usleep(100000);
    memcpy(image + IMMEDIATE_RVA, loop_id, sizeof(loop_id));
    if (tries < 600)
        fprintf(stderr, "wine-lan: pid %d: switched to the LAN provider; handler restored\n", (int)getpid());
    else
        fprintf(stderr, "wine-lan: pid %d: no LAN socket within 60 s of the change; handler restored\n",
                (int)getpid());
    unlink(request);
}

static void *watch(void *arg)
{
    char request[4096];
    const char *dir = getenv("WC3_LAN_DIR");
    const char *home = getenv("HOME");
    (void)arg;
    if (dir && *dir)
        snprintf(request, sizeof(request), "%s/%d", dir, (int)getpid());
    else if (home && *home)
        snprintf(request, sizeof(request), "%s/.cache/wc3-lan/%d", home, (int)getpid());
    else
        return NULL;
    for (;;) {
        int process = which_process();
        if (process == NOT_GAME) return NULL;
        if (process == GAME && !access(request, F_OK)) switch_once(request);
        usleep(100000);
    }
}

__attribute__((constructor)) static void start(void)
{
    sigset_t all, old;
    pthread_t thread;
    if (which_process() == NOT_GAME) return;
    /* Wine directs its signals at specific threads; keep process-wide ones off this one */
    sigfillset(&all);
    pthread_sigmask(SIG_BLOCK, &all, &old);
    if (!pthread_create(&thread, NULL, watch, NULL)) pthread_detach(thread);
    pthread_sigmask(SIG_SETMASK, &old, NULL);
}
