"""The maps of the town theme: several areas joined at their edges, like the farm, the town, the beach and
the mountain of a farming game.

Every district has four areas: the **town** in the middle, the **farm** to the west, the **mountain** to the
north and the **beach** to the south. The town's east road leads to the next district's farm. Each area is a
W x H tile grid (tile codes below) with two workshops of its own kinds: rooms without a roof whose machines
stand along the back walls, entered by one door.

Walking goes tile by tile (four directions) over walkable tiles, through an area's exit tile into the
neighbouring area; routes are shortest walks over the whole world, and a walk costs one action per
TILES_PER_ACTION tiles.

Tile codes::

    .  ground (grass, sand or dirt by theme)   =  path        p  plaza       b  bridge or pier
    ~  water      ^  rock      T  tree      f  field      h  house      o  small decoration     F  fountain
    w  workshop wall      i  workshop floor      m  machine      d  workshop door
"""

from __future__ import annotations

import math
import random
from collections import deque
from functools import lru_cache

W, H = 22, 14
TILES_PER_ACTION = 16
WALKABLE = set(".=pbid")
THEMES = ["town", "farm", "beach", "mountain"]
AREA_KINDS = {"town": ["bakery", "clinic"], "farm": ["farm", "florist"], "beach": ["inn", "shop"],
              "mountain": ["mine", "smithy"]}
KIND_AREA = {k: t for t, ks in AREA_KINDS.items() for k in ks}
TITLES = {"town": "Town", "farm": "Farm", "beach": "Beach", "mountain": "Mountain"}


def room_tiles(x0: int, y0: int):
    """A workshop of 6 x 5 tiles at (x0, y0): walls around, door in the front (+y) wall, machines along
    the two back walls. Returns (door, centre, [(machine tile, standing tile), ...])."""
    door = (x0 + 3, y0 + 4)
    left = [((x0 + 1, y), (x0 + 2, y if y > y0 + 1 else y0 + 2)) for y in range(y0 + 1, y0 + 4)]
    back = [((x, y0 + 1), (x, y0 + 2)) for x in range(x0 + 2, x0 + 5)]
    more = [((x0 + 4, y0 + 3), (x0 + 3, y0 + 3)), ((x0 + 4, y0 + 2), (x0 + 3, y0 + 2))]
    return door, (x0 + 3, y0 + 3), left + back + more


