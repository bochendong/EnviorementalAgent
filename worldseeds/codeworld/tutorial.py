"""An interface diagnostic, not a benchmark: learn two simple machines, then exchange private notes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..recording import ACTIVE_RECORDING, EventLog
from .llm_agent import run_dev
from .org import Org
from .recording import sprint_snapshot, start_replay
from .town_llm import TownSession
from .world import Function, Law, Project, Universe

MACHINES = ("bakery.grinder", "inn.stove")


@dataclass
class TutorialConfig:
    seeds: tuple = (11, 22, 33)
    budget: int = 32
    max_turns: int = 40
    out_dir: str = "results/tutorial"


def tiny_world(seed):
    # Retain the engine's actual town map for replay, but expose only two workshops/machines.
    u = Universe(seed, n_modules=8, fns_per_module=6, theme="town", branch_share=0)
    rng = random.Random(seed)
    u.modules = ["bakery", "inn"]
    u.functions = {
        MACHINES[0]: Function(MACHINES[0], "bakery", "wheat", "flour", Law("affine", rng.randint(2, 5), rng.randint(1, 7))),
        MACHINES[1]: Function(MACHINES[1], "inn", "flour", "dough", Law("affine", rng.randint(2, 5), rng.randint(1, 7))),
    }
    u.out_of = {"wheat": [u.functions[MACHINES[0]]], "flour": [u.functions[MACHINES[1]]]}
    return u


class TutorialSession(TownSession):
    stage: str = "solo"

    def run(self, function, x):
        if self.stage == "pair" and function in self.u.functions and self.u.functions[function].module not in self.dev.owns:
            return self.log("run", {"function": function, "x": x},
                            "This diagnostic gives you access only to your own machine. Ask its owner for the other rule.")
        return super().run(function, x)

    def study(self, function):
        if self.stage == "pair" and function in self.u.functions and self.u.functions[function].module not in self.dev.owns:
            return self.log("study", {"function": function}, "The other machine is private to its owner; ask them.")
        return super().study(function)

    def submit(self, program):
        missing = [fn for fn in MACHINES if self._law(fn) is None]
        if missing:
            return self.log("submit", {"program": program}, "Rejected: first record or obtain rules for " + ", ".join(missing))
        if self.stage == "solo" and any(len(self.observations.get(fn, {})) < 3 for fn in MACHINES):
            return self.log("submit", {"program": program}, "Rejected: this tutorial requires at least three real samples per machine.")
        # Require a predicted check for each public example, before checking on real machines.
        for x, _ in self.project.examples:
            if not any(t["tool"] == "compute" and t["args"].get("program") == list(program)
                       and t["args"].get("x") == x for t in self.trace):
                return self.log("submit", {"program": program}, f"Rejected: first use compute for public example input {x}.")
        if self.stage == "pair" and not any(t["tool"] == "ask" and " is " in t["out"] for t in self.trace):
            return self.log("submit", {"program": program}, "Rejected: obtain the missing rule by asking your teammate first.")
        return super().submit(program)


def make_sessions(seed, stage, budget):
    u = tiny_world(seed)
    org = Org(u, 1 if stage == "solo" else 2, 2, "solo" if stage == "solo" else "owners",
              walk=False, record=True)
    org.begin_sprint(budget, [], None)
    sessions = []
    for i, dev in enumerate(org.devs):
        p = Project(f"tutorial-{seed}-{i}", "wheat", "dough",
                    [(x, u.run(MACHINES, x)) for x in (2, 7)], MACHINES, 1)
        session = TutorialSession(org, dev, [p])
        session.stage = stage
        if stage == "pair":
            fn = MACHINES[i]
            dev.notebook.put(fn, u.functions[fn].law)
            session.observations[fn] = {x: u.functions[fn].law(x) for x in (0, 1, 2)}
        sessions.append(session)
    org.sessions = {s.dev.name: s for s in sessions}
    return org, sessions


def prompt(s):
    head = (f"You are {s.dev.name} in a small tutorial. There are ONLY TWO machines. "
            "Their rules are simple a*x+b modulo 101, with integer a and b; no branches. "
            "The order converts wheat to dough. Machine names and types are:\n" + s.u.signatures_text() + "\n")
    if s.stage == "solo":
        task = ("Your notebook is initially empty. Learn each machine by run on 0, 1, 2 "
                "(1 action each) or study (8 actions), infer its numerical rule, and save it with remember. "
                "For a simple rule, output at 0 is b; output at 1 minus b is a modulo 101. "
                "Confirm against input 2. Do not use an order's desired value as a machine observation.\n")
    else:
        task = ("Each player received a private notebook for one machine. Other machine probes are unavailable "
                "to you; ask its owner with ask(teammate, function). Answers come from their notebook automatically. "
                "dev0 owns bakery.grinder; dev1 owns inn.stove. Your initial private notebook is:\n" +
                "\n".join(f"{fn}: {law.describe()}" for fn, law in s.dev.notebook.laws.items()) + "\n")
    return head + task + ("Once both rules are available, compute the two-machine chain on EACH public example "
            "shown in your order, then submit the chain. compute predicts from notes; submit runs the real machines. "
            "Use concrete numeric coefficients, never the letters a or b. Example of syntax only: '3*x + 5'. "
            "Tools automatically handle locations; walking has zero cost in this tutorial. "
            "There are no money goals, festivals or other tasks. Make one tool call at a time. "
            "Use a tool now instead of planning at length.")


def run(cfg, model=None, settings=None):
    return asyncio.run(_run(cfg, model, settings))


async def _run(cfg, model, settings):
    from ..llm import LLMConfig, make_model, make_settings
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = EventLog(out / "events.jsonl")
    lc = LLMConfig()
    if model is None:
        model = make_model(lc)
    settings = settings or make_settings(lc)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
    log.write("experiment_start", diagnostic=True, config=asdict(cfg), model=lc.model,
              thinking=lc.thinking, settings=settings,
              source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    results, replays = [], []
    for stage in ("solo", "pair"):
        # Only move on when the basic action loop works on at least two of three cases.
        if stage == "pair" and sum(r["passed"] for r in results) < (2 * len(cfg.seeds) + 2) // 3:
            log.write("stage_skipped", stage="pair", reason="solo gate failed: require at least two-thirds of cases")
            break
        for seed in cfg.seeds:
            org, sessions = make_sessions(seed, stage, cfg.budget)
            tags = {"universe": seed, "variant": stage, "sprint": 1}
            token = ACTIVE_RECORDING.set((log, tags))
            replay = start_replay(org, tags, cfg.budget)
            snapshot = sprint_snapshot(org, [s.project for s in sessions], None)
            snapshot["initial_rules"] = {s.dev.name: {fn: law.to_dict() for fn, law in s.dev.notebook.laws.items()}
                                         for s in sessions}
            log.write("sprint_start", tags, world=org.u.layout(), snapshot=snapshot, devs=replay["devs"])
            for s in sessions:
                s._begin()
            outputs = await asyncio.gather(*[run_dev(s, model, settings, cfg.max_turns, text=prompt(s)) for s in sessions])
            metrics = org.end_sprint([{"done": s.done == 1} for s in sessions], gifts=False)
            row = {**metrics, **tags, "diagnostic": True, "players": len(sessions), "done": sum(s.done for s in sessions),
                   "projects": len(sessions), "passed": all(s.done == 1 for s in sessions),
                   "statuses": [r["status"] for r in outputs], "actions": sum(sum(s.dev.spent.values()) for s in sessions),
                   "correct_rules": sum(org.u.functions[fn].law.table == law.table for s in sessions for fn,law in s.dev.notebook.laws.items()),
                   "asks": sum(t["tool"] == "ask" for s in sessions for t in s.trace),
                   "input_tokens": sum(r["input_tokens"] for r in outputs), "output_tokens": sum(r["output_tokens"] for r in outputs),
                   "time": time.time()}
            results.append(row)
            with (out / "codeworld.jsonl").open("a") as f: f.write(json.dumps(row) + "\n")
            with (out / "traces.jsonl").open("a") as f: f.write(json.dumps({**tags, "traces": outputs}) + "\n")
            replay["sprints"].append({**snapshot, "index": 1, "budget": cfg.budget, "events": org.events,
                                     "metrics": row, "world_events": [], "broken": [], "storm": [], "goals": []})
            replays.append(replay)
            (out / "replay.json").write_text(json.dumps({"replays": replays}))
            log.write("sprint_end", tags, metrics=row)
            ACTIVE_RECORDING.reset(token)
            print(stage, seed, "PASS" if row["passed"] else "FAIL", row["statuses"], flush=True)
    log.write("experiment_end", passed=sum(r["passed"] for r in results), cases=len(results))
    if any(s.startswith("error:") for r in results for s in r["statuses"]):
        raise RuntimeError("Player runtime errors: inspect saved events.jsonl")
    return out
