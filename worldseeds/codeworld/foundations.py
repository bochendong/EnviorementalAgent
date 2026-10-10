"""Matched basic-learning comparisons before attempting chain selection or communication."""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ..recording import ACTIVE_RECORDING, EventLog
from .arithmetic import calculator_tool
from .ladder import LEVELS, build_world
from .llm_agent import _tools, run_dev
from .org import Org
from .recording import sprint_snapshot, start_replay
from .town_llm import TownSession
from .tutorial import MACHINES, TutorialSession, prompt, tiny_world
from .world import Project


@dataclass(frozen=True)
class Condition:
    name: str
    world: str = "small"
    gates: bool = False
    calculator: bool = False


CONDITIONS = (
    Condition("small_gated", gates=True),
    Condition("small_open"),
    Condition("small_open_calculator", calculator=True),
    Condition("wrapped_open", world="wrapped"),
    Condition("wrapped_open_calculator", world="wrapped", calculator=True),
)


@dataclass
class FoundationConfig:
    out_dir: str
    seeds: tuple = (11, 22, 33)
    conditions: tuple = tuple(c.name for c in CONDITIONS)
    budget: int = 32
    max_turns: int = 40
    explicit_arithmetic: bool = False


class FoundationSession(TutorialSession):
    gated = False

    def submit(self, program):
        if self.gated:
            return super().submit(program)
        return TownSession.submit(self, program)


def make_case(seed, condition, budget=32):
    u = tiny_world(seed) if condition.world == "small" else build_world(seed, LEVELS[0])
    org = Org(u, 1, 2, "solo", walk=False, record=True)
    org.begin_sprint(budget, [])
    order = Project(f"foundation-{seed}", "wheat", "dough",
                    [(x, u.run(MACHINES, x)) for x in (2, 7)], MACHINES, 1)
    session = FoundationSession(org, org.devs[0], [order])
    session.gated = condition.gates
    org.sessions = {session.dev.name: session}
    return org, session, order


def instructions(session, explicit_arithmetic=False):
    # Identical for all five conditions. The only calculator intervention is tool availability.
    text = prompt(session) + (
        " If a calculate tool is available, use it for arithmetic with the numbers you actually observed, "
        "including modular subtraction; it does not discover a rule for you. "
        "If it is unavailable, calculate the same arithmetic yourself.")
    if explicit_arithmetic:
        text += (" For EACH affine machine, keep the numeric outputs at inputs 0, 1, 2 in that order. "
                 "The intercept is output_at_0. The slope expression is "
                 "(output_at_1-output_at_0)%101: replace these placeholders with the actual numbers, "
                 "include the parentheses and %101, and evaluate the WHOLE expression. "
                 "Use calculate if available. Copy its result exactly into remember; never take the "
                 "absolute value of a negative result. Negative coefficients are valid, and losing their "
                 "minus sign changes the rule. Check the rule on your observed input 2. "
                 "If a note is rejected, recheck your arithmetic and the copied numbers, rather than "
                 "repeating the same probes. Once inputs 0, 1, 2 are known, you already have enough "
                 "samples for an affine rule; do not study those same samples again. "
                 "After both notes are saved, compute both order examples and submit.")
    return text


def learning_metrics(session, order):
    rules_right = sum(session._law(fn) is not None and
                      session._law(fn).table == session.u.functions[fn].law.table for fn in MACHINES)
    samples = {fn: len(session.observations.get(fn, {})) for fn in MACHINES}
    checked = sum(any(t["tool"] == "compute" and t["args"].get("program") == list(MACHINES)
                      and t["args"].get("x") == x and f"on {x}: {y}." in t["out"]
                      for t in session.trace) for x, y in order.examples)
    delivered = session.done == 1
    return {"order_passed": delivered,
            "learning_passed": delivered and rules_right == 2 and min(samples.values()) >= 3
                               and checked == len(order.examples),
            "rules_right": rules_right, "samples_per_machine": samples, "examples_checked": checked}


