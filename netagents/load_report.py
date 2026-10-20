"""The load experiment's table: share of tasks done by world size, for the single agent and each team with
tools shared or split, and each team's paired difference from the single agent (95% bootstrap interval).

    python -m netagents.load_report results/net/runs/<run>/load

A crossing is where a team's interval moves from below zero to above it as the world grows.
"""

from __future__ import annotations

import argparse
import re
import statistics as st

from .evaluate import load_runs
from .fidelity import bootstrap


def table(rows: list[dict]) -> str:
    def size(case):
        return int(re.search(r"-m(\d+)-", case).group(1))

    sizes = sorted({size(r["case"]) for r in rows})
    solo = {(size(r["case"]), r["seed"]): r["completion"] for r in rows if r["design"] == "sas"}
    groups = [("sas", "")] + sorted({(r["design"], r["case"].rsplit("-", 1)[1]) for r in rows if r["design"] != "sas"})
    out = ["| design | tools | " + " | ".join(f"{m} modules" for m in sizes) + " |",
           "|---|---|" + "---|" * len(sizes)]
    for d, tools in groups:
        cells = []
        for m in sizes:
            mine = {r["seed"]: r["completion"] for r in rows if r["design"] == d and size(r["case"]) == m
                    and (not tools or r["case"].endswith(tools))}
            if not mine:
                cells.append("-")
                continue
            cell = f"{st.mean(mine.values()):.2f}"
            common = sorted(set(mine) & {s for (mm, s) in solo if mm == m})
            if d != "sas" and len(common) >= 2:
                a, b = [mine[s] for s in common], [solo[(m, s)] for s in common]
                lo, hi = bootstrap(a, b)
                cell += f" ({(sum(a) - sum(b)) / len(common):+.2f} [{lo:+.2f}, {hi:+.2f}])"
            cells.append(cell)
        out.append(f"| {d} | {tools or 'all (alone)'} | " + " | ".join(cells) + " |")
    def load(m, key):
        vals = [r[key] for r in rows if size(r["case"]) == m and key in r]
        return st.mean(vals) if vals else 0

    loads = {m: (load(m, "candidates_per_project"), load(m, "distinct_functions_needed")) for m in sizes}
    out.append("| load | | " + " | ".join(f"{loads[m][0]:.0f} chains / project, {loads[m][1]:.0f} functions"
                                            for m in sizes) + " |")
    return ("\n".join(out) + "\n\nEach cell: mean share of tasks done; for teams, in brackets, the paired difference "
            "from the single agent over seeds and its 95% bootstrap interval.\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    a = ap.parse_args()
    print(table(load_runs(a.dir)))


if __name__ == "__main__":
    main()