class Area:
    def __init__(self, name: str, theme: str, district: int, rng: random.Random, machines: int = 6):
        self.name, self.theme, self.district, self.n_machines = name, theme, district, machines
        self.g = [["."] * W for _ in range(H)]
        self.rooms: list[dict] = []  # {"kind", "x", "y", "door", "centre", "machines"}
        self.exits: list[dict] = []  # {"to": area index, "at": (x, y), "arrive": (x, y)}
        getattr(self, "_" + theme)(rng)

    # ------------------------------------------------------------ drawing helpers
    def put(self, x, y, c, over=None):
        if 0 <= x < W and 0 <= y < H and (over is None or self.g[y][x] in over):
            self.g[y][x] = c

    def rect(self, x0, y0, x1, y1, c, over=None):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.put(x, y, c, over)

    def room(self, x0, y0, kind):
        door, centre, machines = room_tiles(x0, y0)
        machines = machines[:max(1, min(self.n_machines, len(machines)))]
        for dy in range(5):
            for dx in range(6):
                self.put(x0 + dx, y0 + dy, "w" if dx in (0, 5) or dy in (0, 4) else "i")
        for m, _ in machines:
            self.put(*m, "m")
        self.put(*door, "d")
        self.put(door[0], door[1] + 1, "=")
        self.rooms.append({"kind": kind, "x": x0, "y": y0, "door": door, "centre": centre, "machines": machines})

    def scatter(self, rng, c, n, x0=0, y0=0, x1=W - 1, y1=H - 1, keep_clear=()):
        for _ in range(n * 6):
            if n <= 0:
                break
            x, y = rng.randint(x0, x1), rng.randint(y0, y1)
            if self.g[y][x] == "." and (x, y) not in keep_clear and not self._near_path(x, y):
                self.g[y][x] = c
                n -= 1

    def _near_path(self, x, y):
        return any(0 <= x + dx < W and 0 <= y + dy < H and self.g[y + dy][x + dx] in "=pdb"
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))

    def border(self, rng, c, p=.55):
        for x in range(W):
            for y in (0, H - 1):
                if self.g[y][x] == "." and rng.random() < p:
                    self.g[y][x] = c
        for y in range(H):
            for x in (0, W - 1):
                if self.g[y][x] == "." and rng.random() < p:
                    self.g[y][x] = c

    # ------------------------------------------------------------ the four kinds of area
    def _town(self, rng):
        self.rect(0, 7, W - 1, 7, "=")
        self.rect(11, 0, 11, H - 1, "=")
        self.rect(9, 6, 13, 8, "p")
        self.room(2, 1, "bakery")
        self.room(14, 1, "clinic")
        for x, y in ((3, 10), (6, 11), (15, 10), (18, 11), (2, 12), (19, 9)):
            self.put(x, y, "h")
        self.put(8, 10, "F")
        self.border(rng, "T")
        self.scatter(rng, "o", 5, 1, 9, W - 2, H - 2)
        self.scatter(rng, "T", 4, 1, 9, W - 2, H - 2)

    def _farm(self, rng):
        self.rect(0, 7, W - 1, 7, "=")
        self.rect(11, 7, 11, H - 2, "=")
        self.room(2, 1, "farm")
        self.room(13, 1, "florist")
        self.rect(1, 9, 8, 12, "f")
        self.rect(13, 9, 20, 12, "f")
        self.rect(20, 1, 21, 4, "~")
        self.border(rng, "T", .4)
        self.scatter(rng, "o", 3, 9, 8, 12, 12)

    def _beach(self, rng):
        self.rect(11, 0, 11, 9, "=")
        self.rect(2, 6, 19, 6, "=")
        self.room(3, 0, "inn")
        self.room(14, 0, "shop")
        self.rect(0, 10, W - 1, H - 1, "~")
        self.rect(11, 10, 11, H - 1, "b")
        self.rect(5, 10, 6, 11, "b")
        for y in range(8, 10):
            for x in range(W):
                if self.g[y][x] == "." and rng.random() < .1:
                    self.g[y][x] = "o"
        self.scatter(rng, "T", 6, 0, 1, W - 1, 9)

    def _mountain(self, rng):
        self.rect(11, 6, 11, H - 1, "=")
        self.rect(3, 6, 19, 6, "=")
        self.room(3, 0, "mine")
        self.room(14, 0, "smithy")
        self.rect(2, 9, 7, 12, "~")
        self.rect(15, 9, 19, 12, "^")
        self.border(rng, "^", .5)
        self.scatter(rng, "T", 8, 1, 7, W - 2, H - 2)
        self.scatter(rng, "^", 4, 1, 7, W - 2, H - 2)

    def walkable(self, x, y) -> bool:
        return 0 <= x < W and 0 <= y < H and self.g[y][x] in WALKABLE


