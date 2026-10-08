"""Write the replays shown by web/codeworld.html (SeedVille Workshops).

    python scripts/build_codeworld_web.py                 # web/replays/codeworld.json
    python scripts/build_codeworld_web.py --universe 2 --out my.json

The page plays back exactly what the engine recorded (worldseeds/codeworld/replay.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worldseeds.codeworld.replay import demo_replays  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universe", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "web", "replays", "codeworld.json"))
    a = ap.parse_args()
    reps = demo_replays(a.universe)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump({"replays": reps}, f, separators=(",", ":"))
    for r in reps:
        done = [s["metrics"]["done"] for s in r["sprints"]]
        print(f"{r['title']:<52} delivered per sprint {done} of {r['sprints'][0]['metrics']['projects']}")
    print(f"wrote {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
