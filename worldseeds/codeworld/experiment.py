"""The core CodeWorld experiment: when the world holds more than one developer can keep in mind, does a
network of developers beat one developer with the same compute?

For every (world size, notebook capacity, team size) and organisation, the same sprints of projects are
worked on; one row per sprint goes to ``codeworld.jsonl``:

    solo            1 developer, the team's whole budget, one notebook of the given capacity
    solo_unbounded  the same with unlimited memory (what the solo developer would do if it could hold it all)
    independent / owners / directory / random / pooled   a team of n (org.MODES)
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .org import Org
from .world import Universe

VARIANTS = ["solo", "solo_unbounded", "independent", "owners", "directory", "random", "pooled"]


@dataclass
class CWConfig:
    universes: list[int] = field(default_factory=lambda: [1, 2])
    modules: list[int] = field(default_factory=lambda: [4, 8, 16, 32])  # world size: functions = modules x fns
    fns_per_module: int = 4
    capacities: list[int] = field(default_factory=lambda: [8, 16])
    team_sizes: list[int] = field(default_factory=lambda: [4])
    variants: list[str] = field(default_factory=lambda: list(VARIANTS))
    sprints: int = 8
    projects_per_dev: int = 4  # per sprint
    budget: int = 120  # actions per developer per sprint
    learn: bool = True
    out_dir: str = "results/codeworld"
    seed: int = 0


def _universe(u: int, modules: int, fns: int) -> Universe:
    # more modules -> more types per level, so a bigger world is also a more varied one
    tpl = 2 if modules <= 8 else 3 if modules <= 16 else 4
    return Universe(u, n_modules=modules, fns_per_module=fns, levels=5, types_per_level=tpl)


def run(cfg: CWConfig) -> Path:
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=1))
    f = open(out / "codeworld.jsonl", "a")
    for u in cfg.universes:
        for mods in cfg.modules:
            world = _universe(u, mods, cfg.fns_per_module)
            for n in cfg.team_sizes:
                rng = random.Random(f"{cfg.seed}/{u}/{mods}/{n}")
                sprints = [[world.project(rng) for _ in range(cfg.projects_per_dev * n)] for _ in range(cfg.sprints)]
                for cap in cfg.capacities:
                    for v in cfg.variants:
                        if v.startswith("solo"):
                            org = Org(world, 1, None if v == "solo_unbounded" else cap, "solo", cfg.learn, cfg.seed)
                            budget = cfg.budget * n  # the team's compute, in one head
                        else:
                            if n < 2:
                                continue
                            org = Org(world, n, cap, v, cfg.learn, cfg.seed)
                            budget = cfg.budget
                        for s, projects in enumerate(sprints):
                            m = org.sprint(projects, budget)
                            row = {"universe": u, "modules": mods, "functions": world.n_functions, "capacity": cap,
                                   "team": n, "variant": v, "sprint": s + 1, "budget_total": budget * len(org.devs),
                                   "world_over_capacity": world.n_functions / cap, **m, "time": time.time()}
                            f.write(json.dumps(row) + "\n")
                    f.flush()
    f.close()
    return out
