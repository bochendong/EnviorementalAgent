"""A ladder from the two-machine tutorial to the full town: one new difficulty per level.

Qwen3-8B passes the tutorial (tutorial.py: two machines, one possible chain, every step spelled out) but
barely acts in the full town (48 machines, a dozen chains per order, edge-case rules, walking, money and
goals, 40 actions each). The ladder measures where it breaks. Each level adds exactly one thing:

    1  two        two machines, one chain                                    (the tutorial, without its gates)
    2  choose     four machines, four chains fit the goods: the order's examples tell which one
    3  edges      the same, but every rule has an edge case (a different rule on multiples of 2, 3 or 5)
    4  masters    two players; each may only use its own workshop's machines and must learn them itself;
                  every order needs both workshops: ask the other master
    5  town       four players, eight workshops of three machines, orders of two or three machines; the
                  machines that fit an order's goods are listed with it
    6  full       the town as in the experiments: 48 machines, walking, money, the festival and the prize

A case passes when all its orders are delivered (levels 1-4) or at least half of them (5-6). A level is
climbed only if at least two thirds of its seeds pass; otherwise the ladder stops there and says why.
Everything is recorded like the tutorial (events.jsonl, traces.jsonl, replay.json, codeworld.jsonl).
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..recording import ACTIVE_RECORDING, EventLog
from .llm_agent import _tools, run_dev
from .org import Org
from .recording import sprint_snapshot, start_replay
from .town_llm import TownSession
from .world import P, Project, Universe


@dataclass
class Level:
    n: int
    name: str
    new: str  # what this level adds
    machines: list | None = None  # ["bakery.grinder", ...]; None: a town of `per_workshop` machines each
    per_workshop: int = 3
    branch: float = 0.0  # share of rules with an edge case
    players: int = 1
    private: bool = False  # a player may only use its own workshops' machines
    orders: int = 1  # per player
    order: tuple | None = None  # (in good, out good) for hand-made levels
    min_len: int = 2
    max_len: int = 3
    budget: int = 40
    max_turns: int = 60
    pass_share: float = 1.0
    focus: bool = False  # list the machines that fit an order's goods with it
    town_tools: bool = False  # money, goals, board, library (town_llm tools)
    walk: bool = False
    hint: str = ""


LEVELS = [
    Level(1, "two", "two machines, one chain", ["bakery.grinder", "inn.stove"], order=("wheat", "dough"),
          budget=32, max_turns=40,
          hint="Learn each machine: run it on 0, 1, 2. For a rule a*x + b the output at 0 is b, the output at 1 minus "
               "b is a (mod 101). Check with 2, remember the rule, compute the chain on the order's examples, submit."),
    Level(2, "choose", "several chains fit the goods; the examples tell which",
          ["bakery.grinder", "florist.seed_mill", "bakery.kneader", "inn.stove"], order=("wheat", "dough"),
          hint="Two machines make flour from wheat and two make dough from flour, so four chains fit the goods. Learn "
               "all four machines (run on 0, 1, 2; remember), then compute each chain on the order's examples: only "
               "one matches. Submit that one."),
    Level(3, "edges", "every rule has an edge case",
          ["bakery.grinder", "florist.seed_mill", "bakery.kneader", "inn.stove"], order=("wheat", "dough"),
          branch=1.0, budget=56, max_turns=70,
          hint="Each rule is a*x + b except on an edge case: inputs that are multiples of m (2, 3 or 5) follow a "
               "different a2*x + b2. study(machine) shows 0..7, enough to see it: find which inputs break the "
               "pattern of the others, then remember 'a2*x + b2 if x % m == 0 else a*x + b'. Then compare chains."),
    Level(4, "masters", "two players, private workshops: ask the other master",
          ["bakery.grinder", "bakery.kneader", "inn.stove", "inn.hearth_oven"], order=("wheat", "bread"),
          players=2, private=True, budget=40, max_turns=60,
          hint="You may only run your own workshop's machines; learn them first (run 0, 1, 2; remember), because the "
               "other master will ask you about them and you answer from your notebook. For the other workshop's "
               "machines, ask(master, machine). Then compute the chains on your order's examples and submit."),
    Level(5, "town", "eight workshops, four players, orders of 2-3 machines", per_workshop=3, branch=0.0,
          players=4, orders=2, budget=80, max_turns=100, pass_share=.5, focus=True,
          hint="Each order lists the machines that fit its goods. Learn those (run 0, 1, 2 for a*x + b), ask a "
               "workshop's master if they already know a rule, compute candidate chains on the examples, submit."),
    Level(6, "full", "the town of the experiments: walking, money, goals", per_workshop=6, branch=0.3,
          players=4, orders=2, budget=100, max_turns=140, pass_share=.5, focus=True, town_tools=True, walk=True,
          hint="Each order lists the machines that fit its goods. Learn what you need (study shows 0..7, which also "
               "reveals edge cases), ask masters, compute chains on the examples, submit. goals() lists the town's goals."),
]


def build_world(seed: int, lv: Level) -> Universe:
    """A town universe restricted to the level's machines (the map stays whole, for the replay)."""
    if lv.machines is None:
        return Universe(seed, n_modules=8, fns_per_module=lv.per_workshop, levels=5, theme="town",
                        branch_share=lv.branch)
    u = Universe(seed, n_modules=8, fns_per_module=8, levels=5, theme="town", branch_share=lv.branch)
    missing = [m for m in lv.machines if m not in u.functions]
    if missing:
        raise ValueError(f"not in the recipe book: {missing}")
    u.functions = {m: u.functions[m] for m in lv.machines}
    u.modules = [m for m in u.modules if any(f.module == m for f in u.functions.values())]
    u.out_of = {}
    for f in u.functions.values():
        u.out_of.setdefault(f.in_type, []).append(f)
    return u


