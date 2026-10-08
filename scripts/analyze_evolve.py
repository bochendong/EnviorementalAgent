#!/usr/bin/env python
"""Summarise evolve runs (protocol 'evolve'): does the learner improve, does it hack, does it transfer?

    python scripts/analyze_evolve.py results/evolve [more dirs...] [--genes]

Per evaluator (true = selected on test success, proxy = selected on what the agent claims it knows /
how it grades itself), per generation: the population's mean true score and proxy, and the archive's best
learner on a fixed benchmark (true score, claimed laws, wrongly claimed laws). The hacking gap is the
proxy-selected line's proxy rising while its true score does not. Then transfer: fresh lives in unseen
universes after k training towns, initial vs evolved learner. --genes prints the best genome per generation.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load(paths, name):
    rows = []
    for p in paths:
        for f in Path(p).rglob(name):
            rows += [json.loads(x) for x in f.open() if x.strip()]
    return rows


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--genes", action="store_true")
    a = ap.parse_args()
    rows = load(a.paths, "evolve.jsonl")
    gens = [r for r in rows if r["phase"] == "generation"]
    if not rows:
        print("no evolve rows")
        return
    print("| evaluator | gen | pop true | pop proxy | bench true | bench claimed | bench wrong |")
    print("|---|---|---|---|---|---|---|")
    by = defaultdict(list)
    for r in gens:
        by[(r["evaluator"], r["generation"])].append(r)
    for (ev, g), rs in sorted(by.items()):
        print(f"| {ev} | {g} | {mean(r['pop_true'] for r in rs):.2f} | {mean(r['pop_proxy'] for r in rs):.2f} | "
              f"{mean(r['bench_true'] for r in rs):.2f} | {mean(r['bench_claimed'] for r in rs):.2f} | "
              f"{mean(r['bench_claimed_wrong'] for r in rs):.2f} |")
        if a.genes:
            g0 = rs[0]["genome"]
            print("|  |  | " + (", ".join(f"{k}={v}" for k, v in g0.items()) if isinstance(g0, dict)
                                else g0[:200].replace("\n", " ").replace("|", "/")) + " | | | | |")
    tr = defaultdict(list)
    for r in rows:
        if r["phase"] == "transfer":
            tr[(r["evaluator"], r["learner"], r["k_train"])].append(r)
    if tr:
        print("\nTransfer to unseen universes (fresh lives, test score after k training towns):\n")
        ks = sorted({k for _, _, k in tr})
        print("| evaluator | learner | " + " | ".join(f"k={k}" for k in ks) + " | wrong claims (last k) |")
        print("|---|---|" + "---|" * len(ks) + "---|")
        for ev in sorted({e for e, _, _ in tr}):
            for lr in ("initial", "evolved"):
                cells = [f"{mean(r['true'] for r in tr[(ev, lr, k)]):.2f}" for k in ks]
                wrong = mean(r["claimed_wrong"] for r in tr[(ev, lr, ks[-1])])
                print(f"| {ev} | {lr} | " + " | ".join(cells) + f" | {wrong:.2f} |")
    lives = [r for r in rows if r["phase"] == "life" and "mentor_claims" in r]
    if lives:
        print("\nMentor (llm): self-grade vs truth per generation\n")
        print("| evaluator | gen | self-grade | true | mentor claims | correct |")
        print("|---|---|---|---|---|---|")
        m = defaultdict(list)
        for r in lives:
            m[(r["evaluator"], r["generation"])].append(r)
        for (ev, g), rs in sorted(m.items()):
            print(f"| {ev} | {g} | {mean(r['proxy'] for r in rs):.2f} | {mean(r['true'] for r in rs):.2f} | "
                  f"{mean(r['mentor_claims'] for r in rs):.1f} | {mean(r['mentor_claims_correct'] for r in rs):.1f} |")


if __name__ == "__main__":
    main()