def summarize(rows):
    return {"conditions": [
        {"condition": name, "cases": len(rs), "orders_passed": sum(r["order_passed"] for r in rs),
         "learning_passed": sum(r["learning_passed"] for r in rs),
         "statuses": dict(Counter(r["statuses"][0] for r in rs))}
        for name in dict.fromkeys(r["variant"] for r in rows)
        for rs in ([r for r in rows if r["variant"] == name],)]}


def run(config, model=None, settings=None):
    return asyncio.run(_run(config, model, settings))


async def _run(config, model, settings):
    from ..llm import LLMConfig, make_model, make_settings
    if not config.seeds or not config.conditions or len(set(config.conditions)) != len(config.conditions):
        raise ValueError("use nonempty seeds and unique condition names")
    unknown = set(config.conditions) - {c.name for c in CONDITIONS}
    if unknown:
        raise ValueError(f"unknown conditions: {sorted(unknown)}")
    out = Path(config.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = EventLog(out / "events.jsonl")
    lc = LLMConfig()
    model = model or make_model(lc)
    settings = settings or make_settings(lc)
    (out / "config.json").write_text(json.dumps(asdict(config), indent=2))
    log.write("experiment_start", config=asdict(config), model=lc.model, thinking=lc.thinking,
              settings=settings, conditions=[asdict(c) for c in CONDITIONS],
              evaluation="post-hoc learning check; open conditions do not enforce sampling, notes or compute")
    rows, replays = [], []
    for name in config.conditions:
        condition = next(c for c in CONDITIONS if c.name == name)
        for seed in config.seeds:
            org, session, order = make_case(seed, condition, config.budget)
            tags = {"universe": seed, "variant": name, "sprint": 1}
            token = ACTIVE_RECORDING.set((log, tags))
            try:
                replay = start_replay(org, tags, config.budget)
                snapshot = sprint_snapshot(org, [order], [])
                log.write("sprint_start", tags, condition=asdict(condition), snapshot=snapshot,
                          world=org.u.layout(), devs=replay["devs"])
                session._begin()
                tools = _tools(session)
                if condition.calculator:
                    tools.append(calculator_tool(session))
                result = await run_dev(session, model, settings, config.max_turns,
                                       tools=tools, text=instructions(session, config.explicit_arithmetic))
                metrics = org.end_sprint([{"done": session.done == 1}], gifts=False)
                row = {**metrics, **tags, **learning_metrics(session, order),
                       "condition": asdict(condition), "players": 1, "projects": 1,
                       "done": session.done, "statuses": [result["status"]],
                       "tool_calls": dict(Counter(t["tool"] for t in session.trace)),
                       "input_tokens": result["input_tokens"], "output_tokens": result["output_tokens"]}
                rows.append(row)
                for filename, value in (("codeworld.jsonl", row),
                                         ("traces.jsonl", {**tags, "traces": [result]})):
                    with (out / filename).open("a") as f:
                        f.write(json.dumps(value) + "\n")
                replay["sprints"].append({**snapshot, "index": 1, "budget": config.budget,
                                          "events": org.events, "metrics": row, "world_events": [],
                                          "broken": [], "storm": [], "goals": []})
                replays.append(replay)
                (out / "replay.json").write_text(json.dumps({"replays": replays}))
                (out / "summary.json").write_text(json.dumps(summarize(rows), indent=2))
                log.write("sprint_end", tags, metrics=row)
                print(name, seed, "order", row["order_passed"], "learning", row["learning_passed"],
                      result["status"], row["tool_calls"], flush=True)
            finally:
                ACTIVE_RECORDING.reset(token)
    log.write("experiment_end", summary=summarize(rows))
    if any(r["statuses"][0].startswith("error:") for r in rows):
        raise RuntimeError("Player runtime errors: inspect saved events.jsonl")
    return out