def make_order(u: Universe, pid: str, in_t: str, out_t: str, rng: random.Random, target=None) -> Project:
    """An order whose examples single out one chain (up to chains that compute the same)."""
    cands = u.candidates(in_t, out_t)
    target = tuple(target or rng.choice(cands))
    tt = u.table(target)
    xs = list(range(P))
    rng.shuffle(xs)
    ex = [(x, tt[x]) for x in xs[:2]]
    alive = [c for c in cands if u.table(c) != tt and all(u.run(c, x) == y for x, y in ex)]
    while alive:
        x = next(x for x in xs if u.run(alive[0], x) != tt[x])
        ex.append((x, tt[x]))
        alive = [c for c in alive if u.run(c, x) == tt[x]]
    return Project(pid, in_t, out_t, ex, target, len(cands))


class LadderSession(TownSession):
    level: Level = None

    def _private(self, function):
        f = self.u.functions.get(function)
        return self.level.private and f is not None and f.module not in self.dev.owns

    def run(self, function, x):
        if self._private(function):
            return self.log("run", {"function": function, "x": x},
                            "That machine is in another master's workshop: ask them about it.")
        return super().run(function, x)

    def study(self, function):
        if self._private(function):
            return self.log("study", {"function": function},
                            "That machine is in another master's workshop: ask them about it.")
        return super().study(function)

    def status(self) -> str:
        out = super().status()
        p = self.project
        if self.level.focus and p is not None:
            fns = sorted({fn for c in self.u.candidates(p.in_type, p.out_type) for fn in c})
            out = out[:-1] + f" | machines that fit this order's goods: {', '.join(fns[:14])}" + \
                ("..." if len(fns) > 14 else "") + "]"
        return out


