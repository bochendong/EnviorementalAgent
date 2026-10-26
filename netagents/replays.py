"""Record runs in the town (CodeWorld provider, town theme) for web/codeworld.html.

    python -m netagents.replays                    # reference teams -> web/replays/codeworld.json
    WS_BASE_URL=... WS_MODEL=qwen3-8b python -m netagents.replays --llm      # LLM teams -> web/replays/llm.json
    python -m netagents.replays --dag results/net/runs/<run>/<suite>/traces/*.jsonl.gz --reference
                                                   # DAG runs (netscale) -> web/replays/dag.json

Each replay is one run of one team; the page shows exactly what the environment recorded
(worldseeds/net/replay.py turns the event log into scenes).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from worldseeds.net import NetConfig, NetworkEnv, providers
from worldseeds.net.replay import dag_replay, town_replay

from .client import LocalEnv
from .scripted import solve_codeworld

# (title, description, provider options, network options, share laws)
SETUPS = [
    ("Four apprentices sharing a library",
     "Anyone can study any machine; what one learns goes into the library for the others.",
     {"devs": 4}, {"budget": 150}, True),
    ("Four apprentices, each on their own",
     "No library, no letters, no board: everyone studies every machine they need themselves.",
     {"devs": 4}, {"budget": 150, "store": False, "messaging": False, "board": False}, False),
    ("Eight masters, letters only",
     "Each workshop has a master and only the master can study its machines; rules travel by letter.",
     {"owners": True}, {"budget": 80, "store": False}, True),
    ("Eight masters in a changing town",
     "Masters again, with a library, while machines get re-tuned now and then: old rules go stale.",
     {"owners": True, "drift": 0.004}, {"budget": 80}, True),
    ("One apprentice with the team's budget, the team's time",
     "One head, every tool, four times the budget, but a deadline: a round is one action for one agent.",
     {"devs": 1}, {"budget": 600, "deadline": 150}, False),
]


def run(opt: dict, net: dict, seed: int, policy, universe: int = 1):
    raw = NetworkEnv(providers.make("codeworld", theme="town", n_projects=10, fns_per_module=4,
                                    universe=universe, **opt), NetConfig(**net))
    raw.reset(seed)
    policy(LocalEnv(raw))
    return raw


def read_trace(path: str) -> list[dict]:
    import gzip

    with (gzip.open(path, "rt") if path.endswith(".gz") else open(path)) as f:
        return [e for e in map(json.loads, f) if e.get("kind") != "transcripts"]


def dag_shape(events: list[dict], path: str = "") -> dict:
    """Width, depth and grain of a DAG run: width and depth from its task ids, grain from the case name in the
    trace's file name ("dag_fixed-g4_n32"), else from the applies of the task done first."""
    import re

    ids = {(e.get("args") or {}).get("task") for e in events if e.get("kind") == "op"} - {None, "FINAL"}
    ids = [t for t in ids if re.fullmatch(r"L\d+\.\d+", t)]
    width = 1 + max(int(t.split(".")[1]) for t in ids)
    depth = 1 + max(int(t[1:].split(".")[0]) for t in ids)
    m = re.search(r"-g(\d+)", os.path.basename(path))
    if m:
        grain = int(m.group(1))
    else:
        first = next(e for e in events if e.get("kind") == "done")
        grain = sum(1 for e in events if e.get("op") == "apply" and e["agent"] == first["agent"]
                    and (e.get("args") or {}).get("task") == first["task"])
    return {"width": width, "depth": depth, "grain": grain}


def reference_run(width: int, depth: int, n: int, seed: int, grain: int, fanin: int = 2):
    """The scripted reference team's run on the same problem (the fastest sharing, netagents/scaling.py), with
    its events: (summary, events)."""
    from .scaling import make_env, run as reference, scripted_batch, scripted_team

    ref = reference(width, depth, n, seed, fanin, grain)
    env = make_env(width, depth, n, seed, fanin, grain)
    if ref["sharing"] == "batch":
        scripted_batch(env)
    else:
        scripted_team(env, "broadcast" if ref["sharing"] == "none" else ref["sharing"])
    return ref, env.events


def dag_replays(paths: list[str], with_reference: bool, skin: str = "campus") -> list[dict]:
    reps = []
    for path in paths:
        ev = read_trace(path)
        shape = dag_shape(ev, path)
        reset = next(e for e in ev if e.get("kind") == "reset")
        n, seed = len(reset["agents"]), reset.get("seed", 0)
        ref, ref_events = reference_run(shape["width"], shape["depth"], n, seed, shape["grain"])
        name = os.path.basename(path).split(".")[0]
        design = name.split("__")[0]
        what = f"{shape['depth']} layers of {shape['width']} tasks and a final task, grain {shape['grain']}, seed {seed}"
        rep = dag_replay(ev, **shape, title=f"{design}: {n} agents (seed {seed})",
                         description=f"The {design} team on {what}.", reference=ref, skin=skin)
        reps.append(rep)
        print(f"{rep['title']:<50} {rep['dag']['rounds']} rounds (reference {ref['rounds']}, bound "
              f"{rep['dag']['lower_bound']}), {len(rep['sprints'][0]['events'])} scenes")
        if with_reference:
            r2 = dag_replay(ref_events, **shape, title=f"reference ({ref['sharing']}): {n} agents (seed {seed})",
                            description=f"The scripted reference team ({ref['sharing']} sharing) on {what}.",
                            reference=ref, skin=skin)
            rep["dag"]["pair"] = r2["title"]
            if all(r["title"] != r2["title"] for r in reps):
                reps.append(r2)
    return reps


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", action="store_true", help="LLM teams (any OpenAI-compatible server)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--universe", type=int, default=1)
    ap.add_argument("--max-turns", type=int, default=120)
    ap.add_argument("--out", default="")
    ap.add_argument("--dag", nargs="+", default=[], metavar="TRACE", help="saved traces of DAG runs (netscale)")
    ap.add_argument("--reference", action="store_true", help="with --dag: also the scripted reference team's run")
    ap.add_argument("--skin", choices=["seedville", "campus"], default="",
                    help="how the page draws the town (default: seedville, campus for --dag)")
    a = ap.parse_args()
    here = os.path.join(os.path.dirname(__file__), "..", "web", "replays")
    if a.dag:
        out = a.out or os.path.join(here, "dag.json")
        with open(out, "w") as f:
            json.dump({"replays": dag_replays(a.dag, a.reference, a.skin or "campus")}, f, separators=(",", ":"), default=str)
        print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")
        return
    out = a.out or os.path.join(here, "llm.json" if a.llm else "codeworld.json")
    reps = []
    for title, desc, opt, net, share in SETUPS[:3] if a.llm else SETUPS:
        if a.llm:
            from .llm import LLMConfig, make_model, make_settings
            from .team import run_llm_team

            cfg = LLMConfig()
            model, settings = make_model(cfg), make_settings(cfg)

            def policy(env):
                asyncio.run(run_llm_team(env, model, settings, a.max_turns))
            title = f"{title} ({cfg.model})"
        else:
            def policy(env, share=share):
                solve_codeworld(env, share)
        raw = run(opt, net, a.seed, policy, a.universe)
        reps.append(town_replay(raw, title, desc, a.skin or "seedville"))
        m = raw.metrics()
        print(f"{title:<62} {m['done']}/{m['tasks']} delivered, {m['actions']} actions, {len(raw.events)} events")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        json.dump({"replays": reps}, f, separators=(",", ":"), default=str)
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
