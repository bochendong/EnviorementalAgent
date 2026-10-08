#!/usr/bin/env python
"""Isometric city sprites for SeedVille Workshops (web/codeworld.html).

    python web/tools/isoart.py          # writes web/assets/iso.png + iso.json

Drawn procedurally (original art): 2:1 isometric tiles 64x32, office towers with window grids and
rooftop details, low buildings, houses, trees, cars and trucks. Every frame of a ground tile has its top
vertex at (32, 0); every building has its tile's top vertex at (32, height - 32), i.e. the tile diamond
fills the bottom 32 rows.

Faces: light comes from the left, so left faces are lighter than right faces and roofs are lightest.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pixel import OUT, Atlas, C, hx, mix, shade  # noqa: E402

TW, TH = 64, 32
INK = hx("#1d1f2a")
GLASS = hx("#3a4660")
GLASS_LIT = hx("#f2d27a")
GLASS_HI = hx("#8fa6c8")


# ---------------------------------------------------------------------------- helpers
def tri(base):
    """(roof, left face, right face, trim) from one base colour."""
    b = hx(base)
    return {"top": mix(b, hx("#ffffff"), .25), "left": b, "right": shade(b, .72), "trim": shade(b, .5)}


PALETTES = {
    "grey": tri("#a4a8b4"), "white": tri("#d8dae2"), "slate": tri("#6c7280"), "dark": tri("#4c5262"),
    "brown": tri("#9a7a5a"), "brick": tri("#b0563e"), "orange": tri("#d99a4a"), "sand": tri("#cdb68a"),
    "teal": tri("#5a9a9a"), "green": tri("#6a9a52"),
}


class Iso:
    """A canvas with a face-id buffer, so outlines and edges between faces come out right."""

    def __init__(self, w, h):
        self.c = C(w, h)
        self.face = [[0] * w for _ in range(h)]
        self.n = 0

    def put(self, x, y, col, fid):
        if 0 <= x < self.c.w and 0 <= y < self.c.h:
            self.c.px[x, y] = col
            self.face[y][x] = fid

    def box(self, ox, oy, wx, wy, h, pal, windows=None, rng=None, roof="flat"):
        """A box whose back corner is at screen (ox, oy) on the ground; wx, wy are pixel widths along the
        two grid axes (a full tile is 32 x 32); h is its height in pixels."""
        rng = rng or random.Random(0)
        fl, fr, ft = self.n + 1, self.n + 2, self.n + 3
        self.n += 3
        # left face: edge from (0, wy) to (wx, wy)
        x0 = ox - wy
        for sx in range(x0, x0 + wx):
            a = sx - x0
            g = oy + wy // 2 + a // 2
            for b in range(h):
                col = pal["left"]
                if windows:
                    col = windows(a, b, wx, h, pal["left"], rng, "l")
                self.put(sx, g - b, col, fl)
        # right face: edge from (wx, wy) to (wx, 0)
        x1 = ox + wx - wy
        for sx in range(x1, x1 + wy):
            a = sx - x1
            g = oy + (wx + wy) // 2 - (a + 1) // 2
            for b in range(h):
                col = pal["right"]
                if windows:
                    col = windows(a, b, wy, h, pal["right"], rng, "r")
                self.put(sx, g - b, col, fr)
        # roof
        top = oy - h
        if roof == "flat":
            self.diamond(ox, top, wx, wy, pal["top"], ft)
            if wx > 14 and wy > 14:  # parapet: an inset darker roof deck
                self.diamond(ox, top + 3, wx - 6, wy - 6, shade(pal["top"], .86), ft)
        elif roof == "pyramid":
            self.pyramid(ox, top, wx, wy, pal, ft)
        return top

    def diamond(self, ox, oy, wx, wy, col, fid):
        """Fill the top face with back corner (ox, oy)."""
        for gx in range(wx):
            for gy in range(wy):
                sx, sy = ox + gx - gy, oy + (gx + gy) // 2
                self.put(sx, sy, col, fid)
                self.put(sx - 1, sy, col, fid)

    def pyramid(self, ox, oy, wx, wy, pal, fid):
        peak = max(wx, wy) // 2
        cx, cy = ox + (wx - wy) // 2, oy + (wx + wy) // 4
        for gx in range(wx):
            for gy in range(wy):
                sx, sy = ox + gx - gy, oy + (gx + gy) // 2
                # height of the roof over this point
                d = max(abs(gx - wx / 2) / (wx / 2), abs(gy - wy / 2) / (wy / 2))
                lift = int(peak * (1 - d))
                left = (gy - wy / 2) * wx > (gx - wx / 2) * wy  # facing +y (screen left)
                col = pal["top"] if left else pal["right"]
                if not left and (gx - wx / 2) * wy < (gy - wy / 2) * wx:
                    col = pal["top"]
                for k in range(lift + 1):
                    self.put(sx, sy - k, col if k == lift else shade(col, .9), fid + (0 if left else 100))
                    self.put(sx - 1, sy - k, col if k == lift else shade(col, .9), fid + (0 if left else 100))
        return cx, cy - peak

    def finish(self, outline=INK):
        """Outer outline plus a darker seam where two faces meet."""
        im, px = self.c.im, self.c.px
        src = im.copy().load()
        w, h = self.c.w, self.c.h
        for y in range(h):
            for x in range(w):
                if src[x, y][3] == 0:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and src[nx, ny][3] > 200:
                            px[x, y] = outline
                            break
                elif self.face[y][x]:
                    f = self.face[y][x]
                    for dx, dy in ((1, 0), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and self.face[ny][nx] and self.face[ny][nx] != f:
                            px[x, y] = shade(src[x, y], .7)
                            break
        return self.c


def office_windows(lit=.12, floor=5, col_w=4, band=True):
    def f(a, b, width, h, base, rng, side):
        if b < 4 and band:  # lobby: a glass band at street level
            return GLASS_HI if side == "l" else shade(GLASS_HI, .8)
        if a < 2 or a >= width - 2 or b >= h - 3:
            return base
        if (b - 4) % floor in (1, 2, 3) and a % col_w in (1, 2):
            if rng.random() < lit / 6:
                return GLASS_LIT
            return GLASS if side == "r" else mix(GLASS, GLASS_HI, .35)
        return base
    return f


def glass_windows(a, b, width, h, base, rng, side):
    if a < 1 or a >= width - 1 or b >= h - 2:
        return base
    if b % 4 == 0:
        return base
    g = mix(GLASS, GLASS_HI, .55 if side == "l" else .2)
    return GLASS_LIT if rng.random() < .01 else g


def house_windows(a, b, width, h, base, rng, side):
    if 3 <= b <= 6 and a % 6 in (2, 3) and 1 < a < width - 2:
        return GLASS
    return base


# ---------------------------------------------------------------------------- frames
def tile(kind, seed=0):
    rng = random.Random(seed)
    c = C(TW, TH)
    grass = [hx("#5e9a3e"), hx("#6aa846"), hx("#558f38")]
    asphalt, line, curb = hx("#5d6068"), hx("#e8e4d4"), hx("#a9aab2")
    paving = [hx("#cfc6b2"), hx("#c2b9a4")]
    for y in range(TH):
        hw = (y + 1) * 2 if y < TH // 2 else (TH - y) * 2
        for x in range(TW // 2 - hw, TW // 2 + hw):
            # grid coordinates inside the tile (0..1)
            u = (x - TW / 2) / TW + y / TH  # along +x
            v = -(x - TW / 2) / TW + y / TH  # along +y
            if kind == "grass":
                col = rng.choice(grass) if rng.random() < .25 else grass[0]
            elif kind == "park":
                col = rng.choice(grass[:2])
            elif kind in ("road_x", "road_y", "cross"):
                col = asphalt
                edge = v if kind == "road_x" else u
                if kind != "cross" and (edge < .12 or edge > .88):
                    col = curb
                if kind == "road_x" and abs(v - .5) < .03 and int(u * 8) % 2 == 0:
                    col = line
                if kind == "road_y" and abs(u - .5) < .03 and int(v * 8) % 2 == 0:
                    col = line
                if kind == "cross" and (u < .14 or u > .86) and .15 < v < .85 and int(v * 10) % 2 == 0:
                    col = line
                if kind == "cross" and (v < .14 or v > .86) and .15 < u < .85 and int(u * 10) % 2 == 0:
                    col = line
            elif kind == "plaza":
                col = paving[(int(u * 4) + int(v * 4)) % 2]
            elif kind == "lot":
                col = hx("#7a7d86")
                if abs(u - .5) < .03 and int(v * 6) % 2 == 0:
                    col = line
            c.p(x, y, col)
    return c


def tower(h, pal, w=24, extra=None, seed=0, windows=None, roof="flat"):
    """A one-tile building: footprint inset so the street shows around it."""
    rng = random.Random(seed)
    top_room = 14
    H = h + TH + top_room
    iso = Iso(TW, H)
    m = (32 - w) // 2
    ox, oy = 32, H - TH + m
    top = iso.box(ox, oy, w, w, h, pal, windows or office_windows(), rng, roof=roof)
    cx, cy = ox + 0, top + w // 2
    for e in extra or []:
        if e == "antenna":
            for k in range(10):
                iso.put(cx, cy - k, INK, 99)
            iso.put(cx, cy - 10, hx("#e04a3a"), 99)
        if e == "ac":
            iso.box(cx - 6, cy - 3, 5, 4, 3, PALETTES["white"], None, rng)
            iso.box(cx + 4, cy - 1, 4, 4, 3, PALETTES["grey"], None, rng)
        if e == "dome":
            iso.box(cx - 3, cy - 2, 7, 7, 4, PALETTES["teal"], None, rng)
    return iso.finish()


def duo(h1, h2, p1, p2, seed=0, extra=()):
    """Two blocks on one tile: a taller block behind and a lower annex in front (like a campus)."""
    rng = random.Random(seed)
    H = max(h1, h2) + TH + 14
    iso = Iso(TW, H)
    base = H - TH
    t1 = iso.box(32 - 4, base + 2, 18, 22, h1, p1, office_windows(), rng)
    iso.box(32 + 8, base + 12, 14, 16, h2, p2, office_windows(), rng)
    if "antenna" in extra:
        cx, cy = 32 - 6, t1 + 10
        for k in range(9):
            iso.put(cx, cy - k, INK, 99)
        iso.put(cx, cy - 9, hx("#e04a3a"), 99)
    return iso.finish()


def house(pal, roof_col, seed=0):
    rng = random.Random(seed)
    H = TH + 30
    iso = Iso(TW, H)
    base = H - TH
    iso.box(32, base + 8, 16, 16, 9, pal, house_windows, rng)
    iso.box(32, base + 8 - 9, 16, 16, 0, tri(roof_col), None, rng, roof="pyramid")
    return iso.finish()


def tree(seed=0, kind="round"):
    rng = random.Random(seed)
    c = C(24, 36)
    trunk = hx("#6b4429")
    c.rect(11, 24, 2, 8, trunk)
    leaves = [hx("#2e5e2a"), hx("#3f7a32"), hx("#56993e"), hx("#7cba52")]
    if kind == "round":
        c.blob(12, 16, 9, leaves, light=(-1, -1.2), rng=rng)
    else:  # conifer
        for k in range(4):
            r = 3 + k * 2
            for j in range(5):
                y = 6 + k * 5 + j
                for i in range(-r + (4 - j) // 2, r - (4 - j) // 2 + 1):
                    c.p(12 + i, y, leaves[1] if i < 0 else leaves[0] if i > 2 else leaves[2])
    c.outline(INK)
    return c


def vehicle(axis, body, cab=None, length=14, width=8, height=6, seed=0):
    """A car or truck driving along grid axis 'x' (screen down-right) or 'y' (screen down-left)."""
    rng = random.Random(seed)
    iso = Iso(32, 28)
    wx, wy = (length, width) if axis == "x" else (width, length)
    ox, oy = 16 + (wy - wx) // 2, 8
    if cab:
        if axis == "x":
            iso.box(ox, oy, wx - 5, wy, height + 2, tri(body), None, rng)
            iso.box(ox + wx - 5, oy + (wx - 5) // 2, 5, wy, height, tri(cab), glass_windows, rng)
        else:
            iso.box(ox, oy, wx, wy - 5, height + 2, tri(body), None, rng)
            iso.box(ox - (wy - 5), oy + (wy - 5) // 2, wx, 5, height, tri(cab), glass_windows, rng)
    else:
        iso.box(ox, oy, wx, wy, height - 2, tri(body), None, rng)
        iso.box(ox + (2 if axis == "x" else 1) - (1 if axis == "y" else 0), oy - 1, wx - 4 if axis == "x" else wx - 2,
                wy - 2 if axis == "x" else wy - 4, 3, {"top": tri(body)["top"], "left": GLASS_HI, "right": GLASS}, None, rng)
    return iso.finish()


def fountain():
    iso = Iso(TW, TH + 20)
    base = 20
    iso.box(32, base + 6, 20, 20, 3, tri("#c9c2b0"), None)
    iso.diamond(32, base + 6 - 3 + 2, 16, 16, hx("#4f8fd0"), 50)
    iso.box(32, base + 12, 4, 4, 9, tri("#d8d2c2"), None)
    c = iso.finish()
    for k in range(4):
        c.p(32 + (k - 1.5) * 2, 6 + k % 2, hx("#a3d2f0"))
    return c


# kind of workshop -> how its building looks (taller = more important; each kind its own look)
WORKSHOP = {
    "bakery": dict(f="tower", h=46, pal="orange", extra=["ac"]),
    "smithy": dict(f="tower", h=56, pal="dark", extra=["antenna"]),
    "florist": dict(f="tower", h=40, pal="brick", extra=["ac"]),
    "mine": dict(f="duo", h1=52, h2=28, p1="brown", p2="sand", extra=["antenna"]),
    "clinic": dict(f="tower", h=62, pal="white", extra=["antenna", "ac"]),
    "inn": dict(f="duo", h1=52, h2=26, p1="brick", p2="orange", extra=[]),
    "shop": dict(f="tower", h=34, pal="teal", extra=["dome"], windows="glass"),
    "farm": dict(f="tower", h=50, pal="green", extra=["ac"]),
}


def workshop(kind, seed=0):
    s = WORKSHOP[kind]
    if s["f"] == "duo":
        return duo(s["h1"], s["h2"], PALETTES[s["p1"]], PALETTES[s["p2"]], seed, s["extra"])
    return tower(s["h"], PALETTES[s["pal"]], 24, s["extra"], seed,
                 glass_windows if s.get("windows") == "glass" else None)


def main():
    at = Atlas(1024)
    for k in ("grass", "park", "road_x", "road_y", "cross", "plaza", "lot"):
        at.add(f"t_{k}", tile(k, 1))
    for k in WORKSHOP:
        at.add(f"w_{k}", workshop(k, 3))
    fill = [("grey", 30), ("white", 44), ("slate", 24), ("sand", 36), ("grey", 60), ("brown", 22)]
    for i, (p, h) in enumerate(fill):
        at.add(f"f_tower{i}", tower(h, PALETTES[p], 22 if h < 40 else 24, ["ac"] if i % 2 else [], seed=10 + i))
    for i, (p, r) in enumerate([("white", "#b0563e"), ("sand", "#5a6a8a"), ("white", "#6a9a52")]):
        at.add(f"f_house{i}", house(PALETTES[p], r, seed=20 + i))
    at.add("f_low0", tower(10, PALETTES["grey"], 28, ["ac"], seed=30))
    at.add("f_low1", tower(8, PALETTES["white"], 28, [], seed=31))
    for i in range(2):
        at.add(f"tree{i}", tree(40 + i, "round"))
    at.add("tree2", tree(42, "pine"))
    at.add("fountain", fountain())
    for axis in "xy":
        at.add(f"car_red_{axis}", vehicle(axis, "#c8463a", seed=1))
        at.add(f"car_blue_{axis}", vehicle(axis, "#3f6fc4", seed=2))
        at.add(f"van_{axis}", vehicle(axis, "#e8e8ee", "#d8dae2", 16, 8, 7, seed=3))
        at.add(f"truck_{axis}", vehicle(axis, "#e07a3a", "#c8463a", 20, 9, 8, seed=4))
    at.save(OUT / "iso.png", OUT / "iso.json")
    print("wrote", OUT / "iso.png")


if __name__ == "__main__":
    main()
