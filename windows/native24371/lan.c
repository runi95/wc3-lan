/* Warcraft III 3.0.1.24371: native LAN transport and discovery. */
typedef unsigned short U16;
typedef unsigned int U32;
typedef unsigned long long U64;
typedef long I32;
/* Keep the mapped adapter independent of the target process's CRT imports. */
void *memset(void *target, int value, U64 size) {
    volatile unsigned char *out = (volatile unsigned char *)target;
    for (U64 i = 0; i < size; ++i) out[i] = (unsigned char)value;
    return target;
}
void *memcpy(void *target, const void *source, U64 size) {
    volatile unsigned char *out = (volatile unsigned char *)target;
    const volatile unsigned char *in = (const volatile unsigned char *)source;
    for (U64 i = 0; i < size; ++i) out[i] = in[i];
    return target;
}
I32 _InterlockedCompareExchange(volatile I32 *, I32, I32);
I32 _InterlockedIncrement(volatile I32 *);
I32 _InterlockedDecrement(volatile I32 *);
I32 _InterlockedExchange(volatile I32 *, I32);
#pragma intrinsic(_InterlockedCompareExchange, _InterlockedIncrement, _InterlockedDecrement,                 \
                  _InterlockedExchange)
#define MAGIC 0x574333484f535431ULL
#define LOOP 0x4c4f4f50U
#define TCPN 0x5443504eU
#include "discovery.h"
#include "profiles.h"
typedef struct {
    U64 magic;
    U32 size, pid;
    volatile I32 command, state, active, unwind;
    U32 error, thread, bind_calls, unbind_calls, connect_calls, port;
    U64 expected_vtable, original[51];
    U64 get_pid, get_tid, get_context, initialize, shutdown, listen, enable, connect;
    U64 add_table, table, image_base;
    U32 table_count, started, old_mode, local_calls;
    U64 provider, session, counts;
    U32 baseline[6], baseline_ready;
    U64 connect_callback, listen_callback, local_connect, add_listing;
    U64 udp_create, udp_send, udp_vtable, udp_handle;
    U32 udp_port, udp_requested, udp_stage, udp_error, udp_closed;
    U32 udp_last, discovery, discovery_product, discovery_version;
    volatile I32 discovery_lock, poll_lock;
    U32 advert_valid, advert_length, searches, queued, dropped, listed;
    unsigned char advert_packet[432];
    LanGame advert_game, queue[16], peers[16];
    U32 peer_count;
    volatile I32 refresh;
    U32 broadcast_count, broadcasts[16];
    U64 create_timer, delete_timer, timer;
    U32 timer_started, timer_deleted;
    U64 create_event, wait_event, close_handle, get_error, timer_event;
    U32 timer_stopping;
    U64 remove_listing, get_tick;
    U32 seen[16], expired;
    U32 profile_enabled, profile_local;
    U64 profile_handle;
    unsigned char own_name[64];
    ProfileStream profile;
    U64 get_manager, get_name;
} Host;
__declspec(dllexport) volatile Host host_config = {MAGIC, sizeof(Host)};
__declspec(dllexport) const U32 host_config_size = sizeof(Host);
typedef U32 (*Id)(void);
typedef void *(*GetManager)(void);
typedef const unsigned char *(*GetName)(void *);
typedef void *(*GetContext)(U32);
typedef U64 (*Initialize)(U32, U32);
typedef void (*Shutdown)(U32);
typedef U64 (*Listen)(U16, void *, void *);
typedef void (*Enable)(U16, U32);
typedef U64 (*Connect)(U32, U16, U64, U64, U64, U32);
typedef void (*LocalConnect)(U64, U64, U64, U64, U32);
typedef unsigned char (*TransportCallback)(U64, U64, U32, U64, U64, U32, U64);
typedef U64 (*Method)(void *, U64, U64, U64, U64, U64);
typedef U64 (*Advertise)(void *, U64, U64, U64, U64, U32, U32, U16);
typedef U32 (*AddListing)(void *, void *, void *, U32, U32, U32, U32, void *, U32, U32, U32, void *, void *,
                          U32);
