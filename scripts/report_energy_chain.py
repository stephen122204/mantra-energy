"""
report_energy_chain.py — Human-readable report for energy chain validation.

Reads the JSON output from validate_energy_chain_v2.py and renders:
  - Metadata block (measurement sources, conservation model)
  - Per-run DAG visual with ASCII tree
  - Per-run check results with confidence scores
  - Conservation summary with status codes

All interpretive text lives HERE, not in the validator.
The validator emits facts. This file adds meaning.

Per spec validator_rewrite_spec_v2.md §1.2, §2, §3, §11.
"""

import sys
from typing import Optional

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

STATUS_COLORS = {
    'OK':   GREEN,
    'WARN': YELLOW,
    'FAIL': RED,
    'N/A':  BLUE,
    'DM':   CYAN,
}

STATUS_LABELS = {
    'OK':   'OK ',
    'WARN': 'WRN',
    'FAIL': 'ERR',
    'N/A':  'N/A',
    'DM':   'DM ',
}

# Interpretive commentary for conservation checks.
# These strings live ONLY here — never in the validator.
CHECK_INTERPRETATIONS = {
    'ML1-INT': {
        'PASS_context': 'SoC intra-source. Residual = unmetered on-die fabric.',
        'FAIL_action':  'Intra-source violation. Check SPBM counter wraparound or ETL bug.',
        'WARN_context': 'Residual outside expected range. May indicate unusual workload mix.',
    },
    'ML0-ML1': {
        'PASS_context': 'Board sensor vs SoC sensor. Difference = off-die systems.',
        'FAIL_action':  'dc_input < pkg. Check board sensor calibration or sampling alignment.',
        'WARN_context': 'Board overhead extremely high. Possible sensor misalignment.',
    },
    'ML1-ML2': {
        'PASS_context': 'SoC GPU rail vs GPU compute counter. Difference = NVLink-C2C + GPU memory.',
        'FAIL_action':  'gpu_spbm < gpu_dcgm. Cross-source temporal skew or DCGM overcounting.',
        'WARN_context': 'Ratio unusually high. Check for DCGM sampling gaps.',
    },
}

# Residual interpretations by domain
RESIDUAL_CONTEXT = {
    'soc_residual':   'CMN-700 mesh interconnect, L3 cache slices, on-chip memory controllers',
    'board_overhead': 'LPDDR5X DIMMs, NVMe storage, USB/DP controllers, Ethernet PHY, fans, VRM losses',
    'nvlink_c2c':     'NVLink-C2C fabric, GPU memory interface (HBM3e PHYs + controllers), GPU VRM overhead',
}


def _j(val_j):
    # type: (Optional[float]) -> str
    if val_j is None:
        return "NULL"
    return f"{val_j:.4f}J"


def _pct(val):
    # type: (Optional[float]) -> str
    if val is None:
        return "NULL"
    return f"{val:.1f}%"


def _conf(conf):
    # type: (Optional[dict]) -> str
    if not conf:
        return ""
    score = conf.get('score')
    level = conf.get('level', '')
    comps = conf.get('components', {})
    if score is None:
        return ""
    parts = []
    if comps.get('sample') is not None:
        parts.append(f"sample={comps['sample']}")
    if comps.get('calibration') is not None:
        parts.append(f"cal={comps['calibration']}")
    if comps.get('source') is not None:
        parts.append(f"src={comps['source']}")
    comp_str = f"  ({', '.join(parts)})" if parts else ""
    return f"confidence: {score:.2f} {level}{comp_str}"


def _status_line(status, msg):
    # type: (str, str) -> str
    color = STATUS_COLORS.get(status, RESET)
    label = STATUS_LABELS.get(status, status)
    return f"{color}{label}{RESET}  {msg}"


