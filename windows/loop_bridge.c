/* MIT. Narrow, data-driven LOOP listing/join callback; no target text patches.
 * The external broker owns publication of the vtable slot and this image's life.
 */
typedef unsigned char U8;
typedef unsigned short U16;
typedef unsigned int U32;
typedef unsigned long long U64;
typedef long I32;

I32 _InterlockedCompareExchange(volatile I32 *, I32, I32);
I32 _InterlockedExchange(volatile I32 *, I32);
I32 _InterlockedIncrement(volatile I32 *);
I32 _InterlockedDecrement(volatile I32 *);
#pragma intrinsic(_InterlockedCompareExchange)
#pragma intrinsic(_InterlockedExchange)
#pragma intrinsic(_InterlockedIncrement)
#pragma intrinsic(_InterlockedDecrement)

#define OFFSET(T, F) ((U32) __builtin_offsetof(T, F))
#define MAGIC 0x57434c414e303031ULL
#define ABI 2
#define LOOP 0x4c4f4f50U
#define TCPN 0x5443504eU
#define MAX_LISTINGS 32

typedef struct {
    U16 family, port;
    U32 address;
    U8 zero[8];
} LanEndpoint;
typedef struct {
    U64 pointer, length, capacity;
    U8 small[16];
} NativeString;
typedef struct {
    U32 native_tags[5];
    I32 native_result;
    U64 reserved;
    LanEndpoint endpoint;
    U8 information[376];
    NativeString name_a, name_b;
    U64 padding;
} LanListing;

typedef struct {
    U64 magic;
    U32 abi, size;
    volatile I32 state;
    U32 error;
    volatile I32 active_calls, unwind_state;
    U32 operation, listing_count;
    U64 generation;
    U32 entered_tid, entered_count;
    U64 expected_vtable, original, get_context, add_listing, connect;
    U64 get_tid, rtl_add_table, runtime_table, image_base;
    U32 runtime_count, reserved;
    U32 owner_data_offset, current_session_offset, mode_offset;
    U32 provider_tag_a_offset, provider_tag_b_offset, context_slot;
    U64 output_provider, output_session;
    U64 bound_provider, bound_session;
    U32 target_port, reserved_port;
    LanEndpoint target;
    U64 result;
    LanListing listings[MAX_LISTINGS];
} LanContext;

_Static_assert(sizeof(NativeString) == 40, "native string size");
_Static_assert(sizeof(LanListing) == 512, "native listing envelope size");

__declspec(dllexport) volatile LanContext lan_context = {MAGIC, ABI, sizeof(LanContext)};
__declspec(dllexport) const U32 lan_layout[] = {sizeof(LanContext),
                                                sizeof(LanListing),
                                                OFFSET(LanContext, state),
                                                OFFSET(LanContext, operation),
                                                OFFSET(LanContext, generation),
                                                OFFSET(LanContext, expected_vtable),
                                                OFFSET(LanContext, runtime_count),
                                                OFFSET(LanContext, owner_data_offset),
                                                OFFSET(LanContext, output_provider),
                                                OFFSET(LanContext, bound_provider),
                                                OFFSET(LanContext, target_port),
                                                OFFSET(LanContext, target),
                                                OFFSET(LanContext, result),
                                                OFFSET(LanContext, listings)};

typedef U64 (*Original)(U64, U64, U64, U64, U64, U64);
typedef U64 (*GetContext)(U32);
typedef U32 (*GetTid)(void);
typedef U8 (*RegisterTable)(U64, U32, U64);
typedef int (*AddListing)(U64, LanEndpoint *, U8 *, U32, U32, U32, U32, U8 *, U32, U32, U32,
                          NativeString *, NativeString *, U32);
typedef U64 (*Connect)(U32, U32, U64, U64, U64, U64);

static void empty_string(NativeString *value) {
    value->pointer = (U64)value->small;
    value->length = 0;
    value->capacity = 0x800000000000000fULL;
    for (U32 i = 0; i < 16; i++)
        value->small[i] = 0;
}

