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
    ap.add_argument("--theme", choices=["software", "town"], default="software",
                    help="town: workshops in districts of 8 (--modules 8 = one district, 24 = three)")
    ap.add_argument("--walk", action="store_true", help="town: walking to a workshop or a teammate costs actions")
    ap.add_argument("--batch", action="store_true",
                    help="whoever is asked also explains every other law they know that the project needs")
    ap.add_argument("--board", action="store_true", help="town: a notice board of who knows what")
    ap.add_argument("--library", action="store_true", help="town: laws written down at the library for everyone")
    ap.add_argument("--post", action="store_true", help="town: ask by letter (no walk, answer after --post-delay)")
    ap.add_argument("--post-delay", type=int, default=3)
    ap.add_argument("--shortcuts", action="store_true", help="town: forest trails from each farm to its mountain and beach")
    ap.add_argument("--no-learn", action="store_true", help="developers never learn laws (just run functions)")
    ap.add_argument("--policy", choices=["heuristic", "llm"], default="heuristic",
                    help="llm: developers are LLM agents (WS_BASE_URL / WS_MODEL, see worldseeds/llm.py)")
    ap.add_argument("--max-turns", type=int, default=d.max_turns, help="llm: model turns per developer per sprint")
    ap.add_argument("--save-traces", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=d.out_dir)
    a = ap.parse_args()
    out = run(CWConfig(universes=a.universes, modules=a.modules, fns_per_module=a.fns_per_module,
                       capacities=a.capacities, team_sizes=a.team_sizes, variants=a.variants, sprints=a.sprints,
                       projects_per_dev=a.projects_per_dev, budget=a.budget, learn=not a.no_learn, out_dir=a.out,
                       seed=a.seed, theme=a.theme, walk=a.walk, batch=a.batch, board=a.board, library=a.library,
                       post=a.post, post_delay=a.post_delay, shortcuts=a.shortcuts, policy=a.policy, max_turns=a.max_turns, save_traces=a.save_traces))
    print(f"done -> {out}/codeworld.jsonl ; summary: python scripts/analyze_codeworld.py {out}")


if __name__ == "__main__":
    main()
