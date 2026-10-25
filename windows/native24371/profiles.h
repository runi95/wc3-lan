/* Recover menu profiles from the real names in the native classic join stream. */
typedef struct {
    unsigned char packet[512], names[32][64], pending[32];
    U32 used, total, remaining, published, errors, own_id;
} ProfileStream;
static void profile_name(ProfileStream *p, U32 id, const unsigned char *name, U32 limit) {
    if (!id || id >= 32 || !limit) return;
    U32 length = 0;
    while (length < limit && name[length]) ++length;
    if (!length || length == limit || length >= 64) return;
    for (U32 i = 0; i <= length; ++i) p->names[id][i] = name[i];
    p->pending[id] = 1;
}
static void profile_packet(ProfileStream *p, const unsigned char *own, int local) {
    const unsigned char *b = p->packet;
    U32 n = p->total;
    if (n > 512) return;
    if (b[1] == 6 && n > 10) profile_name(p, b[8], b + 9, n - 9);
    if (b[1] == 4 && n >= 7) {
        U32 offset = 6 + (U32)b[4] + ((U32)b[5] << 8);
        if (offset < n && b[offset] > 0 && b[offset] < 32) {
            p->own_id = b[offset];
            profile_name(p, p->own_id, own, 64);
        }
    }
    if (local && !p->own_id && n >= 11 && b[1] == 0x59 && b[4] == 4 && read32(b + 5) == n - 9 && b[9] == 8 &&
        b[10] > 0 && b[10] < 32) {
        p->own_id = b[10];
        profile_name(p, p->own_id, own, 64);
    }
}
static void profile_feed(ProfileStream *p, const unsigned char *data, U32 length, const unsigned char *own,
                         int local) {
    for (U32 i = 0; i < length; ++i) {
        unsigned char value = data[i];
        if (p->used < 4) {
            if (!p->used && value != 0xf7) {
                ++p->errors;
                continue;
            }
            p->packet[p->used++] = value;
            if (p->used == 4) {
                p->total = (U32)p->packet[2] | ((U32)p->packet[3] << 8);
                if (p->total < 4) {
                    p->used = 0;
                    ++p->errors;
                    continue;
                }
                p->remaining = p->total - 4;
                if (!p->remaining) {
                    profile_packet(p, own, local);
                    p->used = 0;
                }
            }
        } else {
            if (p->used < 512) p->packet[p->used] = value;
            ++p->used;
            if (!--p->remaining) {
                profile_packet(p, own, local);
                p->used = 0;
            }
        }
    }
}
static U32 profile_encode(unsigned char *out, U32 id, const unsigned char *name) {
    U32 length = 0;
    while (length < 64 && name[length]) ++length;
    if (!length || length == 64 || !id || id >= 32) return 0;
    U32 total = 13 + length;
    out[0] = 0xf7;
    out[1] = 0x59;
    out[2] = (unsigned char)total;
    out[3] = 0;
    out[4] = 3;
    write32(out + 5, total - 9);
    out[9] = 8;
    out[10] = (unsigned char)id;
    out[11] = 0x12;
    out[12] = (unsigned char)length;
    for (U32 i = 0; i < length; ++i) out[13 + i] = name[i];
    return total;
}
