#!/usr/bin/env python
"""Bake replays into the pixel UI so it works as a standalone page (no server).

    python scripts/build_ui.py                                  # demo replays -> ui/seedville_demo.html
    python scripts/build_ui.py --replay my_run.json --out ui/my_run.html

Make replay JSON files from experiment runs with scripts/export_replay.py.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worldseeds.town.replay import demo_replays  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", nargs="*", default=[], help="replay JSON files to include (after the demos)")
    ap.add_argument("--no-demo", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "ui" / "seedville_demo.html"))
    a = ap.parse_args()
    replays = [] if a.no_demo else demo_replays()
    for f in a.replay:
        d = json.loads(Path(f).read_text())
        replays += d if isinstance(d, list) else [d]
    page = (ROOT / "ui" / "seedville.html").read_text()
    Path(a.out).write_text(page.replace("/*__REPLAYS__*/null", json.dumps(replays, separators=(",", ":"))))
    print(f"wrote {a.out} with {len(replays)} replays")


if __name__ == "__main__":
    main()
