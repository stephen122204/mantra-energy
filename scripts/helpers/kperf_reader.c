/*
 * alems_kperf_reader.c
 *
 * Minimal helper for A-LEMS: reads Apple Silicon PMU counters via
 * kperf/kperfdata private frameworks. Prints JSON to stdout.
 *
 * Build:  cc -O2 -o kperf_reader kperf_reader.c
 * Usage:  sudo ./kperf_reader
 * Output: {"instructions":123456,"cycles":789012,"l1d_miss_ld":34,
 *          "l1d_miss_st":12,"l1d_miss_nonspec":30,"l1d_tlb_access":5000}
 *
 * Exit codes: 0 = success, 1 = framework load failed,
 *             2 = kpep db failed, 3 = counter config failed,
 *             4 = counter read failed
 *
 * Requires root (kpc_set_config needs EPERM bypass).
 * System-wide counters (all CPUs, all processes).
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <dlfcn.h>

/* sysctl for CPU count - add include if compiler warns */
extern int sysctl(int *, unsigned int, void *, size_t *, void *, size_t);

/* ---------- kperf/kperfdata function pointer typedefs ---------- */

/* Counter classes bitmask */
#define KPC_CLASS_FIXED          (1u << 0)
#define KPC_CLASS_CONFIGURABLE   (1u << 1)
#define KPC_CLASS_FIXED_AND_CFG  (KPC_CLASS_FIXED | KPC_CLASS_CONFIGURABLE)

/* Max counters: 2 fixed + 8 configurable on Apple Silicon */
#define MAX_COUNTERS 10

/* kperf functions */
typedef int (*kpc_get_counter_count_fn)(uint32_t classes);
typedef int (*kpc_set_counting_fn)(uint32_t classes);
typedef int (*kpc_get_counting_fn)(void);
typedef int (*kpc_set_config_fn)(uint32_t classes, uint64_t *config);
typedef int (*kpc_get_config_fn)(uint32_t classes, uint64_t *config);
typedef int (*kpc_get_cpu_counters_fn)(int all_cpus, uint32_t classes,
                                       int cpu_number, uint64_t *buf);
typedef int (*kpc_force_all_ctrs_set_fn)(int enable);

/* kpep functions (event database lookup) */
typedef int (*kpep_db_create_fn)(const char *path, void **db_out);
typedef void (*kpep_db_free_fn)(void *db);
typedef int (*kpep_db_event_fn)(void *db, const char *name, void **ev_out);
typedef int (*kpep_event_name_fn)(void *ev, const char **name_out);
typedef int (*kpep_event_alias_fn)(void *ev, const char **alias_out);
typedef int (*kpep_event_description_fn)(void *ev, const char **desc_out);

/*
 * kpep_config functions: manage an event configuration object
 * that maps event names to hardware counter slots.
 */
typedef int (*kpep_config_create_fn)(void *db, void **cfg_out);
typedef void (*kpep_config_free_fn)(void *cfg);
typedef int (*kpep_config_add_event_fn)(void *cfg, void **ev, uint32_t flag,
                                        uint32_t *err);
typedef int (*kpep_config_kpc_fn)(void *cfg, uint64_t *buf,
                                   size_t buf_size);
typedef int (*kpep_config_kpc_count_fn)(void *cfg, size_t *count_out);
typedef int (*kpep_config_kpc_classes_fn)(void *cfg, uint32_t *classes_out);
typedef int (*kpep_config_kpc_map_fn)(void *cfg, size_t *buf,
                                      size_t buf_size);

/* ---------- Global function pointers ---------- */
static kpc_get_counter_count_fn   kpc_get_counter_count;
static kpc_set_counting_fn        kpc_set_counting;
static kpc_get_counting_fn        kpc_get_counting;
static kpc_set_config_fn          kpc_set_config;
static kpc_get_config_fn          kpc_get_config;
static kpc_get_cpu_counters_fn    kpc_get_cpu_counters;
static kpc_force_all_ctrs_set_fn  kpc_force_all_ctrs_set;

