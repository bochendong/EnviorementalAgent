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
LLM_VARIANTS = ["solo", "solo_unbounded", "independent", "owners", "directory", "random"]  # no pooled notebook


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
    theme: str = "software"  # software | town (workshops in districts of 8; modules = 8 x districts)
    walk: bool = False  # town: studying a machine / asking someone means walking there (1 next door, 3 across)
    batch: bool = False  # whoever is asked also explains every other law they know that this project needs
    board: bool = False  # town: a notice board of who knows what (read it once a sprint)
    library: bool = False  # town: masters write their laws down at the library, anyone can read them there
    post: bool = False  # town: ask by letter (no walk, the answer takes post_delay actions)
    post_delay: int = 3
    shortcuts: bool = False  # town: forest trails from each farm to its mountain and beach
    # random events (events.py), per sprint; all zero = none (and then every sprint's orders are fixed up front)
    breakdown: float = 0.0  # per machine: out of order for 1-2 sprints
    drift: float = 0.0  # per machine: re-tuned, its law changes for good
    festival: float = 0.0  # chance of a festival (one finished good four times as wanted)
    storm: float = 0.0  # per outdoor map: walking there costs double
    rumor: float = 0.0  # expected rumours per sprint on the notice board
    # grand goals (goals.py): banquet, prize, recipe, encyclopedia; worked on before the day's orders
    goals: list = field(default_factory=list)
    goal_deadline: int = 4
    fund: int = 0  # the clock tower's price (0: 400 per district)
    # money (economy.py): purses, treasury, order pay, royalties, tax, bounties, overtime, hiring
    money: bool = False
    answer_price: int = 0  # coins per explanation (0: free)
    upkeep: int = 0  # coins per sprint for food and lodging (0: none)
    bounty: int = 25
    hiring: bool = True
    policy: str = "heuristic"  # heuristic | llm (worldseeds/codeworld/llm_agent.py)
    max_turns: int = 200  # llm: model turns per developer per sprint
    save_traces: bool = False
    out_dir: str = "results/codeworld"
    seed: int = 0