def render_metadata(exp):
    # type: (dict) -> None
    """Print experiment metadata block."""
    W = 72
    print(f"\n{BOLD}{'='*W}{RESET}")
    print(f"{BOLD}A-LEMS Energy Chain Validation  exp_id={exp['exp_id']}{RESET}")
    print(f"  type={exp['experiment_type']}  workflow={exp['workflow_type']}"
          f"  runs={exp['runs_completed']}  is_valid={exp['is_valid']}")
    print(f"{BOLD}{'='*W}{RESET}")

    # Detect platform from first run
    runs = exp.get('runs', [])
    if not runs:
        return
    platform = runs[0].get('platform', 'unknown')

    # Measurement sources
    platform_layer_info = {
        'arm_spbm': {
            'ML0': 'Board monitor (SPBM INA shunt, 10 Hz)',
            'ML1': 'SoC monitor (SPBM sysfs IIO, 10 Hz)',
            'ML2': 'GPU monitor (DCGM field 156, 1 Hz)',
        },
        'x86_rapl': {
            'ML1': 'CPU package (Intel RAPL MSR, ~100 Hz)',
            'ML2': 'GPU (Intel PP1 MSR / DCGM)',
        },
        'macos_iokit': {
            'ML1': 'CPU package (Apple IOKit, W×dt integration)',
        },
    }
    layers = platform_layer_info.get(platform, {})
    if layers:
        print(f"\n{BOLD}Measurement Sources{RESET}")
        print("─" * 40)
        for layer, desc in layers.items():
            print(f"  {layer:<4}: {desc}")

    # Conservation model
    conservation_info = {
        'arm_spbm': [
            ('ML1-INT', 'ML1 intra-source  pkg >= cpu_p + cpu_e + gpu_spbm + dla'),
            ('ML0-ML1', 'Cross-source      dc_input >= pkg'),
            ('ML1-ML2', 'Cross-source      gpu_spbm >= gpu_dcgm'),
        ],
        'x86_rapl': [
            ('ML1-INT', 'ML1 intra-source  pkg = core + uncore + dram  (exact)'),
        ],
    }
    checks_info = conservation_info.get(platform, [])
    if checks_info:
        print(f"\n{BOLD}Conservation Model{RESET}")
        print("─" * 40)
        for name, desc in checks_info:
            print(f"  {name:<8}: {desc}")
    print()