static kpep_db_create_fn          kpep_db_create;
static kpep_db_free_fn            kpep_db_free;
static kpep_db_event_fn           kpep_db_event;
static kpep_config_create_fn      kpep_config_create;
static kpep_config_free_fn        kpep_config_free;
static kpep_config_add_event_fn   kpep_config_add_event;
static kpep_config_kpc_fn         kpep_config_kpc;
static kpep_config_kpc_count_fn   kpep_config_kpc_count;
static kpep_config_kpc_classes_fn kpep_config_kpc_classes;
static kpep_config_kpc_map_fn     kpep_config_kpc_map;


/*
 * load_frameworks: dlopen kperf and kperfdata, resolve all symbols.
 * Returns 0 on success, 1 on failure.
 */
static int load_frameworks(void)
{
    void *kperf = dlopen(
        "/System/Library/PrivateFrameworks/kperf.framework/kperf",
        RTLD_LAZY
    );
    if (!kperf) {
        fprintf(stderr, "ERROR: cannot load kperf.framework: %s\n",
                dlerror());
        return 1;
    }

    void *kperfdata = dlopen(
        "/System/Library/PrivateFrameworks/kperfdata.framework/kperfdata",
        RTLD_LAZY
    );
    if (!kperfdata) {
        fprintf(stderr, "ERROR: cannot load kperfdata.framework: %s\n",
                dlerror());
        return 1;
    }

    /* Resolve kpc functions */
    kpc_get_counter_count  = dlsym(kperf, "kpc_get_counter_count");
    kpc_set_counting       = dlsym(kperf, "kpc_set_counting");
    kpc_get_counting       = dlsym(kperf, "kpc_get_counting");
    kpc_set_config         = dlsym(kperf, "kpc_set_config");
    kpc_get_config         = dlsym(kperf, "kpc_get_config");
    kpc_get_cpu_counters   = dlsym(kperf, "kpc_get_cpu_counters");
    kpc_force_all_ctrs_set = dlsym(kperf, "kpc_force_all_ctrs_set");

    /* Resolve kpep functions */
    kpep_db_create          = dlsym(kperfdata, "kpep_db_create");
    kpep_db_free            = dlsym(kperfdata, "kpep_db_free");
    kpep_db_event           = dlsym(kperfdata, "kpep_db_event");
    kpep_config_create      = dlsym(kperfdata, "kpep_config_create");
    kpep_config_free        = dlsym(kperfdata, "kpep_config_free");
    kpep_config_add_event   = dlsym(kperfdata, "kpep_config_add_event");
    kpep_config_kpc         = dlsym(kperfdata, "kpep_config_kpc");
    kpep_config_kpc_count   = dlsym(kperfdata, "kpep_config_kpc_count");
    kpep_config_kpc_classes = dlsym(kperfdata, "kpep_config_kpc_classes");
    kpep_config_kpc_map     = dlsym(kperfdata, "kpep_config_kpc_map");

    /* Verify critical symbols resolved */
    if (!kpc_get_counter_count || !kpc_set_counting ||
        !kpc_set_config || !kpc_get_cpu_counters ||
        !kpep_db_create || !kpep_db_event ||
        !kpep_config_create || !kpep_config_add_event ||
        !kpep_config_kpc || !kpep_config_kpc_count ||
        !kpep_config_kpc_classes || !kpep_config_kpc_map) {
        fprintf(stderr, "ERROR: failed to resolve required kperf symbols\n");
        return 1;
    }

    return 0;
}


/*
 * A-LEMS event list: the events we want to read.
 *
 * Fixed counters (always slot 0 and 1 on Apple Silicon):
 *   FIXED_CYCLES       -> slot 0
 *   FIXED_INSTRUCTIONS -> slot 1
 *
 * Configurable counters (resolved via kpep from chip plist):
 *   L1D_CACHE_MISS_LD       -> loads that missed L1D
 *   L1D_CACHE_MISS_ST       -> stores that missed L1D
 *   L1D_CACHE_MISS_LD_NONSPEC -> retired L1D load misses (most accurate)
 *   L1D_TLB_ACCESS           -> proxy for cache_references
 *
 * Note: L2 and L3 cache events are NOT available in a14.plist (M1).
 * Those columns will remain NULL. This is a hardware limitation,
 * not a software gap.
 */

