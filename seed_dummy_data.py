#!/usr/bin/env python3
"""
seed_dummy_data.py
==================
Seeds dummy data for UI development. All dummy records are tagged
so they can be deleted in one shot when real data arrives.

Usage:
    python3 seed_dummy_data.py --db data/experiments.db --seed
    python3 seed_dummy_data.py --db data/experiments.db --delete
    python3 seed_dummy_data.py --db data/experiments.db --status

Dummy data added:
    1. hardware_config    — 3 extra hw profiles (AMD, ARM, Cloud)
    2. agent_decision_tree — decision trees for 5 real agentic runs
    3. runs               — 10 runs tagged dummy for multi-hw view

Delete marker:
    hardware_config.agent_status = 'dummy'
    agent_decision_tree.reasoning LIKE '[dummy]%'
    runs.run_state_hash LIKE 'dummy_%'
"""

import sqlite3
import json
import random
import argparse
import time

# ─── Dummy hardware profiles ──────────────────────────────────────────────────
DUMMY_HARDWARE = [
    {
        "hostname": "AMD-RYZEN-BOX",
        "cpu_model": "AMD Ryzen 7 5800X @ 3.80GHz",
        "cpu_cores": 8, "cpu_threads": 16, "ram_gb": 32,
        "cpu_architecture": "x86_64", "cpu_vendor": "AuthenticAMD",
        "virtualization_type": "none", "system_type": "desktop",
        "rapl_has_dram": True, "rapl_has_uncore": True,
        "has_avx2": True, "has_avx512": False,
        "agent_status": "dummy",
        "hardware_hash": "dummy_amd_ryzen_5800x",
    },
    {
        "hostname": "APPLE-M2-MAC",
        "cpu_model": "Apple M2 @ 3.49GHz",
        "cpu_cores": 8, "cpu_threads": 8, "ram_gb": 16,
        "cpu_architecture": "arm64", "cpu_vendor": "Apple",
        "virtualization_type": "none", "system_type": "laptop",
        "rapl_has_dram": False, "rapl_has_uncore": False,
        "has_avx2": False, "has_avx512": False,
        "agent_status": "dummy",
        "hardware_hash": "dummy_apple_m2",
    },
    {
        "hostname": "ORACLE-CLOUD-VM",
        "cpu_model": "Intel Xeon Platinum 8358 @ 2.60GHz",
        "cpu_cores": 4, "cpu_threads": 8, "ram_gb": 64,
        "cpu_architecture": "x86_64", "cpu_vendor": "GenuineIntel",
        "virtualization_type": "kvm", "system_type": "cloud",
        "rapl_has_dram": False, "rapl_has_uncore": False,
        "has_avx2": True, "has_avx512": True,
        "agent_status": "dummy",
        "hardware_hash": "dummy_oracle_xeon",
    },
]

# ─── Energy multipliers per hw (relative to i7-1165G7 baseline) ──────────────
HW_ENERGY_MULTIPLIERS = {
    "dummy_amd_ryzen_5800x": 1.45,   # desktop, more power
    "dummy_apple_m2":        0.52,   # ARM, very efficient
    "dummy_oracle_xeon":     2.10,   # cloud VM, high overhead
}

