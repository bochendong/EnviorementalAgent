#!/usr/bin/env python
"""Run a World Seeds experiment protocol.

Examples
--------
CPU smoke test (no LLM):
    python scripts/run_experiment.py --protocol compgen --policy heuristic --out results/smoke

LLM run against a local vLLM server (see slurm/serve_and_run.sh):
    WS_BASE_URL=http://localhost:8000/v1 WS_MODEL=qwen3-8b \
    python scripts/run_experiment.py --protocol compgen --conditions none retrieval seed oracle \
        --universes 0 1 2 --views zoom flat --out results/compgen_qwen3_8b
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worldseeds.agent import CONDITIONS  # noqa: E402
from worldseeds.envs import ENV_NAMES  # noqa: E402
from worldseeds.experiment import PROTOCOLS, ExpConfig, run_experiment  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env", choices=ENV_NAMES, default="dungeon", help="dungeon (rooms/doors) or town (SeedVille)")
    p.add_argument("--protocol", choices=PROTOCOLS, default="compgen")
    p.add_argument("--policy", choices=["llm", "heuristic"], default="llm")
    p.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=["none", "retrieval", "seed", "oracle"])
    p.add_argument("--universes", nargs="+", type=int, default=[0, 1, 2])
    p.add_argument("--views", nargs="+", choices=["zoom", "flat"], default=["zoom"])
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--n-train", type=int, default=24)
    p.add_argument("--n-test", type=int, default=16)
    p.add_argument("--n-agents", type=int, default=4)
    p.add_argument("--max-actions", type=int, default=50)
    p.add_argument("--max-turns", type=int, default=120)
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--history-items", type=int, default=40, help="trim agent context to last N items (0=off)")
    p.add_argument("--decay", type=float, default=1.0)
    p.add_argument("--n-distractors", type=int, default=2)
    p.add_argument("--save-traces", action="store_true")
    p.add_argument("--rng-seed", type=int, default=0)
    p.add_argument("--source-errors", nargs="*", type=float, default=[],
                   help="town/board: error rates of library notes and villager testimony (one variant each)")
    p.add_argument("--team-modes", nargs="+",
                   default=["solo", "solo_matched", "independent", "library", "messages", "merged"],
                   choices=["solo", "solo_matched", "independent", "library", "messages", "merged"],
                   help="team protocol (board env): how teammates share what they learned")
    p.add_argument("--n-crops", type=int, default=4, help="town/board: crops per universe (law space size)")
    p.add_argument("--hive-modes", nargs="+", default=["isolated", "serial", "groups", "hive", "sync",
                                                       "hive_verified", "hive_directed", "hive_full"],
                   help="hive protocol: how the agents share memory (see worldseeds/hive.py)")
    p.add_argument("--hive-sizes", nargs="+", type=int, default=[1, 4, 16], help="hive: numbers of agents")
    p.add_argument("--hive-faulty", nargs="+", type=float, default=[0.0], help="hive: shares of faulty agents")
    p.add_argument("--hive-waves", type=int, default=8, help="hive: worlds each agent plays")
    p.add_argument("--trusts", nargs="+", choices=["blind", "calibrated"], default=["blind", "calibrated"],
                   help="heuristic policy only: how the agent weighs second-hand claims")
    p.add_argument("--out", default="results/run")
    a = p.parse_args()
    cfg = ExpConfig(
        protocol=a.protocol, env=a.env, policy=a.policy, conditions=a.conditions, universes=a.universes,
        repeats=a.repeats, views=a.views, n_train=a.n_train, n_test=a.n_test, n_agents=a.n_agents,
        max_actions=a.max_actions, max_turns=a.max_turns, concurrency=a.concurrency, history_items=a.history_items, decay=a.decay,
        n_distractors=a.n_distractors, save_traces=a.save_traces, out_dir=a.out, rng_seed=a.rng_seed,
        source_errors=a.source_errors, trusts=a.trusts, team_modes=a.team_modes,
        n_crops=a.n_crops, hive_modes=a.hive_modes, hive_sizes=a.hive_sizes, hive_faulty=a.hive_faulty,
        hive_waves=a.hive_waves,
    )
    out = run_experiment(cfg)
    print(f"done -> {out}/episodes.jsonl")


if __name__ == "__main__":
    main()