/* Event names to configure via kpep */
static const char *CFG_EVENT_NAMES[] = {
    "L1D_CACHE_MISS_LD",
    "L1D_CACHE_MISS_ST",
    "L1D_CACHE_MISS_LD_NONSPEC",
    "L1D_TLB_ACCESS",
};
#define NUM_CFG_EVENTS 4


int main(void)
{
    int ret;

    /* Step 1: Load private frameworks */
    if (load_frameworks() != 0)
        return 1;

    /* Step 2: Create kpep database (auto detects chip from /usr/share/kpep/) */
    void *db = NULL;
    ret = kpep_db_create(NULL, &db);   /* NULL path = auto detect chip */
    if (ret != 0 || !db) {
        fprintf(stderr, "ERROR: kpep_db_create failed (ret=%d). "
                "Check /usr/share/kpep/ exists.\n", ret);
        return 2;
    }

    /* Step 3: Create kpep config and add configurable events */
    void *cfg = NULL;
    ret = kpep_config_create(db, &cfg);
    if (ret != 0 || !cfg) {
        fprintf(stderr, "ERROR: kpep_config_create failed (ret=%d)\n", ret);
        kpep_db_free(db);
        return 2;
    }

    /* Look up and add each configurable event */
    int events_added = 0;
    int event_slot_map[NUM_CFG_EVENTS]; /* which output index maps to which */
    for (int i = 0; i < NUM_CFG_EVENTS; i++) {
        void *ev = NULL;
        ret = kpep_db_event(db, CFG_EVENT_NAMES[i], &ev);
        if (ret != 0 || !ev) {
            /* Event not available on this chip (expected for some chips) */
            fprintf(stderr, "WARN: event %s not found in chip plist, "
                    "skipping\n", CFG_EVENT_NAMES[i]);
            event_slot_map[i] = -1;   /* mark as unavailable */
            continue;
        }
        uint32_t err = 0;
        ret = kpep_config_add_event(cfg, &ev, 0, &err);
        if (ret != 0) {
            fprintf(stderr, "WARN: kpep_config_add_event(%s) failed "
                    "(ret=%d, err=%u)\n", CFG_EVENT_NAMES[i], ret, err);
            event_slot_map[i] = -1;
            continue;
        }
        event_slot_map[i] = events_added;
        events_added++;
    }

    /* Step 4: Get the KPC config array from kpep */
    uint32_t classes = 0;
    ret = kpep_config_kpc_classes(cfg, &classes);
    if (ret != 0) {
        fprintf(stderr, "ERROR: kpep_config_kpc_classes failed\n");
        kpep_config_free(cfg);
        kpep_db_free(db);
        return 3;
    }
    /* Always include fixed counters */
    classes |= KPC_CLASS_FIXED;

    size_t kpc_count = 0;
    ret = kpep_config_kpc_count(cfg, &kpc_count);
    if (ret != 0 || kpc_count == 0) {
        /* Fallback: 2 fixed + events_added configurable */
        kpc_count = 2 + events_added;
    }

    uint64_t kpc_config[MAX_COUNTERS];
    memset(kpc_config, 0, sizeof(kpc_config));
    ret = kpep_config_kpc(cfg, kpc_config, sizeof(kpc_config));
    if (ret != 0) {
        fprintf(stderr, "ERROR: kpep_config_kpc failed (ret=%d)\n", ret);
        kpep_config_free(cfg);
        kpep_db_free(db);
        return 3;
    }

    /* Get the slot map: kpep event index -> kpc counter index */
    size_t kpc_map[MAX_COUNTERS];
    memset(kpc_map, 0, sizeof(kpc_map));
    ret = kpep_config_kpc_map(cfg, kpc_map, sizeof(kpc_map));
    if (ret != 0) {
        fprintf(stderr, "WARN: kpep_config_kpc_map failed, "
                "using sequential mapping\n");
        /* Fallback: configurable events start at index 2 (after fixed) */
        for (int i = 0; i < events_added; i++)
            kpc_map[i] = 2 + i;
    }

    /* Step 5: Force enable all counters (requires root) */
    ret = kpc_force_all_ctrs_set(1);
    if (ret != 0) {
        fprintf(stderr, "ERROR: kpc_force_all_ctrs_set failed (ret=%d). "
                "Are you running as root?\n", ret);
        kpep_config_free(cfg);
        kpep_db_free(db);
        return 3;
    }

    /* Step 6: Apply the counter configuration */
    ret = kpc_set_config(classes, kpc_config);
    if (ret != 0) {
        fprintf(stderr, "ERROR: kpc_set_config failed (ret=%d). "
                "Root required for configurable counters.\n", ret);
        kpep_config_free(cfg);
        kpep_db_free(db);
        return 3;
    }

    /* Step 7: Enable counting */
    ret = kpc_set_counting(classes);
    if (ret != 0) {
        fprintf(stderr, "ERROR: kpc_set_counting failed (ret=%d)\n", ret);
        kpep_config_free(cfg);
        kpep_db_free(db);
        return 3;
    }

    /* Step 8: Read counters (all CPUs summed) */
    int total_counters = kpc_get_counter_count(KPC_CLASS_FIXED_AND_CFG);
    if (total_counters <= 0)
        total_counters = MAX_COUNTERS;

    /* Buffer: ncpus * total_counters. We request all_cpus=1 to get
     * per-CPU arrays, then sum across CPUs for system-wide totals. */
    int ncpus = 0;
    {
        /* Get CPU count via sysctl */
        size_t sz = sizeof(ncpus);
        int mib[] = {6 /* CTL_HW */, 3 /* HW_NCPU */};
        sysctl(mib, 2, &ncpus, &sz, NULL, 0);
        if (ncpus <= 0) ncpus = 1;
    }

    size_t buf_size = ncpus * total_counters;
    uint64_t *buf = calloc(buf_size, sizeof(uint64_t));
    if (!buf) {
        fprintf(stderr, "ERROR: calloc failed for %zu counters\n", buf_size);
        kpep_config_free(cfg);
        kpep_db_free(db);
        return 4;
    }

    ret = kpc_get_cpu_counters(1, classes, 0, buf);
    if (ret != 0) {
        fprintf(stderr, "ERROR: kpc_get_cpu_counters failed (ret=%d)\n", ret);
        free(buf);
        kpep_config_free(cfg);
        kpep_db_free(db);
        return 4;
    }

    /* Step 9: Sum counters across all CPUs */
    uint64_t sums[MAX_COUNTERS];
    memset(sums, 0, sizeof(sums));
    for (int cpu = 0; cpu < ncpus; cpu++) {
        for (int c = 0; c < total_counters && c < MAX_COUNTERS; c++) {
            sums[c] += buf[cpu * total_counters + c];
        }
    }

    free(buf);

    /* Step 10: Extract values by slot.
     * Fixed counters are always at indices 0 (FIXED_CYCLES) and
     * 1 (FIXED_INSTRUCTIONS) on Apple Silicon. */
    uint64_t fixed_cycles       = sums[0];
    uint64_t fixed_instructions = sums[1];

    /* Configurable event values via kpc_map */
    uint64_t cfg_values[NUM_CFG_EVENTS];
    for (int i = 0; i < NUM_CFG_EVENTS; i++) {
        if (event_slot_map[i] >= 0) {
            int slot = (int)kpc_map[event_slot_map[i]];
            if (slot >= 0 && slot < MAX_COUNTERS)
                cfg_values[i] = sums[slot];
            else
                cfg_values[i] = 0;
        } else {
            cfg_values[i] = 0;
        }
    }

    /* Step 11: Print JSON (single line).
     * Index mapping: 0=L1D_CACHE_MISS_LD, 1=L1D_CACHE_MISS_ST,
     *               2=L1D_CACHE_MISS_LD_NONSPEC, 3=L1D_TLB_ACCESS */
    printf("{\"instructions\":%llu,\"cycles\":%llu,"
           "\"l1d_miss_ld\":%llu,\"l1d_miss_st\":%llu,"
           "\"l1d_miss_nonspec\":%llu,\"l1d_tlb_access\":%llu}\n",
           fixed_instructions, fixed_cycles,
           cfg_values[0], cfg_values[1],
           cfg_values[2], cfg_values[3]);

    /* Cleanup */
    kpep_config_free(cfg);
    kpep_db_free(db);

    return 0;
}