def render_dag(run):
    # type: (dict) -> None
    """Print ASCII DAG visual for one run."""
    platform   = run.get('platform', 'unknown')
    dag_nodes  = run.get('dag_nodes', {})
    diag       = run.get('diagnostic_channels', {})
    derived    = run.get('derived', {})
    checks     = run.get('checks', {})

    def _ej(node_name):
        # type: (str) -> str
        node = dag_nodes.get(node_name) or diag.get(node_name) or {}
        j = node.get('energy_j')
        return f"{j:.4f}J" if j is not None else "NULL"

    def _dj(derived_name):
        # type: (str) -> str
        d = derived.get(derived_name) or {}
        j = d.get('value_j')
        return f"{j:.4f}J" if j is not None else "NULL"

    def _dpct(derived_name):
        # type: (str) -> str
        d = derived.get(derived_name) or {}
        p = d.get('pct_of_parent')
        return f"{p:.1f}%" if p is not None else ""

    def _dratio(derived_name):
        # type: (str) -> str
        d = derived.get(derived_name) or {}
        r = d.get('ratio')
        return f"{r:.2f}x" if r is not None else ""

    print(f"  {BOLD}[MEASUREMENT DAG]{RESET}  "
          f"run={run['run_id']} [{run['workflow_type']}/{run.get('provider','?')}]")
    print()

    if platform == 'arm_spbm':
        c2_status = checks.get('ML0-ML1', {}).get('status', '?')
        c1_status = checks.get('ML1-INT', {}).get('status', '?')
        c3_status = checks.get('ML1-ML2', {}).get('status', '?')
        c2_color  = STATUS_COLORS.get(c2_status, RESET)
        c1_color  = STATUS_COLORS.get(c1_status, RESET)
        c3_color  = STATUS_COLORS.get(c3_status, RESET)

        board_oh  = _dj('board_overhead')
        board_pct = _dpct('board_overhead')
        soc_res   = _dj('soc_residual')
        soc_pct   = _dpct('soc_residual')
        c2c       = _dj('nvlink_c2c')
        c3_ratio  = _dratio('nvlink_c2c')

        print(f"  ML0")
        print(f"   DC_INPUT {'─'*10} {_ej('dc_input')}")
        print(f"     │")
        print(f"     │  {c2_color}ML0-ML1: dc_input >= pkg [{c2_status}]{RESET}  "
              f"off-die={board_oh} ({board_pct})")
        print(f"     ▼")
        print(f"  ML1")
        print(f"   PACKAGE {'─'*11} {_ej('pkg')}")
        print(f"   ├── CPU_P {'─'*10} {_ej('cpu_p')}")
        print(f"   ├── CPU_E {'─'*10} {_ej('cpu_e')}")
        print(f"   ├── GPU_SPBM {'─'*7} {_ej('gpu_spbm')}")
        print(f"   │      │")
        print(f"   │      │  {c3_color}ML1-ML2: gpu_spbm >= gpu_dcgm [{c3_status}]{RESET}  "
              f"c2c={c2c} ({c3_ratio})")
        print(f"   │      ▼")
        print(f"   │   ML2")
        print(f"   │   GPU_DCGM {'─'*7} {_ej('gpu_dcgm')}")
        print(f"   │")
        print(f"   ├── DLA {'─'*13} {_ej('dla')}")
        print(f"   └── RESIDUAL {'─'*7} {soc_res} ({soc_pct})")
        print(f"       {c1_color}ML1-INT: pkg >= sum(children) [{c1_status}]{RESET}")

        # Diagnostic channels
        diag_channels = ['soc_pkg', 'cpu_gpu', 'vcore', 'prereg', 'sys_total']
        has_diag = any(
            (diag.get(ch) or {}).get('energy_j') is not None
            for ch in diag_channels
        )
        if has_diag:
            print(f"\n  {BOLD}Diagnostic Channels{RESET} (not in conservation chain)")
            print("  " + "─" * 40)
            for ch in diag_channels:
                node = diag.get(ch) or {}
                j = node.get('energy_j')
                if j is not None:
                    print(f"   {ch.upper():<12} {'─'*5} {j:.4f}J")

    elif platform == 'x86_rapl':
        c1_status = checks.get('ML1-INT', {}).get('status', '?')
        c1_color  = STATUS_COLORS.get(c1_status, RESET)

        print(f"  ML1")
        print(f"   PKG {'─'*14} {_ej('pkg')}")
        print(f"   ├── CORE {'─'*11} {_ej('core')}")
        print(f"   ├── UNCORE {'─'*8} {_ej('uncore')}")
        print(f"   └── DRAM {'─'*11} {_ej('dram')}")
        print(f"   {c1_color}ML1-INT: pkg = core + uncore + dram [{c1_status}]{RESET}")

    else:
        print(f"  Platform {platform} — DAG display not implemented")

    print()


