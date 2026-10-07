#!/usr/bin/env python
"""Turn an LLM episode from an experiment run into a replay for the pixel UI.

    python scripts/export_replay.py results/town_pilot --list            # show available episodes
    python scripts/export_replay.py results/town_pilot --chain town-compgen-u1-seed-zoom-r0 --episode 5 \\
        -o qwen_ep5.json
    then open the SeedVille page and use "Load replay", or bake it in:
    python scripts/build_web.py --replay qwen_ep5.json

Needs a run made with --save-traces. Only town episodes that start from a fresh town
(goal_index 0) can be re-simulated.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worldseeds.town.library import LibraryArchive  # noqa: E402
from worldseeds.town.replay import replay_trace  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--chain")
    ap.add_argument("--episode", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-o", "--out", default="replay.json")
    a = ap.parse_args()
    d = Path(a.run_dir)
    rows = [json.loads(x) for x in (d / "episodes.jsonl").open() if x.strip()]
    rows = [r for r in rows if r.get("env") in ("town", "board") and r.get("seed") and r.get("goal_index", 0) == 0]
    if a.list:
        for r in rows:
            print(f"{r['chain']}  episode {r['episode']:3d}  {r['phase']:5s}  {r['composition']:35s} "
                  f"success={r['success']} actions={r['actions']}")
        return
    row = next(r for r in rows if r["chain"] == a.chain and r["episode"] == a.episode)
    traces = [json.loads(x) for x in (d / "traces.jsonl").open() if x.strip()]
    tr = next(t for t in traces if t["key"] == a.chain and t["episode"] == a.episode)
    title = f"{row['llm']} · {row['condition']} · episode {row['episode']}"
    lib = LibraryArchive.from_dict(row["library"]) if row.get("library") else None
    rep = replay_trace(row["seed"], tr["trace"], title=title, library=lib)
    Path(a.out).write_text(json.dumps(rep))
    print(f"wrote {a.out}: {len(rep['frames'])} frames, success={rep['success']}")


if __name__ == "__main__":
    main()
