#!/usr/bin/env python
"""Aggregate episodes.jsonl files into markdown tables (no pandas needed).

    python scripts/analyze.py results/compgen_qwen3_8b [more dirs...] [--by condition view phase]
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def load(dirs):
    rows = []
    for d in dirs:
        p = Path(d)
        files = [p] if p.is_file() else list(p.rglob("episodes.jsonl"))
        for f in files:
            rows += [json.loads(line) for line in f.open() if line.strip()]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--by", nargs="+", default=["env", "protocol", "context", "condition", "view", "variant", "phase"])
    ap.add_argument("--curve", action="store_true", help="also print success by episode bucket (learning curve)")
    a = ap.parse_args()
    rows = load(a.paths)
    if not rows:
        print("no rows")
        return
    groups = defaultdict(list)
    for r in rows:
        groups[tuple(r.get(k, "") for k in a.by)].append(r)
    hdr = a.by + ["n", "success", "95% CI", "actions", "act/oracle", "invalid", "zoom", "in_tok", "out_tok",
                  "laws_ok/conf", "reads", "board", "errors"]
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for key in sorted(groups, key=lambda k: tuple(str(x) for x in k)):
        g = groups[key]
        n = len(g)
        k = sum(1 for r in g if r["success"])
        lo, hi = wilson(k, n)
        succ = [r for r in g if r["success"] and r.get("oracle_steps")]
        ratio = mean([r["actions"] / r["oracle_steps"] for r in succ])
        laws = ""
        if any("seed_laws_confident" in r for r in g):
            last = g[-1]
            laws = f"{last.get('seed_laws_correct', 0)}/{last.get('seed_laws_confident', 0)}"
        elif any("library_claims" in r for r in g):  # library: correct/total claims on the shelves
            last = g[-1]
            laws = f"{last.get('library_claims_correct', 0)}/{last.get('library_claims', 0)} lib"
        reads = mean([r["library_reads"] for r in g if "library_reads" in r])
        board = mean([r["board_done"] / r["board_total"] for r in g if r.get("board_total")])  # share of requests done
        print("| " + " | ".join(str(x) for x in key) + f" | {n} | {k / n:.2f} | [{lo:.2f},{hi:.2f}] | "
              f"{mean([r['actions'] for r in g]):.1f} | {ratio:.2f} | {mean([r['invalid_actions'] for r in g]):.1f} | "
              f"{mean([r['zoom_ops'] for r in g]):.1f} | {mean([r['input_tokens'] for r in g]):.0f} | "
              f"{mean([r['output_tokens'] for r in g]):.0f} | {laws} | "
              f"{'' if reads != reads else f'{reads:.1f}'} | {'' if board != board else f'{board:.2f}'} | "
              f"{sum(1 for r in g if r.get('status') == 'error')} |")
    if a.curve:
        print("\nLearning curves (success rate per block of 4 episodes, train phases):")
        chains = defaultdict(list)
        for r in rows:
            chains[(r["protocol"], r["condition"], r["view"], r.get("variant", ""))].append(r)
        for key, g in sorted(chains.items()):
            g.sort(key=lambda r: r["episode"])
            buckets = defaultdict(list)
            for r in g:
                buckets[r["episode"] // 4].append(r["success"])
            print(" ", key, " ".join(f"{mean(v):.2f}" for _, v in sorted(buckets.items())))


if __name__ == "__main__":
    main()