class TownMap:
    """All areas of all districts, their exits, and shortest walks between any two tiles of the world."""

    def __init__(self, n_districts: int, district_names: list[str], seed: str = "", machines: int = 6):
        self.areas: list[Area] = []
        self.index: dict[str, int] = {}
        for d in range(n_districts):
            for theme in THEMES:
                name = theme if n_districts == 1 else f"{district_names[d]}_{theme}"
                self.index[name] = len(self.areas)
                self.areas.append(Area(name, theme, d, random.Random(f"townmap/{seed}/{name}"), machines))
        for d in range(n_districts):
            t, f, b, m = (self.index[self._name(d, th, n_districts, district_names)] for th in THEMES)
            self._join(t, (0, 7), f, (W - 1, 7))
            self._join(t, (11, 0), m, (11, H - 1))
            self._join(t, (11, H - 1), b, (11, 0))
            if d + 1 < n_districts:
                self._join(t, (W - 1, 7), self.index[self._name(d + 1, "farm", n_districts, district_names)], (0, 7))
        # where each map lies in one continuous world grid: maps touch at their exits, so the roads run on
        self.offset, self.mini = {}, {}
        for a in self.areas:
            ox = 2 * W * a.district + (0 if a.theme == "farm" else W)
            oy = {"mountain": -H, "town": 0, "farm": 0, "beach": H}[a.theme]
            self.offset[a.name] = (ox, oy)
            self.mini[a.name] = (2 * a.district + (0 if a.theme == "farm" else 1), oy // H + 1)

    @staticmethod
    def _name(d, theme, n, names):
        return theme if n == 1 else f"{names[d]}_{theme}"

    def _join(self, a, at_a, b, at_b):
        self.areas[a].exits.append({"to": b, "at": at_a, "arrive": at_b})
        self.areas[b].exits.append({"to": a, "at": at_b, "arrive": at_a})

    def room_of(self, district: int, kind: str) -> tuple[int, dict]:
        """(area index, room) of the workshop of ``kind`` in ``district``."""
        theme = KIND_AREA[kind]
        a = next(i for i, ar in enumerate(self.areas) if ar.district == district and ar.theme == theme)
        return a, next(r for r in self.areas[a].rooms if r["kind"] == kind)

    @property
    def plaza(self) -> tuple[int, int, int]:
        return (next(i for i, a in enumerate(self.areas) if a.theme == "town" and a.district == 0), 11, 7)

    def _next(self, node):
        a, x, y = node
        ar = self.areas[a]
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if ar.walkable(nx, ny):
                yield (a, nx, ny)
        for e in ar.exits:
            if e["at"] == (x, y):
                yield (e["to"], *e["arrive"])

    @lru_cache(maxsize=None)
    def route(self, src: tuple[int, int, int], dst: tuple[int, int, int]) -> tuple[tuple[int, int, int], ...]:
        """Shortest walk (area, x, y), ... from src to dst, both included."""
        prev = {src: None}
        q = deque([src])
        while q:
            c = q.popleft()
            if c == dst:
                break
            for n in self._next(c):
                if n not in prev:
                    prev[n] = c
                    q.append(n)
        if dst not in prev:
            raise ValueError(f"no way from {src} to {dst}")
        out, c = [], dst
        while c is not None:
            out.append(c)
            c = prev[c]
        return tuple(reversed(out))

    def legs(self, path) -> list[dict]:
        """A walk split by area, each leg reduced to its turning points (what the client draws)."""
        legs: list[dict] = []
        for a, x, y in path:
            if not legs or legs[-1]["area"] != self.areas[a].name:
                legs.append({"area": self.areas[a].name, "tiles": []})
            legs[-1]["tiles"].append((x, y))
        for leg in legs:
            t = leg.pop("tiles")
            leg["path"] = [list(p) for i, p in enumerate(t) if i in (0, len(t) - 1) or
                           (t[i - 1][0] - p[0], t[i - 1][1] - p[1]) != (p[0] - t[i + 1][0], p[1] - t[i + 1][1])]
        return legs

    @staticmethod
    def cost(steps: int) -> int:
        return 0 if steps == 0 else math.ceil(steps / TILES_PER_ACTION)

    def to_dict(self) -> dict:
        return {"W": W, "H": H, "tiles_per_action": TILES_PER_ACTION,
                "plaza": {"area": self.areas[self.plaza[0]].name, "x": self.plaza[1], "y": self.plaza[2]},
                "areas": [{"name": a.name, "theme": a.theme, "district": a.district, "title": TITLES[a.theme],
                           "mini": list(self.mini[a.name]), "offset": list(self.offset[a.name]), "grid": ["".join(r) for r in a.g],
                           "exits": [{"to": self.areas[e["to"]].name, "at": list(e["at"]), "arrive": list(e["arrive"])}
                                     for e in a.exits]} for a in self.areas]}