# ─── Decision tree templates per event_type ───────────────────────────────────
def make_decision_tree(run_id: int, events: list, llm_calls: list) -> list:
    """Build dummy decision tree from real orchestration events."""
    decisions = []
    parent_id = None
    prev_decision_id = 1000 * run_id  # offset to avoid collision

    for i, ev in enumerate(events):
        step_index, phase, event_type, start_ns, end_ns, duration_ns = ev
        real_step = i + 1

        if event_type == "planning":
            dtype = "llm_choice"
            options = json.dumps(["tool_call", "llm_call", "direct_answer"])
            chosen = "llm_call"
            prompt = f"[dummy] Planning step {real_step}: determine approach for task"
            response = "[dummy] Decided to use LLM for reasoning before tool execution"
            reasoning = "[dummy] Planning phase — agent evaluating strategy"

        elif event_type == "llm_call":
            dtype = "llm_choice"
            llm = llm_calls[i % len(llm_calls)] if llm_calls else None
            options = json.dumps(["direct_answer", "tool_call", "retry"])
            chosen = "tool_call" if i < len(events) - 2 else "direct_answer"
            prompt = f"[dummy] LLM call step {real_step}"
            response = f"[dummy] tokens={llm[4] if llm else 'N/A'}"
            reasoning = "[dummy] LLM decided next action"

        elif event_type == "tool_call":
            dtype = "tool_choice"
            options = json.dumps(["search_web", "calculate", "read_file", "write_file"])
            chosen = random.choice(["search_web", "calculate"])
            prompt = f"[dummy] Tool selection step {real_step}"
            response = f"[dummy] Tool executed successfully"
            reasoning = "[dummy] Tool call — execution phase"

        elif event_type == "synthesis":
            dtype = "conditional"
            options = json.dumps(["finalize", "retry", "partial_answer"])
            chosen = "finalize"
            prompt = f"[dummy] Synthesis step {real_step}: combine results"
            response = "[dummy] Final answer synthesized"
            reasoning = "[dummy] Synthesis phase — combining outputs"
        else:
            continue

        decision_id = prev_decision_id + i + 1
        decisions.append({
            "decision_id":        decision_id,
            "run_id":             run_id,
            "step_index":         real_step,
            "parent_step_index":  real_step - 1 if real_step > 1 else None,
            "parent_decision_id": prev_decision_id + i if i > 0 else None,
            "decision_type":      dtype,
            "decision_prompt":    prompt,
            "decision_response":  response,
            "available_options":  options,
            "chosen_option":      chosen,
            "chosen_step_index":  real_step + 1,
            "reasoning":          reasoning,
            "decision_start_ns":  start_ns,
            "decision_end_ns":    end_ns,
            "decision_duration_ns": duration_ns,
            "energy_uj":          int(duration_ns / 1e6 * random.uniform(8, 25)),
        })

    return decisions