typedef U64 (*RemoveListing)(void *, void *, U32);
typedef void (*UdpCreate)(void *, U16, U16, void *, U64);
typedef void (*UdpSend)(U64, const void *, U32, U32, const void *);
typedef void (*SocketRef)(U64);
typedef void (*SocketCallback)(U64, U64, U64);
typedef int (*CreateTimer)(U64 *, U64, void *, void *, U32, U32, U32);
typedef int (*DeleteTimer)(U64, U64, U64);
typedef U64 (*CreateEvent)(U64, U32, U32, U64);
typedef U32 (*WaitEvent)(U64, U32);
typedef int (*CloseHandle)(U64);
typedef struct {
    U64 data, length, capacity;
    unsigned char text[16];
} NativeString;
typedef unsigned char (*AddTable)(void *, U32, U64);
static int valid(void *self) {
    volatile Host *p = &host_config;
    return self && p->magic == MAGIC && p->size == sizeof(Host) && p->get_pid &&
           ((Id)p->get_pid)() == p->pid && *(const U64 *)self == p->expected_vtable;
}
static int enter(void *self) {
    volatile Host *p = &host_config;
    if (!valid(self)) return 0;
    if (_InterlockedCompareExchange(&p->unwind, 1, 0) == 0) {
        if (!p->add_table || !((AddTable)p->add_table)((void *)p->table, p->table_count, p->image_base)) {
            p->error = 1;
            _InterlockedExchange(&p->unwind, 3);
            return 0;
        }
        _InterlockedExchange(&p->unwind, 2);
    }
    if (p->unwind != 2) return 0;
    p->thread = ((Id)p->get_tid)();
    return 1;
}
static U32 *mode(void *self) {
    volatile Host *p = &host_config;
    const unsigned char *root = ((GetContext)p->get_context)(13);
    if (!root) return (U32 *)0;
    const unsigned char *owner = *(const unsigned char *const *)(root + 0x20);
    if (!owner) return (U32 *)0;
    unsigned char *session = *(unsigned char *const *)(owner + 0xb8);
    if (!session || (p->provider && p->provider != (U64)self)) return (U32 *)0;
    U32 *result = (U32 *)(session + 0xc890);
    if (*result != LOOP && *result != TCPN) return (U32 *)0;
    if (p->session && p->session != (U64)session && (*result != LOOP || p->port)) return (U32 *)0;
    if (p->session != (U64)session) {
        p->provider = (U64)self;
        p->session = (U64)session;
        p->old_mode = *result;
    }
    return result;
}
static U64 original(U32 index, void *self, U64 a, U64 b, U64 c, U64 d, U64 e) {
    return ((Method)host_config.original[index])(self, a, b, c, d, e);
}
static void lan_lock(volatile Host *p) {
    while (_InterlockedCompareExchange(&p->discovery_lock, 1, 0) != 0) {
    }
}
static void lan_unlock(volatile Host *p) {
    _InterlockedExchange(&p->discovery_lock, 0);
}
static void lan_receive(volatile Host *p, U64 handle, const unsigned char *address, const unsigned char *data,
                        U32 length) {
    if (length == 16 && data[0] == 0xf7 && data[1] == 0x2f && data[2] == 16 && !data[3] &&
        read32(data + 4) == p->discovery_product && read32(data + 8) == p->discovery_version) {
        unsigned char packet[432];
        U32 size = 0;
        lan_lock(p);
        if (p->advert_valid) {
            size = p->advert_length;
            for (U32 i = 0; i < size; ++i) packet[i] = p->advert_packet[i];
        }
        lan_unlock(p);
        if (size && p->command == 1) {
            ((UdpSend)p->udp_send)(handle, packet, size, 1, address);
        }
    } else {
        LanGame game;
        if (!lan_decode(data, length, address, &game) || game.product != p->discovery_product ||
            game.version != p->discovery_version)
            return;
        lan_lock(p);
        if (!(p->advert_valid && game.counter == p->advert_game.counter && game.key == p->advert_game.key)) {
            U32 index = p->queued;
            for (U32 i = 0; i < p->queued; ++i) {
                if (lan_same((const LanGame *)&p->queue[i], &game)) {
                    index = i;
                    break;
                }
            }
            if (index < 16) {
                if (index < p->queued)
                    for (U32 i = 0; i < 16; ++i) game.address[i] = p->queue[index].address[i];
                const unsigned char *source = (const unsigned char *)&game;
                volatile unsigned char *dest = (volatile unsigned char *)&p->queue[index];
                for (U32 i = 0; i < sizeof(game); ++i) dest[i] = source[i];
                if (index == p->queued) ++p->queued;
            } else
                ++p->dropped;
        }
        lan_unlock(p);
    }
}
static void lan_poll(volatile Host *p, void *self) {
    if (!p->discovery || p->udp_stage != 1 || !p->udp_handle) return;
    U32 now = ((Id)p->get_tick)();
    /* An explicit menu refresh clears its cache. Emit fresh Add events. */
    if (_InterlockedExchange(&p->refresh, 0))
        for (U32 i = 0; i < p->peer_count; ++i) {
            if (p->peers[i].counter) {
                ((RemoveListing)p->remove_listing)(self, (void *)p->peers[i].address, p->peers[i].counter);
                p->peers[i].counter = 0;
            }
        }
    for (U32 item = 0; item < 16; ++item) {
        LanGame game;
        int available = 0;
        lan_lock(p);
        if (p->queued) {
            const volatile unsigned char *source = (const volatile unsigned char *)&p->queue[--p->queued];
            unsigned char *dest = (unsigned char *)&game;
            for (U32 i = 0; i < sizeof(game); ++i) dest[i] = source[i];
            available = 1;
        }
        lan_unlock(p);
        if (!available) break;
        U32 index = p->peer_count;
        for (U32 i = 0; i < p->peer_count; ++i) {
            if (lan_same((const LanGame *)&p->peers[i], &game)) {
                index = i;
                break;
            }
        }
        if (index == p->peer_count)
            for (U32 i = 0; i < p->peer_count; ++i) {
                if (!p->peers[i].counter) {
                    index = i;
                    break;
                }
            }
        if (index == 16) {
            ++p->dropped;
            continue;
        }
        if (index == p->peer_count) ++p->peer_count;
        if (p->peers[index].counter)
            for (U32 i = 0; i < 16; ++i) game.address[i] = p->peers[index].address[i];
        p->seen[index] = now;
        unsigned char *dest = (unsigned char *)&p->peers[index];
        for (U32 i = 0; i < sizeof(game); ++i) dest[i] = ((unsigned char *)&game)[i];
        LanGame *peer = (LanGame *)&p->peers[index];
        NativeString first = {0}, second = {0};
        first.data = (U64)&first.text;
        first.capacity = 0x800000000000000fULL;
        second.data = (U64)&second.text;
        second.capacity = 0x800000000000000fULL;
        /* Pointers required by the game are reconstructed in this process. */
        *(U64 *)(peer->info + 0x12c) = p->expected_vtable;
        *(U64 *)(peer->info + 0x144) = (U64)peer->address;
        U32 id = ((AddListing)p->add_listing)(self, peer->address, peer->address, game.counter, game.key,
                                              game.product, game.version, peer->info, game.current,
                                              game.total, 0, &first, &second, 1);
        if (id) ++p->listed;
    }
    for (U32 i = 0; i < p->peer_count; ++i) {
        if (p->peers[i].counter && now - p->seen[i] > 12000) {
            ((RemoveListing)p->remove_listing)(self, (void *)p->peers[i].address, p->peers[i].counter);
            p->peers[i].counter = 0;
            ++p->expired;
        }
    }
    unsigned char request[16], addresses[16][16];
    lan_search(request, p->discovery_product, p->discovery_version);
    U32 networks = p->broadcast_count;
    if (!networks || networks > 16) networks = 1;
    for (U32 network = 0; network < networks; ++network) {
        U32 broadcast = p->broadcast_count ? p->broadcasts[network] : 0xffffffff;
        for (U32 i = 0; i < 16; ++i) {
            for (U32 j = 0; j < 16; ++j) addresses[i][j] = 0;
            U16 port = (U16)(6112 + i);
            addresses[i][0] = 2;
            addresses[i][2] = (unsigned char)(port >> 8);
            addresses[i][3] = (unsigned char)port;
            write32(addresses[i] + 4, broadcast);
        }
        ((UdpSend)p->udp_send)(p->udp_handle, request, 16, 16, addresses);
    }
    ++p->searches;
}
__declspec(dllexport) void host_timer(void *context, unsigned char timed_out) {
    volatile Host *p = &host_config;
    _InterlockedIncrement(&p->active);
    if (context == (void *)p && p->command == 1 && p->started && valid((void *)p->provider))
        if (_InterlockedCompareExchange(&p->poll_lock, 1, 0) == 0) {
            lan_poll(p, (void *)p->provider);
            _InterlockedExchange(&p->poll_lock, 0);
        }
    _InterlockedDecrement(&p->active);
}
__declspec(dllexport) unsigned char host_udp(U64 handle, U64 address, U32 event, U64 user, U64 data,
                                             U32 length, U64 consumed) {
    volatile Host *p = &host_config;
    _InterlockedIncrement(&p->active);
    if (user != (U64)p || p->magic != MAGIC || p->size != sizeof(Host) || !p->get_pid ||
        ((Id)p->get_pid)() != p->pid)
        goto done;
    if (event == 0) {
        if (!handle || *(const U64 *)handle != p->udp_vtable) {
            p->udp_error = 1;
            p->udp_stage = 3;
            goto done;
        }
        if (p->udp_handle) {
            p->udp_error = 4;
            goto done;
        }
        ((SocketRef) * (const U64 *)(p->udp_vtable + 64))(handle);
        p->udp_handle = handle;
        p->udp_stage = 1;
    } else if (event == 1 && handle == p->udp_handle && data && consumed) {
        if (p->discovery && p->command == 1 && address) {
            lan_receive(p, handle, (const unsigned char *)address, (const unsigned char *)data, length);
        }
        *(U32 *)consumed += length;
    } else if (event == 2 || event == 3) {
        p->udp_error = 2;
        p->udp_stage = 3;
    }
done:
    _InterlockedDecrement(&p->active);
    return 1;
}
static int close_udp(volatile Host *p) {
    if (p->udp_requested && p->udp_stage == 0) return 0;
    U64 handle = p->udp_handle;
    if (handle) {
        if (*(const U64 *)handle != p->udp_vtable) {
            p->udp_error = 3;
            return 0;
        }
        ((SocketCallback) * (const U64 *)(p->udp_vtable + 16))(handle, 0, 0);
        ((SocketRef) * (const U64 *)(p->udp_vtable + 48))(handle);
        p->udp_handle = 0;
        p->udp_closed = 1;
        p->udp_stage = 2;
        ((SocketRef) * (const U64 *)(p->udp_vtable + 72))(handle);
    }
    return 1;
}
__declspec(dllexport) U64 host_poll(void *self, U64 a, U64 b, U64 c, U64 d, U64 e) {
    volatile Host *p = &host_config;
    U64 result = 0;
    _InterlockedIncrement(&p->active);
    if (!enter(self))
        result = original(4, self, a, b, c, d, e);
    else {
        U32 *current = mode(self);
        if (p->command == 2) {
            if (p->timer) {
                if (!p->timer_stopping) {
                    int deleted = ((DeleteTimer)p->delete_timer)(0, p->timer, p->timer_event);
                    if (!deleted && ((Id)p->get_error)() != 997) {
                        p->error = 6;
                        p->state = 4;
                        goto finish;
                    }
                    p->timer_stopping = 1;
                }
                if (((WaitEvent)p->wait_event)(p->timer_event, 0) != 0) {
                    p->state = 6;
                    goto finish;
                }
                p->timer = 0;
                p->timer_deleted = 1;
            }
            if (p->timer_event) {
                ((CloseHandle)p->close_handle)(p->timer_event);
                p->timer_event = 0;
            }
            if (p->discovery)
                for (U32 i = 0; i < p->peer_count; ++i) {
                    if (p->peers[i].counter) {
                        ((RemoveListing)p->remove_listing)(self, (void *)p->peers[i].address,
                                                           p->peers[i].counter);
                        p->peers[i].counter = 0;
                    }
                }
            if (!close_udp(p)) {
                p->state = 6;
                goto finish;
            }
            if (p->port) ((Enable)p->enable)((U16)p->port, 0);
            if (p->started) {
                ((Shutdown)p->shutdown)(3);
                p->started = 0;
            }
            if (current) *current = p->old_mode;
            p->state = 3;
            result = 1;
        } else if (!current) {
            p->error = 2;
            p->state = 4;
        } else if (p->command == 1) {
            if (!p->started) {
                if (p->counts) {
                    for (U32 i = 0; i < 6; ++i) p->baseline[i] = ((const U32 *)p->counts)[i];
                    p->baseline_ready = 1;
                }
                if (!((Initialize)p->initialize)(0, 3)) {
                    p->error = 3;
                    p->state = 4;
                } else
                    p->started = 1;
            }
            if (p->started) {
                *current = TCPN;
                p->state = 2;
                result = 1;
                if (p->discovery) _InterlockedExchange(&p->refresh, 1);
                if (p->udp_port && !p->udp_requested) {
                    p->udp_requested = 1;
                    p->discovery_product = *(const U32 *)((unsigned char *)self + 0x30);
                    p->discovery_version = *(const U32 *)((unsigned char *)self + 0x34);
                    ((UdpCreate)p->udp_create)((void *)0, (U16)p->udp_port,
                                               (U16)(p->udp_last ? p->udp_last : p->udp_port),
                                               (void *)&host_udp, (U64)p);
                }
                if (p->discovery && !p->timer_started) {
                    U64 timer = 0;
                    p->timer_event = ((CreateEvent)p->create_event)(0, 1, 0, 0);
                    if (!p->timer_event || !p->create_timer ||
                        !((CreateTimer)p->create_timer)(&timer, 0, (void *)&host_timer, (void *)p, 500, 2000,
                                                        0)) {
                        p->error = 5;
                        p->state = 4;
                    } else {
                        p->timer = timer;
                        p->timer_started = 1;
                    }
                }
            }
        }
    }
finish:
    _InterlockedDecrement(&p->active);
    return result;
}
__declspec(dllexport) unsigned char host_accepted(U64 a, U64 b, U32 event, U64 d, U64 data, U32 length,
                                                  U64 handled) {
    volatile Host *p = &host_config;
    _InterlockedIncrement(&p->active);
    unsigned char result = ((TransportCallback)p->listen_callback)(a, b, event, d, data, length, handled);
    _InterlockedDecrement(&p->active);
    return result;
}
__declspec(dllexport) U64 host_bind(void *self, U16 first, U16 last, void *callback) {
    volatile Host *p = &host_config;
    U64 result = 0;
    _InterlockedIncrement(&p->active);
    if (!enter(self) || !p->started || p->command != 1)
        result = original(16, self, first, last, (U64)callback, 0, 0);
    else {
        U32 *current = mode(self);
        if (current && callback && first && first < last) {
            if (!p->listen_callback || p->listen_callback == (U64)callback) {
                p->listen_callback = (U64)callback;
                callback = (void *)&host_accepted;
            }
            for (U32 port = first; port < last; ++port) {
                if (((Listen)p->listen)((U16)port, callback, (void *)0)) {
                    *current = TCPN;
                    p->port = port;
                    ++p->bind_calls;
                    result = port;
                    break;
                }
            }
        }
    }
    _InterlockedDecrement(&p->active);
    return result;
}
__declspec(dllexport) void host_unbind(void *self, U16 port) {
    volatile Host *p = &host_config;
    _InterlockedIncrement(&p->active);
    if (enter(self) && p->started && port == p->port) {
        ((Enable)p->enable)(port, 0);
        p->port = 0;
        ++p->unbind_calls;
    } else
        original(17, self, port, 0, 0, 0, 0);
    _InterlockedDecrement(&p->active);
}
__declspec(dllexport) unsigned char host_connected(U64 a, U64 b, U32 event, U64 d, U64 data, U32 length,
                                                   U64 handled) {
    volatile Host *p = &host_config;
    _InterlockedIncrement(&p->active);
    U32 before = event == 1 && p->profile_enabled && handled ? *(const U32 *)handled : 0;
    unsigned char result = ((TransportCallback)p->connect_callback)(a, b, event, d, data, length, handled);
    if (p->profile_enabled && p->command == 1 && p->started && ((Id)p->get_pid)() == p->pid) {
        if (event == 0) {
            memset((void *)&p->profile, 0, sizeof(ProfileStream));
            p->profile_handle = a;
        } else if (event == 1 && a == p->profile_handle && data) {
            ProfileStream *stream = (ProfileStream *)&p->profile;
            U32 received = handled ? *(const U32 *)handled - before : 0;
            if (received > length) {
                ++stream->errors;
                received = 0;
            }
            profile_feed(stream, (const unsigned char *)data, received, (const unsigned char *)p->own_name,
                         p->profile_local);
            /* The real receive must end at a packet boundary before appending
               metadata to the engine parser; incomplete packets stay untouched. */
            if (!stream->used)
                for (U32 id = 1; id < 32; ++id) {
                    if (stream->pending[id]) {
                        unsigned char packet[80];
                        U32 consumed = 0;
                        U32 size = profile_encode(packet, id, stream->names[id]);
                        stream->pending[id] = 0;
                        if (size) {
                            unsigned char accepted = ((TransportCallback)p->connect_callback)(
                                a, b, 1, d, (U64)packet, size, (U64)&consumed);
                            if (accepted && consumed == size)
                                ++stream->published;
                            else
                                ++stream->errors;
                        }
                    }
                }
        }
    }
    _InterlockedDecrement(&p->active);
    return result;
}
__declspec(dllexport) U64 host_connect(void *self, const unsigned char *address, U64 cb, U64 user, U64 flags,
                                       U32 timeout) {
    volatile Host *p = &host_config;
    U64 result = 0;
    _InterlockedIncrement(&p->active);
    if (!enter(self) || !p->started || p->command != 1)
        result = original(15, self, (U64)address, cb, user, flags, timeout);
    else {
        U32 *current = mode(self);
        if (current && address && *(const U16 *)address == 2) {
            U16 port = (U16)(((U32)address[2] << 8) | address[3]);
            if (port) {
                U32 ip = *(const U32 *)(address + 4);
                if (p->profile_enabled) {
                    p->profile_local = !ip && port == p->port;
                    void *manager = ((GetManager)p->get_manager)();
                    const unsigned char *name =
                        manager ? ((GetName)p->get_name)(manager) : (const unsigned char *)0;
                    U32 n = 0;
                    if (name)
                        while (n < 63 && name[n]) {
                            p->own_name[n] = name[n];
                            ++n;
                        }
                    p->own_name[n] = 0;
                }
                if (cb && (!p->connect_callback || p->connect_callback == cb)) {
                    p->connect_callback = cb;
                    cb = (U64)&host_connected;
                }
                *current = TCPN;
                ++p->connect_calls;
                if (!ip && port == p->port && p->listen_callback) {
                    /* The creator joins with the engine's private self packet.
                       Keep its native local channel; remote peers use OS TCP. */
                    ++p->local_calls;
                    ((LocalConnect)p->local_connect)(cb, (U64)&host_accepted, user, flags, timeout);
                    result = 1;
                } else
                    result = ((Connect)p->connect)(ip, port, cb, user, flags, timeout);
            }
        }
    }
    _InterlockedDecrement(&p->active);
    return result;
}
__declspec(dllexport) U32 host_identity(void *self) {
    if (valid(self) && host_config.started) return TCPN;
    return (U32)original(49, self, 0, 0, 0, 0, 0);
}
__declspec(dllexport) U64 host_advertise(void *s, U64 a, U64 b, U64 c, U64 info, U32 product, U32 protocol,
                                         U16 port) {
    volatile Host *p = &host_config;
    _InterlockedIncrement(&p->active);
    if (valid(s)) {
        if (p->discovery && info) {
            LanGame game = {0};
            game.counter = (U32)b;
            game.key = (U32)c;
            game.product = product;
            game.version = protocol;
            game.current = 1;
            game.address[0] = 2;
            game.address[2] = (unsigned char)(port >> 8);
            game.address[3] = (unsigned char)port;
            const unsigned char *source = (const unsigned char *)info;
            for (U32 field = 0; field < 3; ++field) {
                U32 start = field == 0 ? 0 : (field == 1 ? 32 : 48),
                    limit = field == 0 ? 32 : (field == 1 ? 16 : 320);
                for (U32 i = 0; i < limit && source[start + i]; ++i) game.info[start + i] = source[start + i];
            }
            for (U32 i = 0x170; i < 0x178; ++i) game.info[i] = source[i];
            game.total = read32(game.info + 0x170);
            unsigned char packet[432];
            U32 length = lan_info(packet, &game);
            lan_lock(p);
            const unsigned char *raw = (const unsigned char *)&game;
            volatile unsigned char *dest = (volatile unsigned char *)&p->advert_game;
            for (U32 i = 0; i < sizeof(game); ++i) dest[i] = raw[i];
            for (U32 i = 0; i < length; ++i) p->advert_packet[i] = packet[i];
            p->advert_length = length;
            p->advert_valid = length != 0;
            lan_unlock(p);
        }
    }
    U64 result = ((Advertise)p->original[18])(s, a, b, c, info, product, protocol, port);
    _InterlockedDecrement(&p->active);
    return result;
}
__declspec(dllexport) U64 host_update(void *s, U64 a, U64 b, U64 c, U64 d) {
    volatile Host *p = &host_config;
    if (valid(s) && p->discovery) {
        LanGame game;
        unsigned char packet[432];
        lan_lock(p);
        unsigned char *dest = (unsigned char *)&game;
        const volatile unsigned char *source = (const volatile unsigned char *)&p->advert_game;
        for (U32 i = 0; i < sizeof(game); ++i) dest[i] = source[i];
        if (game.counter == (U32)b) {
            game.current = (U32)c;
            game.total = (U32)d;
            U32 length = lan_info(packet, &game);
            for (U32 i = 0; i < sizeof(game); ++i) ((volatile unsigned char *)&p->advert_game)[i] = dest[i];
            for (U32 i = 0; i < length; ++i) p->advert_packet[i] = packet[i];
            p->advert_length = length;
            p->advert_valid = length != 0;
        }
        lan_unlock(p);
    }
    return original(19, s, a, b, c, d, 0);
}
__declspec(dllexport) U64 host_unadvertise(void *s, U64 a, U64 b, unsigned char started) {
    volatile Host *p = &host_config;
    if (valid(s) && p->discovery) {
        lan_lock(p);
        if (p->advert_game.counter == (U32)b) p->advert_valid = 0;
        lan_unlock(p);
    }
    return original(20, s, a, b, started, 0, 0);
}