__declspec(dllexport) U64 loop_callback(U64 provider, U64 argument, U64 a2, U64 a3, U64 a4,
                                        U64 a5) {
    volatile LanContext *c = &lan_context;
    U64 answer = 0, owner = 0, session = 0;
    U32 failure = 0;
    I32 previous;
    _InterlockedIncrement(&c->active_calls);
    if (c->magic != MAGIC || c->abi != ABI || c->size != sizeof(LanContext) || !c->context_slot ||
        c->context_slot > 64) {
        failure = 1;
        goto failed;
    }
    previous = _InterlockedCompareExchange(&c->state, 2, 1);
    if (previous != 1) {
        if (previous == 0 || previous == 3) {
            Original original = (Original)c->original;
            if (original)
                answer = original(provider, argument, a2, a3, a4, a5);
        }
        goto exit;
    }
    _InterlockedIncrement((volatile I32 *)&c->entered_count);
    if (!c->get_tid || !c->rtl_add_table || !c->get_context) {
        failure = 1;
        goto failed;
    }
    c->entered_tid = ((GetTid)c->get_tid)();
    if (_InterlockedCompareExchange(&c->unwind_state, 1, 0) == 0) {
        U8 registered =
            ((RegisterTable)c->rtl_add_table)(c->runtime_table, c->runtime_count, c->image_base);
        _InterlockedExchange(&c->unwind_state, registered ? 2 : 3);
    }
    if (c->unwind_state != 2) {
        failure = 9;
        goto failed;
    }
    if (!provider || *(U64 *)provider != c->expected_vtable) {
        failure = 2;
        goto failed;
    }
    owner = ((GetContext)c->get_context)(c->context_slot);
    if (!owner) {
        failure = 3;
        goto failed;
    }
    owner = *(U64 *)(owner + c->owner_data_offset);
    if (!owner) {
        failure = 3;
        goto failed;
    }
    session = *(U64 *)(owner + c->current_session_offset);
    if (!session) {
        failure = 3;
        goto failed;
    }
    if (*(U32 *)(session + c->mode_offset) != LOOP) {
        failure = 4;
        goto failed;
    }
    c->output_provider = provider;
    c->output_session = session;
    if (c->operation == 0)
        goto done;
    if (c->operation == 1) {
        if (!c->listing_count || c->listing_count > MAX_LISTINGS || !c->add_listing) {
            failure = 5;
            goto failed;
        }
        for (U32 i = 0; i < c->listing_count; i++) {
            LanListing *row = (LanListing *)&c->listings[i];
            if (row->endpoint.family != 2 || !row->endpoint.port) {
                failure = 5;
                goto failed;
            }
            empty_string(&row->name_a);
            empty_string(&row->name_b);
            int accepted = ((AddListing)c->add_listing)(
                provider, &row->endpoint, row->information, row->native_tags[0],
                row->native_tags[1], *(U32 *)(provider + c->provider_tag_a_offset),
                *(U32 *)(provider + c->provider_tag_b_offset), row->information,
                row->native_tags[2], row->native_tags[3], row->native_tags[4], &row->name_a,
                &row->name_b, 999);
            row->native_result = accepted;
            if (accepted <= 0) {
                failure = 6;
                goto failed;
            }
        }
        goto done;
    }
    if (c->operation == 2) {
        if (provider != c->bound_provider || session != c->bound_session || !argument ||
            !c->target_port || c->target_port > 65535 || !c->connect) {
            failure = 7;
            goto failed;
        }
        for (U32 i = 0; i < sizeof(LanEndpoint); i++)
            if (((U8 *)argument)[i] != ((volatile U8 *)&c->target)[i]) {
                failure = 8;
                goto failed;
            }
        *(U32 *)(session + c->mode_offset) = TCPN;
        answer = ((Connect)c->connect)(c->target.address, c->target_port, a2, a3, a4, a5);
        c->result = answer;
        goto done;
    }
    failure = 10;
failed:
    c->error = failure;
    _InterlockedExchange(&c->state, 4);
    goto exit;
done:
    _InterlockedExchange(&c->state, 3);
exit:
    /* After active_calls reaches zero, the epilogue must not access this context.
       The broker still retains the executable image for the entire game process. */
    _InterlockedDecrement(&c->active_calls);
    return answer;
}