def seed(db_path: str):
    db = sqlite3.connect(db_path)
    c  = db.cursor()

    # ── 1. Create agent_decision_tree if not exists ───────────────────────────
    c.executescript("""
        CREATE TABLE IF NOT EXISTS agent_decision_tree (
            decision_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id              INTEGER NOT NULL,
            step_index          INTEGER NOT NULL,
            parent_step_index   INTEGER,
            parent_decision_id  INTEGER,
            decision_type       TEXT NOT NULL,
            decision_prompt     TEXT,
            decision_response   TEXT,
            available_options   JSON,
            chosen_option       TEXT NOT NULL,
            chosen_step_index   INTEGER,
            reasoning           TEXT,
            retry_of_decision_id INTEGER,
            decision_start_ns   INTEGER,
            decision_end_ns     INTEGER,
            decision_duration_ns INTEGER,
            energy_uj           INTEGER,
            FOREIGN KEY (run_id) REFERENCES runs(run_id),
            FOREIGN KEY (parent_decision_id) REFERENCES agent_decision_tree(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_decision_run    ON agent_decision_tree(run_id);
        CREATE INDEX IF NOT EXISTS idx_decision_parent ON agent_decision_tree(parent_decision_id);
    """)

    # ── 2. Insert dummy hardware ──────────────────────────────────────────────
    existing_hashes = {r[0] for r in c.execute("SELECT hardware_hash FROM hardware_config").fetchall()}
    hw_id_map = {}
    for hw in DUMMY_HARDWARE:
        if hw["hardware_hash"] in existing_hashes:
            print(f"  SKIP hw {hw['hostname']} (already exists)")
            hw_id = c.execute("SELECT hw_id FROM hardware_config WHERE hardware_hash=?", (hw["hardware_hash"],)).fetchone()[0]
        else:
            c.execute("""
                INSERT INTO hardware_config
                (hostname, cpu_model, cpu_cores, cpu_threads, ram_gb,
                 cpu_architecture, cpu_vendor, virtualization_type, system_type,
                 rapl_has_dram, rapl_has_uncore, has_avx2, has_avx512,
                 agent_status, hardware_hash, detected_at, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            """, (
                hw["hostname"], hw["cpu_model"], hw["cpu_cores"], hw["cpu_threads"], hw["ram_gb"],
                hw["cpu_architecture"], hw["cpu_vendor"], hw["virtualization_type"], hw["system_type"],
                hw["rapl_has_dram"], hw["rapl_has_uncore"], hw["has_avx2"], hw["has_avx512"],
                hw["agent_status"], hw["hardware_hash"],
            ))
            hw_id = c.lastrowid
            print(f"  INSERT hw {hw['hostname']} → hw_id={hw_id}")
        hw_id_map[hw["hardware_hash"]] = hw_id

    # ── 3. Insert dummy runs for multi-hw view ────────────────────────────────
    # Get real experiments to copy structure from
    real_exps = c.execute("""
        SELECT e.exp_id, e.model_name, e.task_name, e.provider,
               r.pkg_energy_uj, r.ipc, r.complexity_score, r.total_tokens,
               r.carbon_g, r.water_ml, r.planning_time_ms,
               r.execution_time_ms, r.synthesis_time_ms,
               r.total_energy_uj, r.dynamic_energy_uj, r.baseline_energy_uj,
               r.duration_ns, r.core_energy_uj, r.uncore_energy_uj
        FROM runs r JOIN experiments e ON r.exp_id = e.exp_id
        WHERE r.workflow_type = 'agentic' AND r.experiment_valid = 1
        LIMIT 10
    """).fetchall()

    dummy_run_ids = []
    for hw_hash, hw_id in hw_id_map.items():
        mult = HW_ENERGY_MULTIPLIERS[hw_hash]
        for exp in real_exps[:3]:  # 3 runs per dummy hw = 9 dummy runs total
            exp_id, model, task, provider = exp[0], exp[1], exp[2], exp[3]
            base_energy = exp[4]
            run_hash = f"dummy_{hw_hash}_{exp_id}_{int(time.time())}"
            c.execute("""
                INSERT INTO runs (
                    exp_id, hw_id, run_number, workflow_type,
                    start_time_ns, end_time_ns, duration_ns,
                    total_energy_uj, dynamic_energy_uj, baseline_energy_uj,
                    pkg_energy_uj, core_energy_uj, uncore_energy_uj,
                    ipc, complexity_score, total_tokens,
                    carbon_g, water_ml,
                    planning_time_ms, execution_time_ms, synthesis_time_ms,
                    experiment_valid, run_state_hash
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                exp_id, hw_id, 999, "agentic",
                0, int(exp[16]), int(exp[16]),
                int(base_energy * mult * random.uniform(0.9, 1.1)),
                int(exp[14] * mult),
                int(exp[15]),
                int(base_energy * mult * random.uniform(0.9, 1.1)),
                int(exp[17] * mult) if exp[17] else None,
                int(exp[18] * mult) if exp[18] else None,
                round(exp[5] * random.uniform(0.85, 1.15), 4),
                exp[6],
                exp[7],
                round(exp[8] * mult, 8) if exp[8] else None,
                round(exp[9] * mult, 8) if exp[9] else None,
                round(exp[10], 2) if exp[10] else None,
                round(exp[11], 2) if exp[11] else None,
                round(exp[12], 2) if exp[12] else None,
                1,
                run_hash,
            ))
            dummy_run_ids.append(c.lastrowid)
            print(f"  INSERT dummy run hw={hw_hash[:15]} exp={exp_id} → run_id={c.lastrowid}")

    # ── 4. Insert decision trees for real agentic runs ────────────────────────
    real_agentic_runs = c.execute("""
        SELECT run_id FROM runs
        WHERE workflow_type='agentic' AND experiment_valid=1
        LIMIT 5
    """).fetchall()

    for (run_id,) in real_agentic_runs:
        # Skip if already seeded
        existing = c.execute("SELECT COUNT(*) FROM agent_decision_tree WHERE run_id=?", (run_id,)).fetchone()[0]
        if existing > 0:
            print(f"  SKIP decision tree run_id={run_id} (already exists)")
            continue

        events = c.execute("""
            SELECT step_index, phase, event_type, start_time_ns, end_time_ns, duration_ns
            FROM orchestration_events WHERE run_id=? ORDER BY start_time_ns
        """, (run_id,)).fetchall()

        llm_calls = c.execute("""
            SELECT step_index, preprocess_ms, non_local_ms, postprocess_ms,
                   prompt_tokens, completion_tokens, status
            FROM llm_interactions WHERE run_id=? ORDER BY step_index
        """, (run_id,)).fetchall()

        if not events:
            print(f"  SKIP decision tree run_id={run_id} (no events)")
            continue

        decisions = make_decision_tree(run_id, events, llm_calls)
        for d in decisions:
            c.execute("""
                INSERT OR IGNORE INTO agent_decision_tree
                (decision_id, run_id, step_index, parent_step_index, parent_decision_id,
                 decision_type, decision_prompt, decision_response, available_options,
                 chosen_option, chosen_step_index, reasoning,
                 decision_start_ns, decision_end_ns, decision_duration_ns, energy_uj)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                d["decision_id"], d["run_id"], d["step_index"],
                d["parent_step_index"], d["parent_decision_id"],
                d["decision_type"], d["decision_prompt"], d["decision_response"],
                d["available_options"], d["chosen_option"], d["chosen_step_index"],
                d["reasoning"], d["decision_start_ns"], d["decision_end_ns"],
                d["decision_duration_ns"], d["energy_uj"],
            ))
        print(f"  INSERT {len(decisions)} decisions for run_id={run_id}")

    db.commit()
    db.close()
    print("\n✓ Seed complete. Run with --status to verify.")


