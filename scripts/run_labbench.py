#!/usr/bin/env python
"""LAB-Bench multiple choice for one model, against an OpenAI-compatible server (the transfer study).

    # once, on a login node (compute nodes are offline):
    hf download futurehouse/lab-bench --repo-type dataset --local-dir $SCRATCH/worldseeds/data/lab-bench
    # then, with the model served (slurm/serve_and_run.sh runs it after a SeedVille job, see submit_transfer.sh):
    WS_BASE_URL=http://localhost:8000/v1 WS_MODEL=qwen3-8b \\
    python scripts/run_labbench.py --data $SCRATCH/worldseeds/data/lab-bench --out results/labbench/qwen3-8b.json

By default the configs answerable from the question text (ProtocolQA, SeqQA, CloningScenarios). Each
question gets the LAB-Bench refusal option; metrics: accuracy, precision (of answered), coverage.
"""

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worldseeds.transfer import TEXT_CONFIGS, load_labbench, mcq_summary, run_mcq  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="local copy of futurehouse/lab-bench")
    ap.add_argument("--configs", nargs="+", default=TEXT_CONFIGS)
    ap.add_argument("--limit", type=int, default=0, help="at most this many questions per config (0 = all)")
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    items = []
    for c in a.configs:
        got = load_labbench(a.data, c)
        if not got:
            print(f"warning: no items for {c} under {a.data}")
        items += got[: a.limit] if a.limit else got
    if not items:
        sys.exit("no LAB-Bench items found")
    model = os.environ.get("WS_MODEL", "qwen3-8b")
    res = asyncio.run(run_mcq(items, os.environ.get("WS_BASE_URL", "http://localhost:8000/v1"), model,
                              os.environ.get("WS_API_KEY", "EMPTY"), a.concurrency))
    by = defaultdict(list)
    for r in res:
        by[r["config"]].append(r)
    out = {"model": model, "overall": mcq_summary(res), "configs": {c: mcq_summary(v) for c, v in by.items()},
           "results": res}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1))
    for c, s in [("overall", out["overall"]), *out["configs"].items()]:
        print(f"{c:18s} n={s['n']:4d} accuracy={s['accuracy']:.3f} precision={s['precision']:.3f} "
              f"coverage={s['coverage']:.3f}")


if __name__ == "__main__":
    main()
