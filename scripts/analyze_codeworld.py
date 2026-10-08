#!/usr/bin/env python
"""Summarise CodeWorld runs: share of projects done per organisation, by world size, capacity and team.

    python scripts/analyze_codeworld.py results/codeworld/core [more dirs] [--from-sprint 5] [--costs]

Rows: (functions, capacity, team). Regimes: the world fits one notebook (F <= C), it fits the team's
notebooks together (C < F <= n*C), or not even that (F > n*C). Steady state = sprints from --from-sprint on
(default: the second half). --costs adds actions per finished project, questions and re-learned laws.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

ORDER = ["solo", "solo_unbounded", "independent", "random", "owners", "directory", "pooled"]


def load(paths):
    rows = []
    for p in paths:
        for f in Path(p).rglob("codeworld.jsonl"):
            rows += [json.loads(x) for x in f.open() if x.strip()]
    return rows


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--from-sprint", type=int, default=0)
    ap.add_argument("--costs", action="store_true")
    a = ap.parse_args()
    rows = load(a.paths)
    if not rows:
        print("no codeworld rows")
        return
    last = max(r["sprint"] for r in rows)
    start = a.from_sprint or last // 2 + 1
    by = defaultdict(list)
    for r in rows:
        if r["sprint"] >= start:
            by[(r["functions"], r["capacity"], r["team"], r["variant"])].append(r)
    keys = sorted({k[:3] for k in by})
    vs = [v for v in ORDER if any(k[3] == v for k in by)]

    def regime(f, c, n):
        return "fits one" if f <= c else "fits team" if f <= n * c else "too big"

    print(f"Share of projects done, sprints {start}-{last} (solo = one developer with the team's budget)\n")
    print("| functions | capacity | team | regime | " + " | ".join(vs) + " |")
    print("|---|---|---|---|" + "---|" * len(vs))
    for f, c, n in keys:
        cells = []
        for v in vs:
            rs = by.get((f, c, n, v))
            cells.append(f"{mean(r['done'] / r['projects'] for r in rs):.2f}" if rs else "")
        print(f"| {f} | {c} | {n} | {regime(f, c, n)} | " + " | ".join(cells) + " |")
    if a.costs:
        print("\nActions per finished project / questions asked per sprint / laws re-learned per sprint\n")
        print("| functions | capacity | team | " + " | ".join(vs) + " |")
        print("|---|---|---|" + "---|" * len(vs))
        for f, c, n in keys:
            cells = []
            for v in vs:
                rs = by.get((f, c, n, v))
                if not rs:
                    cells.append("")
                    continue
                done = sum(r["done"] for r in rs)
                cells.append(f"{sum(r['actions'] for r in rs) / max(1, done):.0f} / {mean(r['spent_ask'] for r in rs):.0f}"
                             f" / {mean(r['relearned'] for r in rs):.0f}")
            print(f"| {f} | {c} | {n} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
