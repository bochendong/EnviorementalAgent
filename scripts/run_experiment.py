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

from worldseeds.experiment import PROTOCOLS, add_arguments, from_args, run_experiment  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)  # every option is declared once, in worldseeds/experiment/config.py
    a = p.parse_args()
    if a.protocol not in PROTOCOLS:
        p.error(f"--protocol must be one of {PROTOCOLS}")
    out = run_experiment(from_args(a))
    print(f"done -> {out}/episodes.jsonl")


if __name__ == "__main__":
    main()
