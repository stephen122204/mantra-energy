"""
platform_config.py — Platform configuration for energy chain validation.

All platform-specific knowledge lives here. The validator and report code
use ONLY this config. No platform-specific if/else branches elsewhere.

To add a new platform (AMD, Apple M1, etc.): add a new entry to
PLATFORM_CONFIGS with measurement_layers, dag_edges, conservation_nodes,
diagnostic_nodes, boundary_mode, and source_scores.

Measurement Layers:
  ML0: Board-level sensors (INA shunt monitors, board power rails)
  ML1: SoC-level sensors (RAPL MSR, SPBM sysfs IIO accumulators)
  ML2: Accelerator-level sensors (DCGM field 156, NVML)

Conservation Invariants:
  C1 (ML1-INT):  Intra-source. sum(children) <= parent. Exact within hw tolerance.
  C2 (ML0-ML1):  Cross-source. board_total >= soc_package. Bounded (off-die overhead).
  C3 (ML1-ML2):  Cross-source. soc_gpu >= accelerator_gpu. Bounded (fabric + memory).

Status Codes:
  OK           Conservation holds within tolerance.
  WARN         Conservation holds but residual outside expected range.
  FAIL         Conservation violated — measurement bug or counter wraparound.
  N/A          Check not applicable on this platform.
  DM           Data missing — ETL not run or sensor not available.
"""

# ---------------------------------------------------------------------------
# DAG edge definition
# ---------------------------------------------------------------------------
# Each edge: parent node, list of child nodes, conservation check name,
# whether the edge crosses measurement source boundaries, and relation type.
#
# relation:
#   'gte'  = parent >= sum(children)  (bounded, residual allowed)
#   'exact' = parent == sum(children) (exact, no residual)

# ---------------------------------------------------------------------------
# Platform configurations
# ---------------------------------------------------------------------------

