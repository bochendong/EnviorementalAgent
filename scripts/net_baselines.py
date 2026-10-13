#!/usr/bin/env python
"""Run the scripted reference teams on every preset and variant; write a table.

    python scripts/net_baselines.py --seeds 10 --out results/net/baselines

For each preset (``worldseeds/net/presets.py``) and variant (team, solo, nonet) it reports the share of
seeds solved, the share of tasks done, and the share of the total budget spent. Held-out presets are
skipped: the scripted teams only know the built-in generators.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worldseeds.net.presets import PRESETS, VARIANTS, build, seeds  # noqa: E402
from worldseeds.net.solvers import SOLVERS  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--presets", nargs="*", default=[p for p in PRESETS if "heldout" not in p])
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    ap.add_argument("--out", default="results/net/baselines")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = []
    for name in a.presets:
        for var in a.variants:
            runs, t0 = [], time.time()
            for s in seeds(name, a.seeds):
                env = build(name, var)
                env.reset(s)
                m = SOLVERS[env.provider.name](env)
                total = sum(ag.budget + ag.spent for ag in env.agents.values())
                runs.append({"seed": s, "solved": m["solved"], "done": m["done"], "tasks": m["tasks"],
                             "actions": m["actions"], "rounds": m["rounds"], "budget_used": round(m["actions"] / total, 3),
                             "messages": m["messages"], "store_keys": m["store_keys"]})
            row = {"preset": name, "variant": var, "agents": len(env.agents),
                   "solved": round(st.mean(r["solved"] for r in runs), 2),
                   "tasks_done": round(st.mean(r["done"] / r["tasks"] for r in runs), 2),
                   "budget_used": round(st.mean(r["budget_used"] for r in runs), 2),
                   "actions": round(st.mean(r["actions"] for r in runs), 1),
                   "rounds": round(st.mean(r["rounds"] for r in runs), 1), "seconds": round(time.time() - t0, 1),
                   "runs": runs}
            rows.append(row)
            print(f"{name:18s} {var:6s} agents {row['agents']:2d}  solved {row['solved']:.2f}  tasks "
                  f"{row['tasks_done']:.2f}  budget used {row['budget_used']:.2f}  rounds {row['rounds']}", flush=True)
    with open(os.path.join(a.out, "baselines.json"), "w") as f:
        json.dump(rows, f, indent=1)
    with open(os.path.join(a.out, "baselines.md"), "w") as f:
        f.write("| preset | variant | agents | solved | tasks done | budget used | rounds |\n|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['preset']} | {r['variant']} | {r['agents']} | {r['solved']:.2f} | {r['tasks_done']:.2f} "
                    f"| {r['budget_used']:.2f} | {r['rounds']} |\n")


if __name__ == "__main__":
    main()
