#!/usr/bin/env python
"""Play one world: as a human (--mode human), with the oracle, or with the LLM agent.

    python scripts/play.py --mode human --blocks lockable fragile machine --universe 1
    python scripts/play.py --mode oracle --blocks lockable powered pushable
    WS_BASE_URL=http://localhost:8000/v1 python scripts/play.py --mode llm --condition oracle --verbose
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worldseeds import Laws, WorldSeed, grow  # noqa: E402
from worldseeds.oracle import Oracle  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["human", "oracle", "llm"], default="human")
    ap.add_argument("--blocks", nargs="+", default=["lockable", "container", "fragile"])
    ap.add_argument("--universe", type=int, default=0)
    ap.add_argument("--rooms", type=int, default=3)
    ap.add_argument("--surface-seed", type=int, default=7)
    ap.add_argument("--flat", action="store_true")
    ap.add_argument("--condition", default="none")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    seed = WorldSeed(laws=Laws.from_index(a.universe), blocks=tuple(a.blocks), n_rooms=a.rooms,
                     surface_seed=a.surface_seed)
    w = grow(seed, eager=a.flat)
    print("seed:", seed.to_dict())
    if a.mode == "oracle":
        n = Oracle(w).solve()
        print("\n".join(ev.line() for ev in w.events))
        print(f"oracle solved in {n} actions")
        return
    if a.mode == "llm":
        from worldseeds.agent import run_episode
        from worldseeds.heuristic import seed_from_laws
        from worldseeds.llm import LLMConfig, make_model, make_settings
        from worldseeds.memory import OracleSeed

        cfg = LLMConfig()
        mem = seed_from_laws(seed.laws) if a.condition == "seed" else None
        metrics, ctx = asyncio.run(run_episode(
            w, a.condition, make_model(cfg), make_settings(cfg), seed=mem,
            oracle=OracleSeed(seed.laws) if a.condition == "oracle" else None))
        if a.verbose:
            for t in ctx.trace:
                print(f">>> {t['tool']}({t['args']})\n{t['out']}\n")
        print(metrics)
        return
    print("Commands: look | in <id> | out | <verb> <target> [instrument] | quit")
    print(w.observe())
    while not w.done and not w.out_of_budget:
        try:
            cmd = input("> ").split()
        except EOFError:
            break
        if not cmd:
            continue
        if cmd[0] == "quit":
            break
        if cmd[0] == "look":
            print(w.observe())
        elif cmd[0] == "in" and len(cmd) > 1:
            print(w.zoom_in(cmd[1]))
        elif cmd[0] == "out":
            print(w.zoom_out())
        else:
            print(w.act(cmd[0], cmd[1] if len(cmd) > 1 else None, cmd[2] if len(cmd) > 2 else None)[0])
    print("success" if w.done else "not solved", f"actions={w.actions}")


if __name__ == "__main__":
    main()
