/* Classic W3GS LAN datagrams. No captured pointers or padding go on the wire. */
typedef struct {
    unsigned char address[16], info[376];
    U32 counter, key, product, version, current, total;
} LanGame;
static int lan_same(const LanGame *a, const LanGame *b) {
    if (a->counter != b->counter || a->key != b->key || a->product != b->product ||
        a->version != b->version || a->address[2] != b->address[2] || a->address[3] != b->address[3])
        return 0;
    for (U32 i = 0; i < 32; ++i) {
        if (a->info[i] != b->info[i]) return 0;
        if (!a->info[i]) return 1;
    }
    return 0;
}
static U32 read32(const unsigned char *b) {
    return (U32)b[0] | ((U32)b[1] << 8) | ((U32)b[2] << 16) | ((U32)b[3] << 24);
}
static void write32(unsigned char *b, U32 n) {
    for (U32 i = 0; i < 4; ++i) b[i] = (unsigned char)(n >> (8 * i));
}
static U32 lan_search(unsigned char *b, U32 product, U32 version) {
    b[0] = 0xf7;
    b[1] = 0x2f;
    b[2] = 16;
    b[3] = 0;
    write32(b + 4, product);
    write32(b + 8, version);
    write32(b + 12, 0);
    return 16;
}
static U32 lan_info(unsigned char *b, const LanGame *g) {
    if (!g->counter || !g->total || g->total > 28 || g->current > g->total) return 0;
    b[0] = 0xf7;
    b[1] = 0x30;
    write32(b + 4, g->product);
    write32(b + 8, g->version);
    write32(b + 12, g->counter);
    write32(b + 16, g->key);
    U32 n = 20;
    for (U32 field = 0; field < 3; ++field) {
        U32 start = field == 0 ? 0 : (field == 1 ? 32 : 48),
            limit = field == 0 ? 32 : (field == 1 ? 16 : 320);
        U32 i = 0;
        for (; i < limit && g->info[start + i]; ++i) b[n++] = g->info[start + i];
        if (i == limit) return 0;
        b[n++] = 0;
    }
    write32(b + n, g->total);
    write32(b + n + 4, read32(g->info + 0x174));
    write32(b + n + 8, 1);
    write32(b + n + 12, g->total - g->current);
    write32(b + n + 16, 0);
    /* W3GS uses a little-endian port, sockaddr uses network byte order. */
    b[n + 20] = g->address[3];
    b[n + 21] = g->address[2];
    n += 22;
    b[2] = (unsigned char)n;
    b[3] = (unsigned char)(n >> 8);
    return n;
}
static int lan_decode(const unsigned char *b, U32 length, const unsigned char *sender, LanGame *g) {
    if (length < 43 || length > 432 || b[0] != 0xf7 || b[1] != 0x30 ||
        ((U32)b[2] | ((U32)b[3] << 8)) != length || !sender || *(const U16 *)sender != 2)
        return 0;
    /* A fresh zeroed game prevents process pointers and stack padding crossing. */
    unsigned char *out = (unsigned char *)g;
    for (U32 i = 0; i < sizeof(*g); ++i) out[i] = 0;
    g->product = read32(b + 4);
    g->version = read32(b + 8);
    g->counter = read32(b + 12);
    g->key = read32(b + 16);
    U32 n = 20;
    for (U32 field = 0; field < 3; ++field) {
        U32 start = field == 0 ? 0 : (field == 1 ? 32 : 48),
            limit = field == 0 ? 32 : (field == 1 ? 16 : 320);
        U32 i = 0;
        while (n < length && b[n]) {
            if (i + 1 >= limit) return 0;
            g->info[start + i++] = b[n++];
        }
        if (n == length) return 0;
        ++n;
    }
    if (n + 22 != length) return 0;
    U32 total = read32(b + n), open = read32(b + n + 12);
    if (!g->counter || !total || total > 28 || open > total || !(b[n + 20] | b[n + 21])) return 0;
    g->total = total;
    g->current = total - open;
    write32(g->info + 0x170, total);
    write32(g->info + 0x174, read32(b + n + 4));
    g->address[0] = 2;
    g->address[2] = b[n + 21];
    g->address[3] = b[n + 20];
    for (U32 i = 4; i < 8; ++i) g->address[i] = sender[i];
    return 1;
}