def render_checks(run):
    # type: (dict) -> list
    """Print per-check details and return summary lines."""
    checks   = run.get('checks', {})
    run_id   = run['run_id']
    wf       = run['workflow_type']
    platform = run.get('platform', 'unknown')
    W        = 72
    summary  = []

    def _section(title):
        print(f"\n  [{title}]")

    def _line(key, val):
        print(f"  {key:<30} {val}")

    def _summary(status, msg):
        s = _status_line(status, f"run={run_id}[{wf}] {msg}")
        summary.append(s)
        print(f"  {s}")

    # ── DAG checks ────────────────────────────────────────────────────────
    for check_name in ['ML1-INT', 'ML0-ML1', 'ML1-ML2']:
        c = checks.get(check_name)
        if not c:
            continue
        status = c.get('status', '?')
        interp = CHECK_INTERPRETATIONS.get(check_name, {})

        _section(check_name)
        _line('parent:',   f"{c.get('parent', '?')} = {_j(c.get('parent_j'))}")
        _line('children:', f"sum = {_j(c.get('children_sum_j'))}")
        _line('residual:', f"{_j(c.get('residual_j'))}  ({_pct(c.get('residual_pct'))})")
        _line('status:',   status)
        if c.get('confidence'):
            _line('confidence:', _conf(c['confidence']))

        # Derived context
        derived = run.get('derived', {})
        if check_name == 'ML1-INT' and derived.get('soc_residual'):
            ctx = RESIDUAL_CONTEXT.get('soc_residual', '')
            _line('residual covers:', ctx)
        elif check_name == 'ML0-ML1' and derived.get('board_overhead'):
            ctx = RESIDUAL_CONTEXT.get('board_overhead', '')
            _line('off-die covers:', ctx)
        elif check_name == 'ML1-ML2' and derived.get('nvlink_c2c'):
            ctx = RESIDUAL_CONTEXT.get('nvlink_c2c', '')
            _line('difference covers:', ctx)

        # Interpretation
        if status == 'OK' and interp.get('PASS_context'):
            _line('context:', interp['PASS_context'])
        elif status == 'FAIL' and interp.get('FAIL_action'):
            _line('action:', interp['FAIL_action'])
        elif status == 'WARN' and interp.get('WARN_context'):
            _line('context:', interp['WARN_context'])

        # Summary line
        if check_name == 'ML1-INT':
            _summary(status, f"ML1-INT residual={_pct(c.get('residual_pct'))}"
                     + (f" confidence={c['confidence']['score']:.2f}({c['confidence']['level']})"
                        if c.get('confidence') else ""))
        elif check_name == 'ML0-ML1':
            _summary(status, f"ML0-ML1 off-die={_pct(c.get('residual_pct'))}"
                     + (f" confidence={c['confidence']['score']:.2f}({c['confidence']['level']})"
                        if c.get('confidence') else ""))
        elif check_name == 'ML1-ML2':
            d = run.get('derived', {}).get('nvlink_c2c', {})
            ratio = d.get('ratio', '')
            _summary(status, f"ML1-ML2 ratio={ratio}x"
                     + (f" confidence={c['confidence']['score']:.2f}({c['confidence']['level']})"
                        if c.get('confidence') else ""))

    # ── IDLE-SPLIT ────────────────────────────────────────────────────────
    c = checks.get('idle_split', {})
    if c:
        _section('IDLE-SPLIT')
        _line('E_pkg = E_idle + E_dynamic:', '')
        _line('', f"{_j(c.get('e_pkg_j'))} = {_j(c.get('e_idle_j'))} ({_pct(c.get('idle_pct'))}) + {_j(c.get('e_dyn_j'))} ({_pct(c.get('dyn_pct'))})")
        _line('delta:', f"{c.get('delta_uj', 0):.0f}µJ")
        if c.get('confidence'):
            _line('confidence:', _conf(c['confidence']))
        _summary(c.get('status', '?'), f"IDLE-SPLIT delta={c.get('delta_uj', 0):.0f}µJ")

    # ── PROC-ATTR-CPU ────────────────────────────────────────────────────
    c = checks.get('proc_attr_cpu', {})
    if c:
        _section('PROC-ATTR-CPU')
        _line('method:', c.get('method', '?'))
        _line('source:', c.get('source', '?'))
        if c.get('status') not in ('DM', 'N/A'):
            _line('E_cpu_dynamic:', _j(c.get('e_cpu_dynamic_j')))
            _line('cpu_fraction:', f"{c.get('cpu_fraction', 0):.4f}")
            _line('E_cpu_attributed:', _j(c.get('e_cpu_attributed_j')))
        _summary(c.get('status', '?'),
                 f"PROC-ATTR-CPU cpu_frac={c.get('cpu_fraction', 0):.3f}"
                 f" E={_j(c.get('e_cpu_attributed_j'))}")

    # ── PROC-ATTR-GPU ────────────────────────────────────────────────────
    c = checks.get('proc_attr_gpu', {})
    if c:
        _section('PROC-ATTR-GPU')
        _line('method:', c.get('method', '?'))
        _line('source:', c.get('source', '?'))
        if c.get('status') not in ('DM', 'N/A'):
            _line('E_gpu:', _j(c.get('e_gpu_dcgm_j') or c.get('e_gpu_j')))
            _line('assumption:', c.get('assumption', '?'))
            _line('assumption_confidence:', c.get('assumption_confidence', '?'))
            _line('E_gpu_attributed:', _j(c.get('e_gpu_attributed_j')))
        _summary(c.get('status', '?'),
                 f"PROC-ATTR-GPU E={_j(c.get('e_gpu_attributed_j') or c.get('e_gpu_j'))}"
                 f" assumption={c.get('assumption', '?')}({c.get('assumption_confidence', '?')})")

    # ── PROC-ATTR-COMBINED ───────────────────────────────────────────────
    c = checks.get('proc_attr_combined', {})
    if c and c.get('status') not in ('DM', 'N/A'):
        _section('PROC-ATTR-COMBINED')
        _line('E_cpu:', _j(c.get('e_cpu_j')))
        _line('E_gpu:', _j(c.get('e_gpu_j')))
        _line('E_total:', _j(c.get('e_total_j')))
        _line('pkg_share:', _pct(c.get('pkg_share_pct')))
        _summary(c.get('status', '?'),
                 f"PROC-ATTR-COMBINED E={_j(c.get('e_total_j'))}"
                 f" pkg_share={_pct(c.get('pkg_share_pct'))}")

    # ── BOUNDARY ─────────────────────────────────────────────────────────
    c = checks.get('boundary', {})
    if c:
        _section('BOUNDARY')
        status = c.get('status', '?')
        if status == 'N/A':
            _line('NOT AVAILABLE:', c.get('reason', ''))
            if c.get('detail'):
                _line('detail:', c['detail'])
            if c.get('fix'):
                _line('fix:', c['fix'])
        elif status == 'DM':
            _line('DATA MISSING:', c.get('reason', ''))
        else:
            _line('E_pre:', _j(c.get('pre_j')))
            _line('E_work:', _j(c.get('work_j')))
            _line('E_post:', _j(c.get('post_j')))
            _line('delta:', f"{c.get('delta_uj', 0):.0f}µJ")
        _line('framework_overhead:', _j(c.get('framework_overhead_j')))
        _bnd_detail = c.get('reason', '') if status in ('N/A', 'DM') else f"delta={c.get('delta_uj',0):.0f}uJ"
        _summary(status, f"BOUNDARY {_bnd_detail}")

    # ── ACTIVITY-DECOMP ──────────────────────────────────────────────────
    c = checks.get('activity_decomp', {})
    if c:
        _section('ACTIVITY-DECOMP')
        status = c.get('status', '?')
        _line('method:', c.get('method', '?'))
        _line('provenance:', c.get('provenance', '?'))
        _line('E_llm_window:', _j(c.get('e_llm_j')))
        _line('E_orchestration:', _j(c.get('e_orch_j')))
        _line('E_attributed:', _j(c.get('e_attr_j')))
        if status == 'DM':
            _line('DATA MISSING:', c.get('reason', ''))
        elif status == 'OK':
            _line('delta:', f"{c.get('delta_uj', 0):.0f}µJ")
        if c.get('e_prefill_j'):
            _line('E_prefill:', _j(c.get('e_prefill_j')))
            _line('E_decode:', _j(c.get('e_decode_j')))
        _line('E_llm_wait (diagnostic):', _j(c.get('e_llm_wait_j')))
        _summary(status,
                 f"ACTIVITY-DECOMP E_llm={_j(c.get('e_llm_j'))}"
                 + (f" {c.get('reason', '')}" if status == 'DM' else f" delta={c.get('delta_uj',0):.0f}µJ"))

    # ── PHASE-PARTITION ──────────────────────────────────────────────────
    c = checks.get('phase_partition', {})
    if c:
        _section('PHASE-PARTITION')
        status = c.get('status', '?')
        if status == 'N/A':
            _line('', c.get('reason', ''))
        elif status == 'DM':
            _line('DATA MISSING:', c.get('reason', ''))
        else:
            phases = c.get('phases', [])
            if phases:
                print(f"\n  {'Phase':<12} {'Energy(J)':>10} {'E%':>6} {'Dur(s)':>8} {'T%':>6} {'E/T':>6}")
                print("  " + "─" * 52)
                for ph in phases:
                    et = f"{ph['et_ratio']:.1f}x" if ph.get('et_ratio') is not None else "──"
                    dur_s = f"{ph['duration_s']:.3f}" if ph.get('duration_s') is not None else "NULL"
                    t_pct = f"{ph['duration_pct']:.1f}%" if ph.get('duration_pct') is not None else "NULL"
                    print(f"  {ph['name']:<12} {ph['energy_j']:>10.4f} {ph['energy_pct']:>5.1f}% "
                          f"{dur_s:>8} {t_pct:>6} {et:>6}")
            _line('phase_coverage:', _pct(c.get('phase_coverage_pct')))
            _line('delta:', f"{c.get('delta_uj', 0):.0f}µJ")
            if c.get('resolution_warning'):
                print(f"\n  {YELLOW}WRN{RESET} {c['resolution_warning']}")

        inter_pct = ""
        if c.get('phases'):
            inter = next((p for p in c['phases'] if p['name'] == 'inter_phase'), None)
            if inter:
                inter_pct = f" inter={inter['energy_pct']:.1f}%"
        _summary(status, f"PHASE-PARTITION delta={c.get('delta_uj', 0):.0f}µJ{inter_pct}")

    # ── GOAL-AGGREGATION ─────────────────────────────────────────────────
    c = checks.get('goal_aggregation', {})
    if c:
        _section('GOAL-AGGREGATION')
        status = c.get('status', '?')
        if status == 'DM':
            _line('DATA MISSING:', c.get('reason', ''))
        else:
            n = c.get('n_attempts', 0)
            _line('E_goal:', _j(c.get('e_goal_j')))
            _line(f'SUM({n} attempts):', _j(c.get('e_sum_attempts_j')))
            _line('delta:', f"{c.get('delta_uj', 0):.0f}µJ")
            if c.get('e_per_attempt_j') and n > 1:
                _line('per attempt:', str([f"{e:.4f}J" for e in c['e_per_attempt_j']]))
            if c.get('retry_amplification_ratios'):
                _line('retry amplification:', str(c['retry_amplification_ratios']))
                _line('retry trend:', c.get('retry_trend', '?'))
        _summary(status,
                 f"GOAL-AGGREGATION delta={c.get('delta_uj', 0):.0f}µJ"
                 f" attempts={c.get('n_attempts', 0)}")

    return summary