def _universe(u: int, modules: int, fns: int, theme: str = "software", shortcuts: bool = False) -> Universe:
    if theme == "town":
        from .replay import town_world

        return town_world(u, districts=max(1, modules // 8), machines=fns, shortcuts=shortcuts)
    # more modules -> more types per level, so a bigger world is also a more varied one
    tpl = 2 if modules <= 8 else 3 if modules <= 16 else 4
    return Universe(u, n_modules=modules, fns_per_module=fns, levels=5, types_per_level=tpl)


def _rates(cfg: CWConfig):
    from .events import EventRates

    return EventRates(cfg.breakdown, cfg.drift, cfg.festival, cfg.storm, cfg.rumor)


def _plan(cfg: CWConfig, world: Universe, sprints: list, u: int, mods: int, n: int):
    """(world, [(orders, events)] per sprint) for one organisation: with events, a fresh copy of the world
    meets the seeded events and each sprint's orders are drawn after them (the same for every organisation)."""
    rates = _rates(cfg)
    if not rates.any:
        return world, ((p, None) for p in sprints)
    import copy

    from .events import Schedule

    w, sched = copy.deepcopy(world), Schedule(rates, cfg.seed)

    def gen():
        for s in range(cfg.sprints):
            ev = sched.next(w, s + 1)
            rng = random.Random(f"{cfg.seed}/{u}/{mods}/{n}/sprint{s}")
            yield [w.project(rng) for _ in range(cfg.projects_per_dev * n)], ev
    return w, gen()


def _buildings(cfg: CWConfig) -> dict:
    econ = None
    if cfg.money:
        from .economy import EconConfig
        econ = EconConfig(answer_price=cfg.answer_price, upkeep=cfg.upkeep, bounty=cfg.bounty, hiring=cfg.hiring,
                          seed=cfg.seed)
    return {"board": cfg.board, "library": cfg.library, "post": cfg.post, "post_delay": cfg.post_delay, "econ": econ}


def run(cfg: CWConfig) -> Path:
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=1))
    f = open(out / "codeworld.jsonl", "a")
    tf = open(out / "traces.jsonl", "a") if cfg.save_traces else None
    model = settings = None
    llm_name = "heuristic"
    if cfg.policy == "llm":
        import asyncio

        from ..llm import LLMConfig, make_model, make_settings
        from .llm_agent import llm_sprint

        lc = LLMConfig()
        model, settings, llm_name = make_model(lc), make_settings(lc), lc.model
    for u in cfg.universes:
        for mods in cfg.modules:
            world = _universe(u, mods, cfg.fns_per_module, cfg.theme, cfg.shortcuts)
            for n in cfg.team_sizes:
                rng = random.Random(f"{cfg.seed}/{u}/{mods}/{n}")
                sprints = [[world.project(rng) for _ in range(cfg.projects_per_dev * n)] for _ in range(cfg.sprints)]
                for cap in cfg.capacities:
                    for v in cfg.variants:
                        if cfg.policy == "llm" and v not in LLM_VARIANTS:
                            continue
                        wv, plan = _plan(cfg, world, sprints, u, mods, n)
                        if v.startswith("solo"):
                            org = Org(wv, 1, None if v == "solo_unbounded" else cap, "solo", cfg.learn, cfg.seed,
                                      walk=cfg.walk, batch=cfg.batch, **_buildings(cfg))
                            budget = cfg.budget * n  # the team's compute, in one head
                        else:
                            if n < 2:
                                continue
                            org = Org(wv, n, cap, v, cfg.learn, cfg.seed, walk=cfg.walk, batch=cfg.batch,
                                      **_buildings(cfg))
                            budget = cfg.budget
                        goals = None
                        if cfg.goals:
                            from .goals import make_goals
                            goals = make_goals(wv, cfg.goals, cfg.seed, deadline=cfg.goal_deadline, fund=cfg.fund or None)
                        for s, (projects, events) in enumerate(plan):
                            if cfg.policy == "llm":
                                if cfg.theme == "town":  # apprentices with the town's tools (money, goals, buildings)
                                    from .town_llm import llm_town_sprint
                                    res = asyncio.run(llm_town_sprint(org, projects, budget, model, settings, events,
                                                                      goals, cfg.max_turns))
                                else:
                                    org.apply_events(events or [])
                                    res = asyncio.run(llm_sprint(org, projects, budget, model, settings, cfg.max_turns))
                                m = res["metrics"]
                                if tf is not None:
                                    tf.write(json.dumps({"universe": u, "modules": mods, "capacity": cap, "team": n,
                                                         "variant": v, "sprint": s + 1, "traces": res["traces"]}) + "\n")
                            else:
                                m = org.sprint(projects, budget, events, goals=goals)
                            row = {"universe": u, "modules": mods, "functions": world.n_functions, "capacity": cap,
                                   "team": n, "variant": v, "sprint": s + 1, "budget_total": budget * len(org.devs),
                                   "policy": cfg.policy, "llm": llm_name, "theme": cfg.theme, "walk": cfg.walk, "batch": cfg.batch,
                                   "board": cfg.board, "library": cfg.library, "post": cfg.post, "shortcuts": cfg.shortcuts,
                                   **{k: getattr(cfg, k) for k in ("breakdown", "drift", "festival", "storm", "rumor")},
                                   "events": len(events or []), "goals": "+".join(cfg.goals),
                                   "money": cfg.money, "answer_price": cfg.answer_price, "upkeep": cfg.upkeep,
                                   "districts": world.n_districts,
                                   "world_over_capacity": world.n_functions / cap, **m, "time": time.time()}
                            f.write(json.dumps(row) + "\n")
                    f.flush()
    f.close()
    if tf is not None:
        tf.close()
    return out