def make_case(seed: int, lv: Level):
    u = build_world(seed, lv)
    rng = random.Random(f"ladder/{lv.n}/{seed}")
    org = Org(u, lv.players, 12, "solo" if lv.players == 1 else "owners", walk=lv.walk, record=True,
              econ=_econ() if lv.town_tools else None)
    goals = None
    if lv.town_tools:
        from .goals import make_goals
        goals = make_goals(u, ["banquet", "prize"], seed, deadline=1)
    org.begin_sprint(lv.budget, [], goals)
    orders = []
    if lv.order is not None:
        cands = u.candidates(*lv.order)
        for k in range(lv.players * lv.orders):
            target = None
            if lv.private:  # every order needs both workshops (true of all chains here); vary the chain
                target = cands[k % len(cands)]
            orders.append(make_order(u, f"L{lv.n}-{seed}-{k + 1}", *lv.order, rng, target))
    else:
        for _ in range(lv.players * lv.orders):
            orders.append(u.project(rng, min_len=lv.min_len, max_len=lv.max_len, min_modules=2))
    sessions = []
    for i, dev in enumerate(org.devs):
        s = LadderSession(org, dev, orders[i::lv.players])
        s.level = lv
        sessions.append(s)
    org.sessions = {s.dev.name: s for s in sessions}
    return org, sessions, orders, goals


def _econ():
    from .economy import EconConfig
    return EconConfig()


def prompt(s: LadderSession) -> str:
    lv, o = s.level, s.org
    who = f"You are {s.dev.name}"
    if lv.players > 1:
        mates = "; ".join(f"{d.name} is the master of {', '.join(sorted(d.owns))}" for d in o.devs)
        who += f", one of {lv.players} players. {mates}."
    else:
        who += ", working alone."
    accessible = s.u.signatures_text() if not lv.focus else \
        "(each order lists the machines that fit its goods; signatures(workshop) shows a workshop's machines)"
    return (f"{who} Machines turn one good into another and change its grade (0..100) by a hidden rule mod 101. "
            f"Orders ask for a chain of machines whose grades match the order's examples.\n"
            f"Machines (workshop.machine: input -> output):\n{accessible}\n"
            f"You have {lv.budget} actions. run(machine, x) costs 1, study(machine) costs 8 (grades 0..7), "
            f"remember/compute/notebook are free, submit costs 1"
            + (", asking costs 1 for you and 1 for the master" if lv.players > 1 else "")
            + (", and walking to a workshop or a person costs actions too" if lv.walk else "") + ".\n"
            f"How: {lv.hint}\n"
            "Write rules with integer coefficients, e.g. '3*x + 5' (an example of syntax, not a rule). compute "
            "only predicts from your notebook; submit runs the real machines. Make one tool call at a time; act "
            "instead of planning at length.")


@dataclass
class LadderConfig:
    seeds: tuple = (11, 22, 33)
    levels: tuple = (1, 2, 3, 4, 5, 6)
    out_dir: str = "results/ladder"
    gate: float = 2 / 3
    stop: bool = True  # stop at the first level that fails its gate
    extra: dict = field(default_factory=dict)
    calculator: bool = False


def run(cfg: LadderConfig, model=None, settings=None):
    return asyncio.run(_run(cfg, model, settings))


