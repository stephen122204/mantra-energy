#!/usr/bin/env python3
"""Median 4-bit/8-bit energy ratios per test and concurrency from bench.py CSVs.

Usage: python3 summarize.py ../results/v100-20261016
Decode and mixed tests use J per generated token; the prefill-only test (one generated token)
uses J per prompt token.
"""
import csv, statistics as st, sys
from pathlib import Path

TESTS = {"p0": "mixed; ~1.57k-token prompt; 256 generated",
         "p0b": "mixed; precision order swapped",
         "p0c": "decode-heavy; ~17-token prompt; 512 generated",
         "p0d": "prefill-only; ~1.57k-token prompt; 1 generated"}

def main(d):
    print("test,description,conc,q4_J_per_tok,q8_J_per_tok,ratio_q4_over_q8,unit,reps")
    for tag, desc in TESTS.items():
        rows = list(csv.DictReader(open(Path(d) / f"{tag}_results.csv")))
        unit = "prompt" if tag == "p0d" else "generated"
        key = "prompt_tokens" if unit == "prompt" else "gen_tokens"
        for conc in sorted({int(r["conc"]) for r in rows}):
            m, n = {}, {}
            for p in ("q4", "q8"):
                v = [float(r["energy_j"]) / float(r[key]) for r in rows if r["precision"] == p and int(r["conc"]) == conc]
                m[p], n[p] = st.median(v), len(v)
            print(f"{tag},{desc},{conc},{m['q4']:.4f},{m['q8']:.4f},{m['q4']/m['q8']:.3f},J/{unit} token,{min(n.values())}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/v100-20261016")
