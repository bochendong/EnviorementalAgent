#!/usr/bin/env python
"""Play SeedVille in the browser with the real game engine.

    python scripts/serve_ui.py            # then open http://localhost:8765
    python scripts/serve_ui.py --port 9000 --universe 3

On Nibi, run it on a login node and forward the port:  ssh -L 8765:localhost:8765 nibi
The page (ui/seedville.html) also works without this server, as a replay viewer.
"""

import argparse
import json
import random
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worldseeds.town import TownLaws, TownSeed, grow_town  # noqa: E402
from worldseeds.town.agents import TownHeuristicAgent, TownOracle  # noqa: E402
from worldseeds.town.replay import Recorder, demo_replays  # noqa: E402
from worldseeds.town.seed import TOWN_BLOCKS  # noqa: E402


class Game:
    def __init__(self, universe: int, blocks, surface_seed: int):
        self.seed = TownSeed(laws=TownLaws.from_index(universe), blocks=tuple(blocks), surface_seed=surface_seed)
        self.universe = universe
        self.world = grow_town(self.seed, max_actions=200)

    def payload(self, message: str = "") -> dict:
        return {"live": True, "state": self.world.snapshot(), "message": message, "seed": self.seed.to_dict(),
                "universe": self.universe, "laws": self.seed.laws.describe(list(self.seed.blocks)),
                "goal_text": self.world.task_text()}


GAME = None
PAGE = ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html", "/seedville.html"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(GAME.payload(GAME.world.observe()))
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        global GAME
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        w = GAME.world
        if self.path == "/api/new":
            blocks = [b for b in body.get("blocks", TOWN_BLOCKS) if b in TOWN_BLOCKS] or ["farming"]
            GAME = Game(int(body.get("universe", 0)), blocks, int(body.get("surface_seed", random.randrange(1 << 30))))
            self._json(GAME.payload(GAME.world.observe()))
        elif self.path == "/api/act":
            msg, _ = w.act(body.get("verb"), body.get("target"), body.get("instrument"))
            self._json(GAME.payload(msg))
        elif self.path == "/api/inspect":
            t = body.get("target")
            loc = w.objs[t].location if t in w.objs else None
            if loc == "inv" or loc not in w.rooms or not w.rooms[loc].visited:
                loc = w.agent_room
            w.focus = [loc]
            msg = w.zoom_in(t)
            self._json(GAME.payload(msg))
        elif self.path == "/api/autoplay":
            rec = Recorder(w)
            w.max_actions = w.actions + 80
            try:
                if body.get("policy") == "oracle":
                    TownOracle(w).solve()
                else:
                    TownHeuristicAgent(w, None, random.Random(0)).run()
            except Exception as e:  # the oracle may fail from a state the player messed up
                rec.frames.append(rec._frame("act", "oracle", f"The oracle gave up: {e}"))
            rec.detach()
            self._json({**GAME.payload(), "frames": rec.frames[1:]})
        else:
            self._send(404, b"not found", "text/plain")


def main():
    global GAME, PAGE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--universe", type=int, default=2)
    ap.add_argument("--blocks", nargs="+", default=["farming", "gifting", "schedule"])
    ap.add_argument("--surface-seed", type=int, default=11)
    a = ap.parse_args()
    GAME = Game(a.universe, a.blocks, a.surface_seed)
    page = (ROOT / "ui" / "seedville.html").read_text()
    PAGE = page.replace("/*__REPLAYS__*/null", json.dumps(demo_replays()))
    print(f"SeedVille running at http://localhost:{a.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
