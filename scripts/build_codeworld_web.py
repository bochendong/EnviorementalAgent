"""Write the replays shown by web/codeworld.html (SeedVille Workshops).

    python scripts/build_codeworld_web.py                 # web/replays/codeworld.json
    python scripts/build_codeworld_web.py --universe 2 --out my.json
    # LLM apprentices (any OpenAI-compatible server: WS_BASE_URL, WS_MODEL), shown next to the others
    WS_BASE_URL=http://localhost:8000/v1 WS_MODEL=qwen3-8b python scripts/build_codeworld_web.py --llm

The page plays back exactly what the engine recorded (worldseeds/codeworld/replay.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worldseeds.codeworld.replay import demo_replays, record, town_world  # noqa: E402


def llm_replays(index: int, sprints: int, budget: int, max_turns: int) -> list[dict]:
    """The town with money and goals, its apprentices LLM agents: four masters, and four without masters."""
    from worldseeds.codeworld.economy import EconConfig
    from worldseeds.llm import LLMConfig, make_model, make_settings

    lc = LLMConfig()
    model, settings = make_model(lc), make_settings(lc)
    town = town_world(index)
    out = []
    for mode, title in (("owners", "LLM apprentices: four masters, money and goals"),
                        ("random", "LLM apprentices: four without masters, money and goals")):
        out.append(record(town, mode, 4, 12, sprints=sprints, budget=budget, projects_per_dev=3,
                          goals=["banquet", "prize", "fund"], goal_deadline=sprints, fund=300, econ=EconConfig(),
                          model=model, settings=settings, max_turns=max_turns, title=f"{title} ({lc.model})",
                          description=f"Each apprentice is {lc.model}, with tools for machines, asking, money, goals, "
                                      "the notice board and the library. Scores: coins + 5 x reputation, scaled by how "
                                      "the town's goals went."))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universe", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--llm", action="store_true", help="record LLM apprentices instead (web/replays/llm.json)")
    ap.add_argument("--sprints", type=int, default=2)
    ap.add_argument("--budget", type=int, default=80)
    ap.add_argument("--max-turns", type=int, default=120)
    a = ap.parse_args()
    here = os.path.join(os.path.dirname(__file__), "..", "web", "replays")
    a.out = a.out or os.path.join(here, "llm.json" if a.llm else "codeworld.json")
    reps = llm_replays(a.universe, a.sprints, a.budget, a.max_turns) if a.llm else demo_replays(a.universe)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump({"replays": reps}, f, separators=(",", ":"))
    for r in reps:
        done = [s["metrics"]["done"] for s in r["sprints"]]
        print(f"{r['title']:<52} delivered per sprint {done} of {r['sprints'][0]['metrics']['projects']}")
    print(f"wrote {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
