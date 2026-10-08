"""The street map of the town theme: where each workshop stands and how to walk between places.

Districts are BLOCK x BLOCK tiles with a road every ROAD tiles; together they form one road grid
(``cols`` districts across). Each district has four blocks, each with two workshops facing a road; the
crossing in the middle of district 0 is the plaza. Walking goes along the roads, by the shortest route.
"""

from __future__ import annotations

import math
from collections import deque
from functools import lru_cache

BLOCK, ROAD = 12, 6
QUADS = [(1, 1), (7, 1), (1, 7), (7, 7)]  # top-left tile of each block inside a district
TILES_PER_ACTION = 6  # one block of road costs one action


class CityMap:
    def __init__(self, n_districts: int):
        self.n = n_districts
        self.cols = n_districts if n_districts <= 3 else math.ceil(math.sqrt(n_districts))
        self.rows = math.ceil(n_districts / self.cols)
        self.GX, self.GY = self.cols * BLOCK, self.rows * BLOCK

    def corner(self, d: int) -> tuple[int, int]:
        return (d % self.cols) * BLOCK, (d // self.cols) * BLOCK

    @staticmethod
    def is_road(x: int, y: int) -> bool:
        return x % ROAD == 0 or y % ROAD == 0

    def slot(self, d: int, k: int) -> tuple[tuple[int, int], tuple[int, int]]:
        """(tile, door) of the k-th workshop (0..7) of district d; the door is the road tile in front."""
        cx, cy = self.corner(d)
        qx, qy = QUADS[k // 2]
        if k % 2 == 0:
            t = (cx + qx + 4, cy + qy + 1)
            return t, (t[0] + 1, t[1])
        t = (cx + qx + 1, cy + qy + 4)
        return t, (t[0], t[1] + 1)

    @property
    def plaza(self) -> tuple[int, int]:
        return (ROAD, ROAD)

    @lru_cache(maxsize=None)
    def route(self, a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], ...]:
        """Shortest walk along the roads from road tile a to road tile b (both included)."""
        prev = {a: None}
        q = deque([a])
        while q:
            c = q.popleft()
            if c == b:
                break
            x, y = c
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n not in prev and 0 <= n[0] <= self.GX and 0 <= n[1] <= self.GY and self.is_road(*n):
                    prev[n] = c
                    q.append(n)
        out, c = [], b
        while c is not None:
            out.append(c)
            c = prev[c]
        return tuple(reversed(out))

    @staticmethod
    def corners(path) -> list[list[int]]:
        """The turning points of a path (enough to draw it)."""
        keep = [p for i, p in enumerate(path) if i in (0, len(path) - 1) or
                (path[i - 1][0] - p[0], path[i - 1][1] - p[1]) != (p[0] - path[i + 1][0], p[1] - path[i + 1][1])]
        return [list(p) for p in keep]

    @staticmethod
    def cost(steps: int) -> int:
        return 0 if steps == 0 else math.ceil(steps / TILES_PER_ACTION)

    def to_dict(self) -> dict:
        return {"block": BLOCK, "road": ROAD, "cols": self.cols, "rows": self.rows, "GX": self.GX, "GY": self.GY,
                "plaza": list(self.plaza), "tiles_per_action": TILES_PER_ACTION}
