#!/usr/bin/env python
"""Build the Phaser client's data: assets, demo replays, and a page body for publishing.

    python scripts/build_web.py                 # regenerate assets + web/replays/demo.json
    python scripts/build_web.py --replay ep.json   # also add replay files (e.g. a Qwen run)

Outputs web/artifact.html: the same page without the <html>/<head>/<body> wrapper, for
hosts that add their own document skeleton.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worldseeds.town.replay import demo_replays  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", nargs="*", default=[])
    ap.add_argument("--skip-assets", action="store_true")
    a = ap.parse_args()
    web = ROOT / "web"
    if not a.skip_assets:
        subprocess.run([sys.executable, str(web / "tools" / "make_assets.py")], check=True)
    reps = demo_replays()
    for f in a.replay:
        d = json.loads(Path(f).read_text())
        reps += d if isinstance(d, list) else [d]
    (web / "replays").mkdir(exist_ok=True)
    (web / "replays" / "demo.json").write_text(json.dumps(reps, separators=(",", ":")))
    page = (web / "index.html").read_text()
    body = page.split("<!--BODY-START-->")[1].split("<!--BODY-END-->")[0]
    (web / "artifact.html").write_text(body.strip() + "\n")
    print(f"web/replays/demo.json: {len(reps)} replays; web/artifact.html written")


if __name__ == "__main__":
    main()
