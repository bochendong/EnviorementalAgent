"""Record runs in the town (CodeWorld provider, town theme) for web/codeworld.html.

    python -m netagents.replays                    # reference teams -> web/replays/codeworld.json
    WS_BASE_URL=... WS_MODEL=qwen3-8b python -m netagents.replays --llm      # LLM teams -> web/replays/llm.json
    python -m netagents.replays --events run.jsonl ...   (not needed: any LocalEnv run can be turned into a replay)

Each replay is one run of one team; the page shows exactly what the environment recorded
(worldseeds/net/replay.py turns the event log into scenes).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from worldseeds.net import NetConfig, NetworkEnv, providers
from worldseeds.net.replay import town_replay

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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", action="store_true", help="LLM teams (any OpenAI-compatible server)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--universe", type=int, default=1)
    ap.add_argument("--max-turns", type=int, default=120)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    here = os.path.join(os.path.dirname(__file__), "..", "web", "replays")
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
        reps.append(town_replay(raw, title, desc))
        m = raw.metrics()
        print(f"{title:<62} {m['done']}/{m['tasks']} delivered, {m['actions']} actions, {len(raw.events)} events")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        json.dump({"replays": reps}, f, separators=(",", ":"), default=str)
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
