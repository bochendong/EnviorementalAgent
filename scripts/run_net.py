#!/usr/bin/env python
"""Serve the agent-network environment over HTTP, so agents in any process or language can take part.

    python scripts/run_net.py --preset math/hard --variant solo --serve 8090
    python scripts/run_net.py --provider website --opt change=0.05 --net budget=60 latency=1 --serve 8090
    python scripts/run_net.py --list-presets

Agents live in netagents/ (``python -m netagents.run --remote http://127.0.0.1:8090 --policy llm``).
--opt sets provider options and --net network options, as key=value (values parsed as JSON when they can be).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worldseeds.net import NetConfig, NetworkEnv, presets, providers  # noqa: E402
from worldseeds.net.server import serve  # noqa: E402


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
    ap.add_argument("--preset", default="")
    ap.add_argument("--variant", default="team", choices=list(presets.VARIANTS))
    ap.add_argument("--provider", default="codeworld", choices=sorted(providers.PROVIDERS))
    ap.add_argument("--opt", nargs="*", default=[])
    ap.add_argument("--net", nargs="*", default=[])
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--serve", type=int, default=8090)
    ap.add_argument("--list-presets", action="store_true")
    a = ap.parse_args()
    if a.list_presets:
        for name, p in presets.PRESETS.items():
            print(f"{name:28s} {p['note']}")
        return
    prov, opt, net = (presets.resolve(a.preset, a.variant) if a.preset else (a.provider, {}, {}))
    env = NetworkEnv(providers.make(prov, **{**opt, **kv(a.opt)}), NetConfig(**{**net, **kv(a.net)}))
    seed = a.seed if a.seed is not None else (presets.seeds(a.preset, 1)[0] if a.preset else 0)
    env.reset(seed)
    print(f"serving {a.preset or prov} (seed {seed}) on http://127.0.0.1:{a.serve}", flush=True)
    serve(env, port=a.serve)


if __name__ == "__main__":
    main()
