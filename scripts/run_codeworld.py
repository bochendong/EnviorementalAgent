#!/usr/bin/env python
"""CodeWorld: networks of developer agents in a software ecosystem with hidden behaviour (docs/codeworld.md).

    # the core experiment (heuristic developers, CPU, ~1 min): network vs equal-compute solo, by world size
    python scripts/run_codeworld.py --out results/codeworld/core
    # scaling the team in a big world
    python scripts/run_codeworld.py --modules 32 --capacities 16 --team-sizes 2 4 8 16 --out results/codeworld/scale
    python scripts/analyze_codeworld.py results/codeworld/core
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worldseeds.codeworld.experiment import VARIANTS, CWConfig, run  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    d = CWConfig()
    ap.add_argument("--universes", nargs="+", type=int, default=d.universes)
    ap.add_argument("--modules", nargs="+", type=int, default=d.modules, help="world sizes (modules; 4 functions each)")
    ap.add_argument("--fns-per-module", type=int, default=d.fns_per_module)
    ap.add_argument("--capacities", nargs="+", type=int, default=d.capacities, help="laws a developer can keep in mind")
    ap.add_argument("--team-sizes", nargs="+", type=int, default=d.team_sizes)
    ap.add_argument("--variants", nargs="+", choices=VARIANTS, default=VARIANTS)
    ap.add_argument("--sprints", type=int, default=d.sprints)
    ap.add_argument("--projects-per-dev", type=int, default=d.projects_per_dev)
    ap.add_argument("--budget", type=int, default=d.budget, help="actions per developer per sprint")
    ap.add_argument("--no-learn", action="store_true", help="developers never learn laws (just run functions)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=d.out_dir)
    a = ap.parse_args()
    out = run(CWConfig(universes=a.universes, modules=a.modules, fns_per_module=a.fns_per_module,
                       capacities=a.capacities, team_sizes=a.team_sizes, variants=a.variants, sprints=a.sprints,
                       projects_per_dev=a.projects_per_dev, budget=a.budget, learn=not a.no_learn, out_dir=a.out,
                       seed=a.seed))
    print(f"done -> {out}/codeworld.jsonl ; summary: python scripts/analyze_codeworld.py {out}")


if __name__ == "__main__":
    main()
