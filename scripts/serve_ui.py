#!/usr/bin/env python
"""Play SeedVille in the browser (Phaser client in web/) with the real game engine.

    python scripts/serve_ui.py            # then open http://localhost:8765
    python scripts/serve_ui.py --port 9000 --universe 3

On Nibi, run it on a login node and forward the port:  ssh -L 8765:localhost:8765 nibi
Without this server, web/ still works as a replay viewer (any static file server).
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
from worldseeds.town.agents import TownHeuristicAgent, TownOracle, TownSeedMemory  # noqa: E402
from worldseeds.town.library import LibraryArchive  # noqa: E402
from worldseeds.town.replay import Recorder, demo_replays  # noqa: E402
from worldseeds.town.seed import TOWN_BLOCKS, town_seeds_for, town_split  # noqa: E402

LIBRARIES: dict[tuple[int, str], LibraryArchive] = {}  # (universe, mode) -> archive; your notes persist here


def library_for(universe: int, mode: str) -> LibraryArchive | None:
    """The universe's library, written by a librarian from 20 earlier towns (built once per universe)."""
    if mode not in ("categorized", "flat"):
        return None
    if (universe, mode) not in LIBRARIES:
        laws = TownLaws.from_index(universe)
        train, _ = town_split(random.Random(universe))
        mem = TownSeedMemory()
        for s in town_seeds_for(train, laws, 20, random.Random(universe + 100)):
            w = grow_town(s)
            TownHeuristicAgent(w, mem).run()
            mem.consolidate_events(w.events)
        lib = LibraryArchive(mode=mode)
        lib.update_from_seed(mem, 20, author="librarian")
        LIBRARIES[(universe, mode)] = lib
    return LIBRARIES[(universe, mode)]


class Game:
    def __init__(self, universe: int, blocks, surface_seed: int, n_villagers: int = 8, library: str = "categorized"):
        self.seed = TownSeed(laws=TownLaws.from_index(universe), blocks=tuple(blocks), surface_seed=surface_seed,
                             n_villagers=n_villagers)
        self.universe = universe
        self.world = grow_town(self.seed, max_actions=200, library=library_for(universe, library))

    def payload(self, message: str = "") -> dict:
        return {"live": True, "state": self.world.snapshot(), "message": message, "seed": self.seed.to_dict(),
                "universe": self.universe, "laws": self.seed.laws.describe(list(self.seed.blocks)),
                "goal_text": self.world.task_text()}


GAME = None
WEB = ROOT / "web"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json",
         ".png": "image/png", ".md": "text/plain; charset=utf-8"}


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
        path = self.path.split("?")[0]
        if path == "/api/state":
            self._json(GAME.payload(GAME.world.observe()))
            return
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (WEB / rel).resolve()
        if WEB.resolve() not in f.parents or not f.is_file():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

    def do_POST(self):
        global GAME
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        w = GAME.world
        if self.path == "/api/new":
            blocks = [b for b in body.get("blocks", TOWN_BLOCKS) if b in TOWN_BLOCKS] or ["farming"]
            GAME = Game(int(body.get("universe", 0)), blocks, int(body.get("surface_seed", random.randrange(1 << 30))),
                        max(2, min(12, int(body.get("n_villagers", 8)))), str(body.get("library", "categorized")))
            self._json(GAME.payload(GAME.world.observe()))
        elif self.path == "/api/act":
            msg, ok = w.act(body.get("verb"), body.get("target"), body.get("instrument"))
            self._json({**GAME.payload(msg), "ok": ok})
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
                rec.frames.append(rec._frame("act", "oracle()", f"The oracle gave up: {e}"))
            rec.detach()
            self._json({**GAME.payload(), "frames": rec.frames[1:]})
        else:
            self._send(404, b"not found", "text/plain")


def main():
    global GAME
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--universe", type=int, default=2)
    ap.add_argument("--blocks", nargs="+", default=["farming", "gifting", "schedule"])
    ap.add_argument("--surface-seed", type=int, default=11)
    a = ap.parse_args()
    GAME = Game(a.universe, a.blocks, a.surface_seed)
    demo = WEB / "replays" / "demo.json"
    if not demo.exists():
        demo.parent.mkdir(exist_ok=True)
        demo.write_text(json.dumps(demo_replays(), separators=(",", ":")))
    print(f"SeedVille running at http://localhost:{a.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