PLATFORM_CONFIGS = {

    # ── ARM / GN100 / NVIDIA Grace Blackwell GB10 ────────────────────────
    'arm_spbm': {
        'display_name': 'NVIDIA Grace Blackwell GB10 (ARM/SPBM)',
        'measurement_layers': {
            'ML0': {
                'name':      'Board monitor',
                'interface': 'SPBM INA shunt',
                'rate_hz':   10,
                'note':      'INA3221-class board-level shunt monitors',
            },
            'ML1': {
                'name':      'SoC monitor',
                'interface': 'SPBM sysfs IIO',
                'rate_hz':   10,
                'note':      'SoC-internal energy accumulator registers via hwmon',
            },
            'ML2': {
                'name':      'GPU monitor',
                'interface': 'DCGM field 156',
                'rate_hz':   1,
                'note':      'GPU compute complex internal counter via DCGM',
            },
        },

        # Nodes that participate in conservation checks (conservation DAG)
        'conservation_nodes': [
            'dc_input',   # ML0 — board DC rail
            'pkg',        # ML1 — full SoC package accumulator
            'cpu_p',      # ML1 — performance core cluster
            'cpu_e',      # ML1 — efficiency core cluster
            'gpu_spbm',   # ML1 — GPU broad rail (compute + memory + NVLink)
            'gpu_dcgm',   # ML2 — GPU compute only (DCGM field 156)
            'dla',        # ML1 — deep learning accelerator (integrated power rail)
        ],

        # Nodes shown in diagnostic section only (not in conservation chain)
        'diagnostic_nodes': [
            'soc_pkg',    # ML1 — SoC package power rail (overlaps pkg)
            'cpu_gpu',    # ML1 — combined CPU+GPU rail (overlaps cpu_p+cpu_e+gpu)
            'vcore',      # ML1 — CPU core voltage rail
            'prereg',     # ML0 — pre-regulator board input
            'sys_total',  # ML0 — total system draw
        ],

        # DAG edges defining conservation relationships
        'dag_edges': [
            {
                'check':        'ML0-ML1',
                'parent':       'dc_input',
                'children':     ['pkg'],
                'cross_source': True,
                'relation':     'gte',
                'description':  'Board DC input >= SoC package (off-die = LPDDR5X + NVMe + fans + VRM)',
            },
            {
                'check':        'ML1-INT',
                'parent':       'pkg',
                'children':     ['cpu_p', 'cpu_e', 'gpu_spbm', 'dla'],
                'cross_source': False,
                'relation':     'gte',
                'description':  'SoC package >= named children (residual = CMN mesh + L3 + mem ctrl)',
            },
            {
                'check':        'ML1-ML2',
                'parent':       'gpu_spbm',
                'children':     ['gpu_dcgm'],
                'cross_source': True,
                'relation':     'gte',
                'description':  'GPU broad rail >= GPU compute (diff = NVLink-C2C + GPU memory + VRM)',
            },
        ],

        # Derived quantities (computed from node differences, not raw sensors)
        'derived': {
            'soc_residual':   ('pkg', ['cpu_p', 'cpu_e', 'gpu_spbm', 'dla'],
                               'SoC unmetered fabric (CMN-700 mesh, L3 cache, memory controllers)'),
            'board_overhead': ('dc_input', ['pkg'],
                               'Off-die power (LPDDR5X, NVMe, USB/DP, Ethernet, fans, VRM losses)'),
            'nvlink_c2c':     ('gpu_spbm', ['gpu_dcgm'],
                               'NVLink-C2C fabric + GPU memory interface + GPU VRM overhead'),
        },

        # How boundary (pre/post task energy) is computed on this platform
        'boundary_mode': 'not_available',
        'boundary_note': 'SPBM accumulators are cumulative from boot, not window snapshots. Fix: integrate power_rail_samples over pre/post time windows (deferred).',

        # Process attribution methods
        'proc_attr_cpu_method': 'cpu_fraction',
        'proc_attr_gpu_method': 'direct_metering',

        # Static source accuracy scores per check (0.0 to 1.0)
        # Used in confidence composite (weight 0.2)
        'source_scores': {
            'ML1-INT': 0.9,   # intra-source, same clock domain, no published accuracy spec
            'ML0-ML1': 0.7,   # cross-source: integrated power rail vs accumulator
            'ML1-ML2': 0.7,   # cross-source: 10Hz SPBM vs 1Hz DCGM
        },

        # Expected residual range for ML1-INT (used in calibration scoring)
        # From empirical data: GN100 shows ~30-32% consistently
        'expected_c1_residual_pct': {'mean': 31.0, 'std': 2.0},

        # Sample rate for phase resolution check
        'sample_interval_ms': 100.0,  # 10Hz SPBM = 100ms per sample
    },

    # ── x86 / Intel / RAPL ───────────────────────────────────────────────
    'x86_rapl': {
        'display_name': 'Intel x86 (RAPL MSR)',
        'measurement_layers': {
            'ML1': {
                'name':      'CPU package',
                'interface': 'Intel RAPL MSR',
                'rate_hz':   100,
                'note':      'RAPL pkg/core/uncore/dram MSR counters via /dev/msr',
            },
            'ML2': {
                'name':      'GPU',
                'interface': 'Intel MSR PP1',
                'rate_hz':   100,
                'note':      'Intel PP1 GPU domain energy (integrated graphics only)',
            },
        },

        'conservation_nodes': ['pkg', 'core', 'uncore', 'dram'],
        'diagnostic_nodes':   [],

        'dag_edges': [
            {
                'check':        'ML1-INT',
                'parent':       'pkg',
                'children':     ['core', 'uncore', 'dram'],
                'cross_source': False,
                'relation':     'exact',
                'description':  'RAPL pkg = core + uncore + dram (exact by hardware design)',
            },
        ],

        'derived': {
            'dram_residual': ('pkg', ['core', 'uncore'],
                              'DRAM domain energy (separate RAPL counter)'),
        },

        'boundary_mode':        'rapl_window_delta',
        'proc_attr_cpu_method': 'cpu_fraction',
        'proc_attr_gpu_method': 'pp1_msr',

        'source_scores': {
            'ML1-INT': 1.0,   # single source, exact by RAPL hardware design
            'ML0-ML1': None,  # no board sensor on x86
            'ML1-ML2': 0.8,   # RAPL vs PP1 (same package, different domain)
        },

        'expected_c1_residual_pct': {'mean': 0.0, 'std': 0.5},  # exact, residual ~0

        'sample_interval_ms': 10.0,  # 100Hz RAPL = 10ms per sample
    },

    # ── macOS / Apple / IOKit ────────────────────────────────────────────
    'macos_iokit': {
        'display_name': 'Apple macOS (IOKit)',
        'measurement_layers': {
            'ML1': {
                'name':      'CPU package',
                'interface': 'Apple IOKit',
                'rate_hz':   None,
                'note':      'IOKit power sensor, W x dt integration, no DRAM domain',
            },
        },

        'conservation_nodes': ['pkg', 'cpu'],
        'diagnostic_nodes':   [],

        'dag_edges': [
            {
                'check':        'ML1-INT',
                'parent':       'pkg',
                'children':     ['cpu'],
                'cross_source': False,
                'relation':     'gte',
                'description':  'IOKit pkg >= cpu (DRAM domain unavailable — LIMITED provenance)',
            },
        ],

        'derived': {},

        'boundary_mode':        'rapl_window_delta',  # IOKit can snapshot
        'proc_attr_cpu_method': 'cpu_fraction',
        'proc_attr_gpu_method': 'none',  # no GPU metering on M1 via IOKit

        'source_scores': {
            'ML1-INT': 0.7,   # IOKit: W x dt integration, no published accuracy spec
        },

        'expected_c1_residual_pct': {'mean': 5.0, 'std': 5.0},

        'sample_interval_ms': None,  # IOKit polling rate varies
    },
}


def get_platform_config(platform):
    # type: (str) -> dict
    """
    Return config for a platform. Returns 'unknown' stub if not found.
    Never raises — unknown platforms get minimal config.
    """
    if platform in PLATFORM_CONFIGS:
        return PLATFORM_CONFIGS[platform]
    return {
        'display_name':        f'Unknown platform ({platform})',
        'measurement_layers':  {},
        'conservation_nodes':  [],
        'diagnostic_nodes':    [],
        'dag_edges':           [],
        'derived':             {},
        'boundary_mode':       'unknown',
        'proc_attr_cpu_method': 'cpu_fraction',
        'proc_attr_gpu_method': 'none',
        'source_scores':       {},
        'expected_c1_residual_pct': None,
        'sample_interval_ms':  None,
    }