def render_report(output):
    # type: (dict) -> None
    """
    Render the full validation report from JSON output.
    Called by validate_energy_chain_v2.py after validation.
    """
    W = 72
    grand_total = {'ok': 0, 'warn': 0, 'fail': 0, 'n_a': 0, 'data_missing': 0}

    for exp in output.get('experiments', []):
        render_metadata(exp)

        for run in exp.get('runs', []):
            print(f"\n  {'─'*W}")
            print(f"  run={run['run_id']}  [{run['workflow_type']}/{run.get('provider','?')}]"
                  f"  platform={run.get('platform','?')}")
            print(f"  {'─'*W}")

            render_dag(run)
            all_summary = render_checks(run)

            run_conf = run.get('run_confidence')
            if run_conf is not None:
                from confidence import confidence_level
                level = confidence_level(run_conf)
                print(f"\n  Run Confidence: {run_conf:.2f} {level}")
            print(f"  {'─'*W}")

        # Experiment summary
        s = exp.get('summary', {})
        print(f"\n  Conservation Summary")
        print(f"  {'─'*70}")
        print(f"\n{'='*W}")
        print(f"  exp_id={exp['exp_id']}: "
              f"{s.get('ok',0)} passed  "
              f"{s.get('warn',0)} warnings  "
              f"{s.get('fail',0)} failed  "
              f"{s.get('n_a',0)} n/a  "
              f"{s.get('data_missing',0)} data_missing")
        print(f"{'='*W}")

        for k, v in s.items():
            grand_total[k] = grand_total.get(k, 0) + v

    if len(output.get('experiments', [])) > 1:
        print(f"\n{BOLD}TOTAL: "
              f"{grand_total['ok']} passed  "
              f"{grand_total['warn']} warnings  "
              f"{grand_total['fail']} failed  "
              f"{grand_total['n_a']} n/a  "
              f"{grand_total['data_missing']} data_missing{RESET}\n")
