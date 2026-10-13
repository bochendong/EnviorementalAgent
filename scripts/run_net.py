#!/usr/bin/env python
"""Run a network of agents on a task provider.

    python scripts/run_net.py --provider math --policy scripted --seeds 0 1 2
    python scripts/run_net.py --provider website --policy llm --net budget=150 latency=1 --opt change=0.05
    python scripts/run_net.py --provider molecule --serve 8090          # HTTP API for outside agents
    python scripts/run_net.py --preset math/hard --variant solo --policy llm --seeds 0 1 2
    python scripts/run_net.py --list-presets

--preset takes a ready-made setting (worldseeds/net/presets.py) and --variant one of team, solo, nonet;
--opt and --net then override it. --opt sets provider options and --net network options (NetConfig), as key=value (values parsed as JSON
when they can be: budget=150, team=0.5, agents='{"explorer": 3, "algebraist": 2}').
Writes events.jsonl (one per seed) and summary.json to --out.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worldseeds.net import NetConfig, NetworkEnv, providers  # noqa: E402


def kv(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="codeworld", choices=sorted(providers.PROVIDERS))
    ap.add_argument("--opt", nargs="*", default=[], help="provider options key=value")
    ap.add_argument("--net", nargs="*", default=[], help="NetConfig options key=value")
    ap.add_argument("--preset", default="", help="a preset name, e.g. math/hard")
    ap.add_argument("--variant", default="team", choices=["team", "solo", "nonet"])
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--policy", default="scripted", choices=["scripted", "random", "llm"])
    ap.add_argument("--seeds", type=int, nargs="*", default=None,
                    help="default: 0, or a preset's first verified seed")
    ap.add_argument("--max-turns", type=int, default=100)
    ap.add_argument("--out", default="results/net")
    ap.add_argument("--serve", type=int, default=0, help="serve the HTTP API on this port instead")
    a = ap.parse_args()

    from worldseeds.net import presets

    if a.list_presets:
        for name, p in presets.PRESETS.items():
            print(f"{name:28s} {p['note']}")
        return
    os.makedirs(a.out, exist_ok=True)
    opt, net = kv(a.opt), kv(a.net)
    if a.preset:
        a.provider, popt, pnet = presets.resolve(a.preset, a.variant)
        opt, net = {**popt, **opt}, {**pnet, **net}
    a.seeds = a.seeds if a.seeds is not None else (presets.seeds(a.preset, 1) if a.preset else [0])
    if a.serve:
        from worldseeds.net.server import serve

        env = NetworkEnv(providers.make(a.provider, **opt), NetConfig(**net))
        env.reset(a.seeds[0])
        print(f"serving {a.provider} on http://127.0.0.1:{a.serve}", flush=True)
        serve(env, port=a.serve)
        return
    rows = []
    for seed in a.seeds:
        env = NetworkEnv(providers.make(a.provider, **opt), NetConfig(**net))
        env.reset(seed)
        if a.policy == "scripted":
            from worldseeds.net.solvers import SOLVERS

            m = SOLVERS[a.provider](env)
        elif a.policy == "random":
            from worldseeds.net.team import random_policy

            m = random_policy(env, seed=seed)
        else:
            from worldseeds.llm import LLMConfig, make_model, make_settings
            from worldseeds.net.team import run_llm_team

            cfg = LLMConfig()
            m = asyncio.run(run_llm_team(env, make_model(cfg), make_settings(cfg), a.max_turns))
        env.save_events(os.path.join(a.out, f"events_{a.provider}_{seed}.jsonl"))
        rows.append({"seed": seed, **m})
        print(json.dumps({k: m[k] for k in ("provider", "solved", "done", "tasks", "actions", "messages")}))
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump({"provider": a.provider, "preset": a.preset, "variant": a.variant, "policy": a.policy,
                   "opt": opt, "net": net, "runs": rows}, f,
                  indent=1, default=str)
    print(f"solved {sum(r['solved'] for r in rows)}/{len(rows)}")


if __name__ == "__main__":
    main()
