#!/usr/bin/env python
"""Small, bright isometric sprites for the maps of SeedVille Workshops (web/codeworld.html).

    python web/tools/kairoart.py          # writes web/assets/kairo.png + kairo.json

Original procedural art in the spirit of cosy management games: 2:1 tiles of 32 x 16, thick dark outlines,
saturated colours. Workshops are rooms without a roof (back walls, low front walls, a floor per trade) so the
machines and the apprentices inside stay visible.

Frames: a ground tile is 32 x 16 with its top vertex at (16, 0). Anything standing on a tile is 32 wide and
its tile diamond fills the bottom 16 rows (top vertex at (16, height - 16)).
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from isoart import Iso, tri  # noqa: E402
from pixel import OUT, Atlas, C, hx, mix, shade  # noqa: E402

TW, TH = 32, 16
WHITE = hx("#ffffff")


# ---------------------------------------------------------------------------- ground
def ground(fill, seed=0):
    """A 32 x 16 diamond; fill(u, v, rng) -> colour, where u, v in [0, 1) run along the two grid axes."""
    rng = random.Random(seed)
    c = C(TW, TH)
    for y in range(TH):
        hw = (y + 1) * 2 if y < TH // 2 else (TH - y) * 2
        for x in range(TW // 2 - hw, TW // 2 + hw):
            u = (x - TW / 2) / TW + y / TH
            v = -(x - TW / 2) / TW + y / TH
            c.p(x, y, fill(min(.999, max(0, u)), min(.999, max(0, v)), rng))
    return c


def speckle(base, dots, p):
    b, ds = hx(base), [hx(d) for d in dots]
    return lambda u, v, rng: rng.choice(ds) if rng.random() < p else b


def checker(a, b, n=2):
    a, b = hx(a), hx(b)
    return lambda u, v, rng: a if (int(u * n) + int(v * n)) % 2 == 0 else b


def planks(a, b, along="u", n=4):
    a, b = hx(a), hx(b)
    def f(u, v, rng):
        k = v if along == "u" else u
        edge = (k * n) % 1 < .12
        return b if edge else a
    return f


def field(u, v, rng):
    soil, dark, sprout = hx("#8a5a32"), hx("#6b4226"), hx("#5fbf3a")
    row = (u * 4) % 1
    if row < .25:
        return dark
    if .45 < row < .7 and (v * 6) % 1 < .5:
        return sprout
    return soil


def water(phase):
    def f(u, v, rng):
        base, hi = hx("#3f8ed8"), hx("#8fd0f5")
        if ((u * 3 + v * 2 + phase * .5) % 1) < .08 and rng.random() < .8:
            return hi
        return base if rng.random() > .05 else hx("#4a9be0")
    return f


def path_stone(u, v, rng):
    a, b, line = hx("#d9cdb2"), hx("#cbbd9e"), hx("#b3a483")
    if (u * 3) % 1 < .07 or (v * 3) % 1 < .07:
        return line
    return a if (int(u * 3) + int(v * 3)) % 2 else b


# ---------------------------------------------------------------------------- standing things
class Thing:
    """An Iso canvas for something standing on one tile; at(gx, gy) is the screen point of tile units."""

    def __init__(self, h):
        self.H = h + TH
        self.iso = Iso(TW, self.H)
        self.base = self.H - TH

    def at(self, gx, gy):
        return 16 + gx - gy, self.base + (gx + gy) // 2

    def box(self, gx, gy, wx, wy, h, pal, windows=None, roof="plain"):
        ox, oy = self.at(gx, gy)
        return self.iso.box(ox, oy, wx, wy, h, pal, windows, random.Random(0), roof=roof)

    def done(self):
        return self.iso.finish()


def blob(t, cx, cy, r, ramp, rng):
    t.iso.c.blob(cx, cy, r, ramp, light=(-1, -1.2), rng=rng)
    for y in range(cy - r - 1, cy + r + 2):  # mark as a face so outlines treat it as one object
        for x in range(cx - r - 1, cx + r + 2):
            if 0 <= x < TW and 0 <= y < t.H and t.iso.c.px[x, y][3]:
                t.iso.face[y][x] = 500


LEAF = [hx("#2f6e2a"), hx("#3f8f34"), hx("#5bb544"), hx("#8bd65c")]
PINE = [hx("#1f4f3a"), hx("#2b6a48"), hx("#3b8a58"), hx("#5aa86e")]


def tree_round(seed):
    rng = random.Random(seed)
    t = Thing(30)
    t.box(7, 7, 3, 3, 8, tri("#8a5a32"))
    blob(t, 16, t.base - 10, 8, LEAF, rng)
    blob(t, 12, t.base - 14, 5, LEAF, rng)
    return t.done()


def tree_pine(seed):
    t = Thing(34)
    t.box(7, 7, 3, 3, 5, tri("#7a4a2a"))
    c = t.iso.c
    for k in range(4):
        w = 3 + k * 2
        top = t.base - 22 + k * 6
        for j in range(7):
            y = top + j
            half = max(1, (w * (j + 2)) // 8)
            for x in range(16 - half, 16 + half + 1):
                col = PINE[3] if x < 15 else PINE[2] if x < 18 else PINE[1]
                if j == 6:
                    col = PINE[0]
                c.p(x, y, col)
                t.iso.face[y][x] = 501
    return t.done()


def tree_palm(seed):
    rng = random.Random(seed)
    t = Thing(34)
    c = t.iso.c
    trunk = [hx("#b98a52"), hx("#94683a")]
    for k in range(22):
        x, y = 16 + (k // 6), t.base + 4 - k
        c.p(x, y, trunk[k % 2]); c.p(x + 1, y, trunk[1])
        t.iso.face[y][x] = t.iso.face[y][x + 1] = 502
    top = (19, t.base - 18)
    for dx, dy in ((-9, 3), (-6, 6), (8, 4), (6, 7), (0, -2), (-3, 0), (4, 0)):
        for s in range(9):
            x = top[0] + dx * s // 9
            y = top[1] + dy * s // 9 + (s * s) // 30
            for w in (0, 1):
                if 0 <= x + w < TW:
                    c.p(x + w, y, LEAF[2] if s < 6 else LEAF[1])
                    t.iso.face[y][x + w] = 503
    c.p(top[0], top[1] + 1, hx("#6b3e1e")); c.p(top[0] + 2, top[1] + 2, hx("#6b3e1e"))
    _ = rng
    return t.done()


def bush(seed, flowers=None):
    rng = random.Random(seed)
    t = Thing(14)
    blob(t, 16, t.base + 3, 6, LEAF, rng)
    if flowers:
        for _ in range(5):
            t.iso.c.p(16 + rng.randint(-4, 4), t.base + rng.randint(-1, 6), hx(flowers))
    return t.done()


def rock(big=False):
    t = Thing(14 if big else 8)
    pal = tri("#9a9aa6")
    if big:
        t.box(2, 2, 12, 12, 10, pal)
        t.box(4, 4, 6, 6, 13, tri("#aeb0bb"))
    else:
        t.box(4, 4, 8, 8, 5, pal)
    return t.done()


def house(wall, roof, seed=0):
    t = Thing(26)
    t.box(2, 2, 12, 12, 10, tri(wall), windows=lambda a, b, w, h, base, rng, side:
          hx("#3a4a70") if 3 <= b <= 6 and a % 6 in (2, 3) and 1 < a < w - 1 else
          (hx("#7a4a26") if side == "l" and 6 <= a <= 8 and b < 7 else base))
    ox, oy = t.at(2, 2)
    t.iso.pyramid(ox, oy - 10, 12, 12, tri(roof), 77)
    return t.done()


def fountain():
    t = Thing(14)
    t.box(1, 1, 14, 14, 3, tri("#d8d2c2"))
    ox, oy = t.at(3, 3)
    t.iso.diamond(ox, oy - 3, 10, 10, hx("#5aa6e6"), 60)
    t.box(7, 7, 2, 2, 9, tri("#e8e2d2"))
    c = t.done()
    for k, (dx, dy) in enumerate(((-2, -12), (2, -12), (0, -13), (-4, -9), (4, -9))):
        c.p(16 + dx, (t.base + 8) + dy, hx("#bfe6ff"))
    return c


def lamp():
    t = Thing(22)
    t.box(7, 7, 2, 2, 18, tri("#4c5262"))
    t.box(6, 6, 4, 4, 4, {"top": hx("#ffe58a"), "left": hx("#ffd24a"), "right": hx("#e0aa2a")})
    return t.done()


def small(kind):
    t = Thing(10)
    if kind == "barrel":
        t.box(5, 5, 6, 6, 7, tri("#9a6236"))
        t.box(5, 5, 6, 6, 2, tri("#5d6068"))
    elif kind == "crate":
        t.box(4, 4, 8, 8, 6, tri("#c08a4a"))
    elif kind == "umbrella":
        t.box(7, 7, 2, 2, 8, tri("#e8e2d2"))
        ox, oy = t.at(2, 2)
        t.iso.pyramid(ox, oy - 8, 12, 12, tri("#e8584a"), 80)
    elif kind == "sign":
        t.box(7, 7, 2, 2, 7, tri("#7a4a26"))
        t.box(3, 7, 10, 2, 4, tri("#c9955a"))
    return t.done()


# ---------------------------------------------------------------------------- workshops
TRADE = {  # wall, trim/roof accent, floor
    "bakery": ("#f3dcae", "#e0823a", planks("#d9a066", "#b97f48")),
    "smithy": ("#9aa0ac", "#59606e", checker("#7d828e", "#6c717c")),
    "florist": ("#f6c6d2", "#5bb544", checker("#dff2d0", "#c8e6b4")),
    "mine": ("#a87a4e", "#5a3a20", planks("#9a7048", "#7a5434", "v")),
    "clinic": ("#f4f6fa", "#3f7fd0", checker("#ffffff", "#d6e6f8")),
    "inn": ("#c8654a", "#7a3020", planks("#b8744a", "#94563a")),
    "shop": ("#a9cdf0", "#3f6fc4", checker("#f3e7cc", "#e0cfa8")),
    "farm": ("#d24a3a", "#f4f0e6", speckle("#e6c870", ["#d4b45a", "#f0d888"], .3)),
}


def wall(kind, axis, low=False, window=False):
    """A wall on one edge of a tile: axis 'x' runs along the back (-y) edge, 'y' along the back (-x) edge;
    low walls stand on the front (+y / +x) edges."""
    w, accent, _ = TRADE[kind]
    h = 5 if low else 20
    t = Thing(h + 2)
    pal = tri(w)
    pal = {**pal, "top": hx(accent)}

    def deco(a, b, width, hh, base, rng, side):
        if low:
            return base
        if b >= hh - 3:
            return shade(hx(accent), .95 if side == "l" else .75)
        if b < 2:
            return shade(base, .85)
        if window and 4 <= a <= width - 5 and 7 <= b <= 14:
            glass = mix(hx("#7fb6e8"), WHITE, .25 if (a + b) % 5 else .6)
            return glass if 5 <= a <= width - 6 and 8 <= b <= 13 else shade(hx(accent), .9)
        return base

    if axis == "x":
        t.box(0, 13 if low else 0, 16, 3, h, pal, deco)
    else:
        t.box(13 if low else 0, 0, 3, 16, h, pal, deco)
    return t.done()


def machine(kind, v):
    """One machine of a trade (two looks per trade)."""
    t = Thing(20)
    if kind == "bakery":
        if v == 0:  # oven
            t.box(2, 2, 12, 12, 12, tri("#c8563a"), lambda a, b, w, h, base, r, s:
                  (hx("#ffb02e") if 3 <= b <= 6 and 3 <= a <= w - 4 else hx("#3a2018") if 2 <= b <= 7 and 2 <= a <= w - 3 else base)
                  if s == "l" else base)
            t.box(9, 3, 3, 3, 16, tri("#8a8f9c"))
        else:  # mixer
            t.box(3, 3, 10, 10, 6, tri("#f4f4f4"))
            t.box(5, 5, 6, 6, 4, tri("#e8c88a"))
    elif kind == "smithy":
        if v == 0:  # anvil
            t.box(5, 4, 6, 8, 4, tri("#4c5262"))
            t.box(3, 3, 10, 10, 3, tri("#3a3f4c"))
            t.box(3, 3, 10, 10, 0, tri("#3a3f4c"))
            t.box(2, 5, 12, 6, 3, tri("#6c7280"))
        else:  # forge
            t.box(2, 2, 12, 12, 8, tri("#7a7f8c"))
            t.box(4, 4, 8, 8, 1, {"top": hx("#ff8a2a"), "left": hx("#ff6a2a"), "right": hx("#d24a1a")})
    elif kind == "florist":
        t.box(2, 2, 12, 12, 5, tri("#b97f48"))
        rng = random.Random(v)
        for _ in range(9):
            col = hx(["#f05a7a", "#ffd24a", "#b47ae8", "#ffffff"][rng.randint(0, 3) if v else rng.randint(0, 1)])
            x, y = rng.randint(10, 22), t.base + rng.randint(-1, 5)
            t.iso.c.rect(x, y - 1, 2, 2, col)
            t.iso.c.p(x, y + 1, hx("#3f8f34"))
    elif kind == "mine":
        if v == 0:  # ore cart
            t.box(3, 2, 10, 12, 7, tri("#6e5a4a"))
            for dx, dy, col in ((14, -8, "#c9c2b0"), (17, -9, "#f2b632"), (19, -7, "#8fa6c8")):
                t.iso.c.rect(dx, t.base + 8 + dy, 3, 2, hx(col))
        else:  # drill
            t.box(3, 3, 10, 10, 9, tri("#e8b832"))
            t.box(7, 7, 2, 2, 17, tri("#5d6068"))
    elif kind == "clinic":
        if v == 0:  # bed
            t.box(2, 4, 12, 8, 4, tri("#ffffff"))
            t.box(2, 4, 4, 8, 6, tri("#e8eef8"))
            t.box(6, 4, 8, 8, 5, tri("#6fa6e6"))
        else:  # cabinet
            t.box(3, 3, 10, 10, 15, tri("#f4f6fa"), lambda a, b, w, h, base, r, s:
                  hx("#e04a3a") if s == "l" and ((4 <= a <= 6 and 7 <= b <= 11) or (3 <= a <= 7 and 8 <= b <= 10)) else base)
    elif kind == "inn":
        if v == 0:  # barrel
            t.box(4, 4, 8, 8, 10, tri("#9a6236"))
            t.box(4, 4, 8, 8, 3, tri("#5d6068"))
        else:  # table with mugs
            t.box(3, 3, 10, 10, 6, tri("#b8744a"))
            t.iso.c.rect(14, t.base - 4, 2, 3, hx("#f2d27a")); t.iso.c.rect(18, t.base - 3, 2, 3, hx("#f2d27a"))
    elif kind == "shop":
        if v == 0:  # shelf
            t.box(3, 5, 10, 6, 16, tri("#b97f48"), lambda a, b, w, h, base, r, s:
                  (hx(["#e8584a", "#3f6fc4", "#f2b632", "#5bb544"][(a // 3) % 4]) if b % 5 in (1, 2) and 1 <= a < w - 1 else base)
                  if s == "l" else base)
        else:  # counter with till
            t.box(2, 3, 12, 10, 7, tri("#d9c08a"))
            t.box(8, 5, 4, 4, 11, tri("#4c5262"))
    elif kind == "farm":
        if v == 0:  # produce crate
            t.box(3, 3, 10, 10, 5, tri("#c08a4a"))
            for k, col in enumerate(("#e8584a", "#f2b632", "#5bb544", "#e8584a")):
                t.iso.c.rect(12 + k * 2, t.base + 1 - (k % 2), 2, 2, hx(col))
        else:  # milk churn
            t.box(5, 5, 6, 6, 11, tri("#c9ccd6"))
            t.box(6, 6, 4, 4, 13, tri("#9a9eaa"))
    return t.done()


def looks():
    """One sprite per kind of machine (see worldseeds/codeworld/recipes.py LOOK)."""
    out = {}
    wood, stone = tri("#b97f48"), tri("#9a9aa6")
    # mill: a millstone on a wooden base
    t = Thing(18); t.box(3, 3, 10, 10, 5, wood); t.box(4, 4, 8, 8, 4, tri("#c9c2b0")); t.box(7, 7, 2, 2, 12, tri("#7a4a26"))
    out["mill"] = t.done()
    # churn: a tall wooden barrel with a plunger
    t = Thing(20); t.box(5, 5, 6, 6, 11, tri("#c08a4a")); t.box(5, 5, 6, 6, 2, tri("#5d6068")); t.box(7, 7, 2, 2, 16, tri("#7a4a26"))
    out["churn"] = t.done()
    # rack: a drying frame hung with green bundles
    t = Thing(20); t.box(2, 7, 12, 2, 14, wood, lambda a, b, w, h, base, r, s:
        hx("#5bb544") if s == "l" and b < 11 and b > 3 and a % 3 == 1 else base)
    out["rack"] = t.done()
    # press: a screw press
    t = Thing(18); t.box(3, 3, 10, 10, 4, wood); t.box(4, 7, 8, 2, 12, tri("#7a4a26")); t.box(7, 7, 2, 2, 15, tri("#5d6068"))
    out["press"] = t.done()
    # oven: brick with a glowing mouth and a chimney
    t = Thing(20)
    t.box(2, 2, 12, 12, 11, tri("#c8563a"), lambda a, b, w, h, base, r, s:
          (hx("#ffb02e") if 3 <= b <= 5 and 3 <= a <= w - 4 else hx("#3a2018") if 2 <= b <= 7 and 2 <= a <= w - 3 else base)
          if s == "l" else base)
    t.box(9, 3, 3, 3, 16, tri("#8a8f9c"))
    out["oven"] = t.done()
    # furnace: stone with fire on top
    t = Thing(16); t.box(2, 2, 12, 12, 9, stone)
    t.box(4, 4, 8, 8, 1, {"top": hx("#ff8a2a"), "left": hx("#ff6a2a"), "right": hx("#d24a1a")})
    out["furnace"] = t.done()
    # anvil: dark iron on a stump
    t = Thing(14); t.box(5, 5, 6, 6, 4, tri("#8a5a32")); t.box(3, 6, 10, 4, 3, tri("#4c5262")); t.box(2, 6, 12, 4, 0, tri("#4c5262"))
    out["anvil"] = t.done()
    # cart: a small wooden cart with wheels
    t = Thing(14); t.box(3, 4, 10, 8, 5, wood)
    for gx, gy in ((3, 11), (11, 11)):
        ox, oy = t.at(gx, gy); t.iso.c.ellipse(ox - 1, oy - 1, 2, 2, hx("#3a2b20"))
    out["cart"] = t.done()
    # still: a copper pot with a coiled pipe
    t = Thing(20); t.box(4, 4, 8, 8, 9, tri("#d17a3a")); t.box(6, 6, 4, 4, 13, tri("#e8a060")); t.box(11, 5, 2, 2, 11, tri("#b86a2a"))
    out["still"] = t.done()
    # shelf: bottles in colours
    t = Thing(20)
    t.box(3, 5, 10, 6, 16, wood, lambda a, b, w, h, base, r, s:
          (hx(["#e8584a", "#3f6fc4", "#f2b632", "#5bb544"][(a // 3) % 4]) if b % 5 in (1, 2) and 1 <= a < w - 1 else base)
          if s == "l" else base)
    out["shelf"] = t.done()
    # table: a work table with things on it
    t = Thing(14); t.box(2, 3, 12, 10, 6, wood)
    for k, col in enumerate(("#f2d27a", "#e8584a", "#ffffff")):
        t.iso.c.rect(12 + k * 3, t.base - 2 + (k % 2), 2, 2, hx(col))
    out["table"] = t.done()
    return out


def main():
    at = Atlas(1024)
    grounds = {
        "g_town": speckle("#6cc04a", ["#5aab3c", "#84d05e"], .18),
        "g_farm": speckle("#7ac64e", ["#68b23e", "#94d866"], .2),
        "g_beach": speckle("#f2dc9a", ["#e6cc84", "#fbe8b4"], .2),
        "g_mountain": speckle("#8fae5a", ["#7a9a4a", "#a6b874", "#9a8a6a"], .25),
        "path_town": path_stone,
        "path_dirt": speckle("#d6b07a", ["#c49c66", "#e2c08c"], .2),
        "path_sand": speckle("#e8cf8e", ["#dcc07a"], .15),
        "plaza": checker("#e8dcc0", "#d4c4a0", 3),
        "pier": planks("#c08a4a", "#8a5a32", "v", 5),
        "field": field,
        "water0": water(0), "water1": water(1),
    }
    for k, f in grounds.items():
        at.add(k, ground(f, 7))
    for kind, (_, _, floor) in TRADE.items():
        at.add(f"floor_{kind}", ground(floor, 3))
    for i in range(2):
        at.add(f"tree_round{i}", tree_round(i))
    at.add("tree_pine", tree_pine(0))
    at.add("tree_palm", tree_palm(0))
    at.add("bush", bush(1))
    at.add("bush_flower", bush(2, "#f05a7a"))
    at.add("rock", rock())
    at.add("rock_big", rock(True))
    for i, (w, r) in enumerate((("#f4ead6", "#e8584a"), ("#e8f0f8", "#3f6fc4"), ("#fbe0b8", "#5bb544"))):
        at.add(f"house{i}", house(w, r, i))
    at.add("fountain", fountain())
    at.add("lamp", lamp())
    for k in ("barrel", "crate", "umbrella", "sign"):
        at.add(k, small(k))
    for kind in TRADE:
        at.add(f"wall_x_{kind}", wall(kind, "x"))
        at.add(f"wall_xw_{kind}", wall(kind, "x", window=True))
        at.add(f"wall_y_{kind}", wall(kind, "y"))
        at.add(f"wall_yw_{kind}", wall(kind, "y", window=True))
        at.add(f"low_x_{kind}", wall(kind, "x", low=True))
        at.add(f"low_y_{kind}", wall(kind, "y", low=True))
        for v in range(2):
            at.add(f"m_{kind}_{v}", machine(kind, v))
    for k, c in looks().items():
        at.add(f"mc_{k}", c)
    at.save(OUT / "kairo.png", OUT / "kairo.json")
    print("wrote", OUT / "kairo.png")


if __name__ == "__main__":
    main()