def delete_dummy(db_path: str):
    db = sqlite3.connect(db_path)
    c  = db.cursor()

    r1 = c.execute("DELETE FROM agent_decision_tree WHERE reasoning LIKE '[dummy]%'").rowcount
    r2 = c.execute("DELETE FROM runs WHERE run_state_hash LIKE 'dummy_%'").rowcount
    r3 = c.execute("DELETE FROM hardware_config WHERE agent_status='dummy'").rowcount

    db.commit()
    db.close()
    print(f"✓ Deleted: {r1} decisions, {r2} dummy runs, {r3} dummy hardware configs")


def status(db_path: str):
    db = sqlite3.connect(db_path)
    c  = db.cursor()
    print("=== Dummy data status ===")
    print(f"hardware_config (dummy):    {c.execute(\"SELECT COUNT(*) FROM hardware_config WHERE agent_status='dummy'\").fetchone()[0]}")
    print(f"runs (dummy):               {c.execute(\"SELECT COUNT(*) FROM runs WHERE run_state_hash LIKE 'dummy_%'\").fetchone()[0]}")
    print(f"agent_decision_tree (dummy):{c.execute(\"SELECT COUNT(*) FROM agent_decision_tree WHERE reasoning LIKE '[dummy]%'\").fetchone()[0]}")
    print(f"agent_decision_tree (real): {c.execute(\"SELECT COUNT(*) FROM agent_decision_tree WHERE reasoning NOT LIKE '[dummy]%'\").fetchone()[0]}")
    print(f"hardware_config (total):    {c.execute('SELECT COUNT(*) FROM hardware_config').fetchone()[0]}")
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",     default="data/experiments.db")
    parser.add_argument("--seed",   action="store_true")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.seed:   seed(args.db)
    elif args.delete: delete_dummy(args.db)
    elif args.status: status(args.db)
    else: parser.print_help()