async def _run(cfg: LadderConfig, model, settings):
    from ..llm import LLMConfig, make_model, make_settings
    from .town_llm import _tools as town_tools
    from .arithmetic import AFFINE_GUIDANCE, calculator_tool

    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = EventLog(out / "events.jsonl")
    lc = LLMConfig()
    model = model or make_model(lc)
    settings = settings or make_settings(lc)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
    log.write("experiment_start", config=asdict(cfg), model=lc.model, thinking=lc.thinking, settings=settings,
              levels=[asdict(lv) for lv in LEVELS if lv.n in cfg.levels])
    rows, replays, summary = [], [], []
    for lv in [lv for lv in LEVELS if lv.n in cfg.levels]:
        passed = 0
        for seed in cfg.seeds:
            org, sessions, orders, goals = make_case(seed, lv)
            tags = {"universe": seed, "variant": f"L{lv.n}-{lv.name}", "sprint": 1}
            token = ACTIVE_RECORDING.set((log, tags))
            replay = start_replay(org, tags, lv.budget)
            replay["title"] = f"Ladder level {lv.n} ({lv.name}): {lv.new} / seed {seed}"
            snapshot = sprint_snapshot(org, orders, goals)
            log.write("sprint_start", tags, level=asdict(lv), world=org.u.layout(), snapshot=snapshot,
                      devs=replay["devs"])
            for s in sessions:
                s._begin()

            def agent_tools(s):
                tools = town_tools(s) if lv.town_tools else _tools(s)
                if cfg.calculator:
                    tools.append(calculator_tool(s))
                return tools

            arithmetic_hint = (" Use calculate for arithmetic with your observed numbers, including modular "
                               "subtraction and modular inverses. It only evaluates your expression; "
                               "you must still infer and verify rules." +
                               AFFINE_GUIDANCE.replace("After both notes are saved",
                                                       "After the required notes for your current chain are saved") +
                               " For branched machines, identify the edge case and fit each segment; "
                               "do not use the two-point affine shortcut across a branch boundary.") if cfg.calculator else ""
            outs = await asyncio.gather(*[
                run_dev(s, model, settings, lv.max_turns, text=prompt(s) + arithmetic_hint,
                        tools=agent_tools(s),
                        more=lambda s=s: bool(s.queue)) for s in sessions])
            done = sum(s.done for s in sessions)
            metrics = org.end_sprint([{"done": True}] * done + [{"done": False}] * (len(orders) - done), gifts=False)
            ok = done >= lv.pass_share * len(orders) - 1e-9
            passed += ok
            tools: dict = {}
            for s in sessions:
                for t in s.trace:
                    tools[t["tool"]] = tools.get(t["tool"], 0) + 1
            row = {**metrics, **tags, "level": lv.n, "level_name": lv.name, "players": len(sessions),
                   "done": done, "projects": len(orders), "passed": ok,
                   "statuses": [r["status"] for r in outs], "tool_calls": tools,
                   "actions": sum(sum(s.dev.spent.values()) for s in sessions),
                   "rules_noted": sum(len(s.dev.notebook.laws) for s in sessions),
                   "rules_right": sum(org.u.functions[fn].law.table == law.table
                                      for s in sessions for fn, law in s.dev.notebook.laws.items()),
                   "candidates": [p.n_candidates for p in orders],
                   "input_tokens": sum(r["input_tokens"] for r in outs),
                   "output_tokens": sum(r["output_tokens"] for r in outs), "time": time.time()}
            rows.append(row)
            with (out / "codeworld.jsonl").open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            with (out / "traces.jsonl").open("a") as f:
                f.write(json.dumps({**tags, "traces": outs}, default=str) + "\n")
            replay["sprints"].append({**snapshot, "index": 1, "budget": lv.budget, "events": org.events,
                                      "metrics": row, "world_events": [], "broken": [], "storm": [],
                                      "goals": [g.to_dict() for g in goals] if goals else []})
            replays.append(replay)
            (out / "replay.json").write_text(json.dumps({"replays": replays}, default=str))
            log.write("sprint_end", tags, metrics=row)
            ACTIVE_RECORDING.reset(token)
            print(f"level {lv.n} {lv.name} seed {seed}: {'PASS' if ok else 'FAIL'} {done}/{len(orders)} "
                  f"{row['statuses']} tools={tools}", flush=True)
        gate = passed >= cfg.gate * len(cfg.seeds) - 1e-9
        summary.append({"level": lv.n, "name": lv.name, "new": lv.new, "passed": passed, "cases": len(cfg.seeds),
                        "climbed": gate})
        log.write("level_end", level=lv.n, passed=passed, cases=len(cfg.seeds), climbed=gate)
        if not gate and cfg.stop:
            log.write("ladder_stopped", level=lv.n, reason=f"{passed}/{len(cfg.seeds)} seeds passed")
            break
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    log.write("experiment_end", summary=summary)
    for x in summary:
        print(f"L{x['level']} {x['name']:<8} {x['passed']}/{x['cases']} {'climbed' if x['climbed'] else 'STOPPED'}"
              f"  ({x['new']})", flush=True)
    return out
