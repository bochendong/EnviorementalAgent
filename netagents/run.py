"""Run agents on the network: a preset (or a provider) in this process, or an environment served over HTTP.

    python -m netagents.run --preset math/hard --variant solo --policy scripted --seeds 0 1 2
    python -m netagents.run --preset website/heldout-todo --policy llm
    python -m netagents.run --remote http://127.0.0.1:8090 --policy llm          # served by scripts/run_net.py

--opt / --net override provider and network options (key=value, values parsed as JSON when they can be).
Writes events and summary.json to --out.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from .client import LocalEnv, RemoteEnv


def kv(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def play(env, policy: str, seed: int, max_turns: int) -> dict:
    if policy == "scripted":
        from .scripted import SOLVERS

        SOLVERS[env.public()["provider"]](env)
    elif policy == "random":
        from .team import random_policy

        random_policy(env, seed=seed)
    else:
        from .llm import LLMConfig, make_model, make_settings
        from .team import run_llm_team

        cfg = LLMConfig()
        return {"agents": asyncio.run(run_llm_team(env, make_model(cfg), make_settings(cfg), max_turns))}
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="")
    ap.add_argument("--variant", default="team", choices=["team", "solo", "nonet"])
    ap.add_argument("--provider", default="")
    ap.add_argument("--opt", nargs="*", default=[])
    ap.add_argument("--net", nargs="*", default=[])
    ap.add_argument("--remote", default="", help="URL of an environment served over HTTP")
    ap.add_argument("--policy", default="scripted", choices=["scripted", "random", "llm"])
    ap.add_argument("--seeds", type=int, nargs="*", default=None)
    ap.add_argument("--max-turns", type=int, default=100)
    ap.add_argument("--out", default="results/net/runs")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = []
    if a.remote:
        env = RemoteEnv(a.remote)
        for seed in a.seeds or [None]:
            if seed is not None:
                env.reset(seed)
            extra = play(env, a.policy, seed or 0, a.max_turns)
            rows.append({"seed": seed, **env.metrics(), **extra})
    else:
        from worldseeds.net import NetConfig, NetworkEnv, presets, providers

        if a.preset:
            prov, opt, net = presets.resolve(a.preset, a.variant)
            seeds = a.seeds if a.seeds is not None else presets.seeds(a.preset, 1)
        else:
            prov, opt, net, seeds = a.provider or "codeworld", {}, {}, a.seeds or [0]
        opt, net = {**opt, **kv(a.opt)}, {**net, **kv(a.net)}
        for seed in seeds:
            raw = NetworkEnv(providers.make(prov, **opt), NetConfig(**net))
            raw.reset(seed)
            env = LocalEnv(raw)
            extra = play(env, a.policy, seed, a.max_turns)
            raw.save_events(os.path.join(a.out, f"events_{prov}_{a.variant}_{seed}.jsonl"))
            rows.append({"seed": seed, **env.metrics(), **extra})
    for r in rows:
        print(json.dumps({k: r.get(k) for k in ("seed", "provider", "solved", "done", "tasks", "actions", "rounds")}))
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump({"preset": a.preset, "variant": a.variant, "policy": a.policy, "runs": rows}, f, indent=1, default=str)
    print(f"solved {sum(bool(r.get('solved')) for r in rows)}/{len(rows)}")


if __name__ == "__main__":
    main()
