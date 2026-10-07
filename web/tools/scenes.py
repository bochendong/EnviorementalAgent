"""SeedVille scenes: extra tiles, workplace buildings, furniture, and the scene maps.

The town is split into Stardew-style scenes connected by exits and doors:

    mountain (forest, pond, mine entrance)
          |
    farm -- town square (plaza, shop, bakery, smithy, flower shop, clinic, library, inn) -- residential lane
          |
    beach (pier)

Every building with a door leads to an interior scene (one template per kind; houses share
one template). Maps are written as Tiled JSON (assets/maps/<key>.json) with these object types:

    location  an engine location hosted here (rect, anchor, item/people spots)
    exit      walk here to travel to another map (props: to, spawn)
    building  exterior sprite; with props interior + loc + door it leads inside
    furniture interior props (sprite from the objects atlas, optional solid)
    tree / lamppost / prop / fence_h / fence_v / plot / fountain / plaza_decor   scenery
"""

from __future__ import annotations

import json
import math
import random

from pixel import C, OUT, STONE, T, WATER, WOOD, hue_ramp, hx, ramp, shade

SAND = ramp("#9c7d52", "#c4a272", "#e0c18c", "#eed4a4", "#f8e8c4")

# ---------------------------------------------------------------- tileset layout (16 columns)
TILE_SAND = 8            # row 0, columns 8..15
TILE_BEACH_DECOR = 88    # row 5, columns 8..15
TILE_OCEAN_A = 96        # row 6: water with sand banks (+mask)
TILE_OCEAN_B = 112       # row 7
TILE_FLOOR = 128         # row 8: wood light 0-3, wood dark 4-7, stone 8-11, checker 12-15
TILE_WALL = 144          # row 9: 4 wallpapers x (top, mid, base) = 144..155, 156 = dark void
WALLPAPERS = ["cream", "green", "rose", "blue"]
N_, E_, S_, W_ = 1, 2, 4, 8


def banked_tile(fill, mask, over, rng, rim):
    """Terrain with an organic overhang of ``over`` (a colour ramp) where neighbours differ."""
    c = fill(rng)
    for side, bit in (("n", N_), ("e", E_), ("s", S_), ("w", W_)):
        if mask & bit:
            continue
        for i in range(T):
            d = 2 + rng.choice((0, 1, 1, 2))
            for k in range(d):
                x, y = {"n": (i, k), "s": (i, T - 1 - k), "w": (k, i), "e": (T - 1 - k, i)}[side]
                c.p(x, y, over[2] if k < d - 1 else over[3])
            x, y = {"n": (i, d), "s": (i, T - 1 - d), "w": (d, i), "e": (T - 1 - d, i)}[side]
            c.p(x, y, rim)
    for (bx, by, cx, cy) in ((N_, W_, 0, 0), (N_, E_, T - 3, 0), (S_, W_, 0, T - 3), (S_, E_, T - 3, T - 3)):
        if not (mask & bx) and not (mask & by):
            c.rect(cx, cy, 3, 3, over[2])
    return c


def sand_tile(v, rng):
    c = C(T, T)
    c.rect(0, 0, T, T, SAND[2])
    for _ in range(18):
        c.p(rng.randrange(T), rng.randrange(T), SAND[1] if rng.random() < .45 else SAND[3])
    if v >= 4:  # ripples
        for k in range(2):
            y = rng.randrange(3, 13)
            x = rng.randrange(1, 9)
            c.hline(x, y, 5, SAND[1]); c.hline(x + 1, y - 1, 3, SAND[3])
    if v >= 6:  # shell / pebble
        x, y = rng.randrange(3, 12), rng.randrange(3, 12)
        c.p(x, y, hx("#f6e6e0")); c.p(x + 1, y, hx("#e8b8a8")); c.p(x, y + 1, hx("#d89a8a"))
    return c


def ocean_fill(frame):
    def f(rng):
        c = C(T, T)
        c.rect(0, 0, T, T, WATER[2])
        for _ in range(12):
            c.p(rng.randrange(T), rng.randrange(T), WATER[1])
        r2 = random.Random(frame * 77 + rng.randrange(9))
        for _ in range(3):
            x, y = r2.randrange(0, 12), r2.randrange(1, 15)
            c.hline(x, y, 4, WATER[3]); c.p(x + 1, y - 1, WATER[4])
        return c
    return f


def floor_tile(kind, v, rng):
    c = C(T, T)
    if kind in ("wood", "dark"):
        R = hue_ramp("#b07a48") if kind == "wood" else hue_ramp("#6e4428")
        for row in range(4):
            y = row * 4
            c.rect(0, y, T, 4, R[2] if (row + v) % 2 else R[3])
            c.hline(0, y + 3, T, R[1])
            c.hline(0, y, T, shade(R[3], 1.04) if (row + v) % 2 else R[3])
            if (row + v) % 3 == 0:  # long planks: only some rows have a joint in this tile
                seam = (row * 7 + v * 5) % 16
                c.vline(seam, y, 3, R[1])
    elif kind == "stone":
        c.rect(0, 0, T, T, STONE[2])
        for (x, y, w, h) in ((0, 0, 8, 8), (8, 0, 8, 8), (0, 8, 8, 8), (8, 8, 8, 8)):
            c.rect(x + 1, y + 1, w - 2, h - 2, STONE[3] if (x + y + v * 8) % 16 else STONE[2])
            c.hline(x, y, w, STONE[1]); c.vline(x, y, h, STONE[1])
    else:  # checker (clinic)
        for y in range(T):
            for x in range(T):
                c.p(x, y, hx("#e8ecf0") if ((x // 8) + (y // 8) + v) % 2 else hx("#b8c8d4"))
    return c


WALLPAPER = {"cream": ("#e8d6b0", "#d8c098"), "green": ("#9cc48a", "#86b076"), "rose": ("#e6a8a0", "#d4908a"),
             "blue": ("#9ab8d8", "#86a4c6")}


def wall_tile(color, part):
    a, b = (hx(x) for x in WALLPAPER[color])
    c = C(T, T)
    for x in range(T):
        c.vline(x, 0, T, a if (x // 4) % 2 else b)
    if part == "top":
        c.rect(0, 0, T, 4, WOOD[1]); c.hline(0, 4, T, WOOD[3]); c.hline(0, 5, T, shade(b, .85))
    if part == "base":
        c.rect(0, 10, T, 6, WOOD[2]); c.hline(0, 10, T, WOOD[4]); c.hline(0, 15, T, WOOD[0])
        c.hline(0, 9, T, shade(b, .8))
    return c


def extra_tiles(sheet, season):
    """Paint rows/columns added for scenes onto a terrain sheet (already 16x10 tiles)."""
    for v in range(8):
        sheet.paste(sand_tile(v, random.Random(50 + v)), (TILE_SAND + v) * T % (16 * T), 0)
    beach = []
    for k in range(8):
        c = sand_tile(k % 4, random.Random(60 + k))
        rng = random.Random(70 + k)
        if k in (0, 1):  # shells
            for _ in range(2):
                x, y = rng.randrange(3, 12), rng.randrange(3, 12)
                c.ellipse(x, y, 1.6, 1.2, hx("#f2d8d0")); c.p(x, y, hx("#c98a7a"))
        elif k in (2, 3):  # seaweed
            for _ in range(3):
                x, y = rng.randrange(2, 13), rng.randrange(4, 13)
                c.hline(x, y, 3, hx("#3f7a4a")); c.p(x + 1, y - 1, hx("#5a9a5a"))
        elif k in (4, 5):  # driftwood
            c.hline(3, 8, 9, WOOD[2]); c.hline(4, 9, 7, WOOD[1]); c.p(11, 7, WOOD[3])
        elif k == 6:  # starfish
            for dx, dy in ((0, 0), (0, -2), (-2, -1), (2, -1), (-1, 2), (1, 2), (0, -1), (-1, 0), (1, 0), (0, 1)):
                c.p(8 + dx, 8 + dy, hx("#e8743a"))
        beach.append(c)
    for k, c in enumerate(beach):
        sheet.paste(c, (8 + k) * T, 5 * T)
    for m in range(16):
        for f, row in ((0, 6), (1, 7)):
            sheet.paste(banked_tile(ocean_fill(f), m, SAND, random.Random(800 + m), WATER[4]), m * T, row * T)
    for k, kind in enumerate(("wood", "dark", "stone", "checker")):
        for v in range(4):
            sheet.paste(floor_tile(kind, v, random.Random(k * 10 + v)), (k * 4 + v) * T, 8 * T)
    for i, col in enumerate(WALLPAPERS):
        for j, part in enumerate(("top", "mid", "base")):
            sheet.paste(wall_tile(col, part), (i * 3 + j) * T, 9 * T)
    void = C(T, T)
    void.rect(0, 0, T, T, hx("#1a120e"))
    sheet.paste(void, 12 * T, 9 * T)


# ---------------------------------------------------------------- buildings
def sign_board(c, x, y, icon):
    c.rect(x, y, 22, 12, WOOD[1]); c.rect(x + 1, y + 1, 20, 10, hx("#f1d9a7"))
    cx, cy = x + 11, y + 6
    if icon == "bread":
        c.ellipse(cx, cy, 6, 3, hx("#c9894a")); c.hline(cx - 4, cy - 1, 9, hx("#e8b070"))
        for k in (-3, 0, 3):
            c.p(cx + k, cy - 2, hx("#f6d8a0"))
    elif icon == "anvil":
        c.rect(cx - 6, cy - 2, 12, 3, hx("#4a4a55")); c.rect(cx - 2, cy + 1, 4, 3, hx("#3a3a44")); c.rect(cx - 5, cy + 3, 10, 1, hx("#3a3a44"))
    elif icon == "flower":
        c.vline(cx, cy - 1, 5, hx("#3f8a3a"))
        for dx, dy in ((0, -3), (-2, -2), (2, -2), (-1, -1), (1, -1)):
            c.p(cx + dx, cy + dy, hx("#e85a8a"))
        c.p(cx, cy - 2, hx("#f6d24a"))
    elif icon == "cross":
        c.rect(cx - 1, cy - 4, 3, 9, hx("#d0473b")); c.rect(cx - 4, cy - 1, 9, 3, hx("#d0473b"))
    elif icon == "book":
        c.rect(cx - 6, cy - 3, 6, 7, hx("#3f6fd6")); c.rect(cx, cy - 3, 6, 7, hx("#3f6fd6"))
        c.vline(cx, cy - 3, 7, hx("#1f3f8a")); c.hline(cx - 5, cy - 1, 4, hx("#cfe0ff")); c.hline(cx + 1, cy - 1, 4, hx("#cfe0ff"))
    elif icon == "mug":
        c.rect(cx - 4, cy - 3, 7, 7, hx("#e0a836")); c.rect(cx - 4, cy - 4, 7, 2, hx("#ffffff"))
        c.rect(cx + 3, cy - 1, 2, 4, hx("#c08a26"))


def workplace(kind, season, house_fn):
    """Exterior for a workplace, built on the house template with its own colours and sign."""
    spec = {
        "bakery": ("#c8622e", "plaster", 80, 72, "bread", True),
        "smithy": ("#4a4a58", "#6a6a78", 80, 72, "anvil", True),
        "florist": ("#d46a9a", "plaster", 64, 64, "flower", False),
        "clinic": ("#2f8a8a", "#e8e0d0", 80, 72, "cross", False),
        "library": ("#2f3f7a", "#9a8a78", 96, 80, "book", False),
        "inn": ("#9a3a2a", "#8a5a36", 112, 88, "mug", True),
    }[kind]
    roof, wall, w, h, icon, chim = spec
    c = house_fn(roof, wall, season, hash(kind) & 0xFF, w, h, chimney=chim)
    sign_board(c, w // 2 - 11, 8 + int(h * .5) - 4, icon)
    rng = random.Random(len(kind))
    if kind == "florist":
        for x in range(4, w - 4, 6):
            c.ellipse(x + 2, h + 4, 2.5, 2, hx("#b8653a")); c.p(x + 2, h + 1, hx(rng.choice(["#e85a8a", "#f6d24a", "#ffffff", "#c98bf0"])))
    if kind == "smithy":
        c.rect(w - 22, 0, 10, 10, STONE[1])  # forge chimney
    c.outline()
    return c


def mine_entrance(season):
    c = C(96, 72)
    rng = random.Random(9)
    R = ramp("#3d3b4a", "#5d5b6c", "#7e7a8a", "#a19caa", "#c4c0ca")
    for (cx, cy, r) in ((48, 40, 34), (20, 50, 20), (76, 50, 20), (34, 26, 18), (62, 24, 18)):
        c.blob(cx, cy, r, R, light=(-1, -1.3), rng=rng)
    if season == "winter":
        for x in range(10, 86):
            for y in range(0, 72):
                if c.get(x, y)[3]:
                    c.p(x, y, hx("#ffffff")); c.p(x, y + 1, hx("#e2eaf3"))
                    break
    # timber frame + dark opening
    c.rect(36, 40, 24, 32, hx("#140e0c"))
    c.rect(32, 36, 4, 36, WOOD[2]); c.rect(60, 36, 4, 36, WOOD[2]); c.rect(30, 33, 36, 5, WOOD[3])
    c.hline(30, 33, 36, WOOD[4])
    for y in (44, 52, 60, 68):  # rails into the dark
        c.hline(40, y, 16, hx("#5a5a66"))
    c.vline(43, 42, 30, WOOD[1]); c.vline(52, 42, 30, WOOD[1])
    c.outline()
    return c


def pier_post():
    c = C(16, 16)
    c.rect(6, 2, 4, 14, WOOD[2]); c.rect(6, 2, 1, 14, WOOD[3]); c.ellipse(8, 2, 2, 1, WOOD[3])
    c.outline()
    return c


def boat():
    c = C(48, 24)
    for y in range(8, 18):
        inset = (y - 8) // 2
        c.hline(4 + inset, y, 40 - 2 * inset, WOOD[2] if y < 15 else WOOD[1])
    c.hline(4, 8, 40, WOOD[4]); c.hline(4, 11, 40, hx("#c0392b"))
    c.rect(22, 0, 2, 9, WOOD[1])
    c.outline()
    return c


# ---------------------------------------------------------------- furniture
def furniture():
    out = {}
    W = WOOD

    def mk(w, h):
        return C(w, h)

    c = mk(16, 32)  # bed (top-down, head at top)
    c.rect(1, 1, 14, 30, W[2]); c.rect(2, 3, 12, 6, hx("#f6f0e0")); c.rect(2, 10, 12, 19, hx("#5a7fd0"))
    c.hline(2, 10, 12, hx("#8aa8e8")); c.rect(2, 26, 12, 3, hx("#3f5fa8")); c.rect(1, 0, 14, 3, W[3])
    out["f_bed"] = c
    c = mk(32, 24)  # table
    c.rect(1, 3, 30, 13, W[3]); c.hline(1, 3, 30, W[4]); c.rect(1, 16, 30, 3, W[1])
    c.rect(3, 19, 3, 5, W[1]); c.rect(26, 19, 3, 5, W[1])
    out["f_table"] = c
    c = mk(16, 16)  # chair
    c.rect(3, 1, 10, 6, W[2]); c.rect(3, 7, 10, 4, W[3]); c.rect(3, 11, 2, 5, W[1]); c.rect(11, 11, 2, 5, W[1])
    out["f_chair"] = c
    c = mk(48, 32)  # rug
    c.rect(0, 0, 48, 32, hx("#9a3a3a")); c.rect(3, 3, 42, 26, hx("#c25a4a"))
    for x in range(6, 42, 6):
        c.rect(x, 12, 3, 8, hx("#e8b86a"))
    c.rect(3, 3, 42, 2, hx("#e8b86a")); c.rect(3, 27, 42, 2, hx("#e8b86a"))
    out["f_rug"] = c
    c = mk(32, 32)  # bookshelf
    c.rect(0, 0, 32, 32, W[1]); c.rect(2, 2, 28, 28, W[0])
    rng = random.Random(4)
    for shelf in range(3):
        y = 3 + shelf * 9
        x = 3
        while x < 28:
            w = rng.choice((2, 3))
            col = hx(rng.choice(["#c0392b", "#3f6fd6", "#3f9e48", "#e8c23a", "#8b52c8", "#e8842c"]))
            c.rect(x, y + rng.choice((0, 1, 2)), w, 7, col)
            x += w + 1
        c.hline(2, y + 7, 28, W[2])
    out["f_bookshelf"] = c
    c = mk(48, 24)  # counter
    c.rect(0, 0, 48, 8, W[3]); c.hline(0, 0, 48, W[4]); c.rect(0, 8, 48, 14, W[2])
    for x in range(4, 46, 8):
        c.rect(x, 11, 6, 8, W[1])
    out["f_counter"] = c
    c = mk(32, 32)  # shelf with goods (shop)
    c.rect(0, 0, 32, 32, W[1]); c.rect(2, 2, 28, 28, W[2])
    for shelf in range(3):
        y = 3 + shelf * 9
        c.hline(2, y + 7, 28, W[3])
        for k in range(5):
            col = hx(["#c0392b", "#e8c23a", "#3f9e48", "#f6f0e0", "#e8842c"][(k + shelf) % 5])
            c.rect(4 + k * 5, y + 2, 3, 5, col); c.p(4 + k * 5, y + 2, shade(col, 1.2))
    out["f_shelf"] = c
    c = mk(32, 32)  # bread oven
    c.rect(0, 4, 32, 28, hx("#a8553a")); c.ellipse(16, 4, 16, 6, hx("#a8553a"))
    for y in range(6, 30, 4):
        c.hline(0, y, 32, hx("#8a3f2a"))
    c.ellipse(16, 20, 9, 7, hx("#1a0e0a")); c.ellipse(16, 23, 6, 3, hx("#f2a33a")); c.ellipse(16, 24, 3, 1.5, hx("#ffe08a"))
    out["f_oven"] = c
    c = mk(16, 16)  # anvil
    c.rect(1, 4, 14, 4, hx("#4a4a55")); c.rect(0, 4, 3, 2, hx("#4a4a55")); c.rect(5, 8, 6, 4, hx("#3a3a44"))
    c.rect(3, 12, 10, 3, hx("#3a3a44")); c.hline(2, 4, 12, hx("#8a8a98"))
    out["f_anvil"] = c
    c = mk(32, 32)  # forge
    c.rect(2, 8, 28, 24, STONE[1]); c.rect(4, 10, 24, 20, STONE[2])
    c.rect(8, 14, 16, 10, hx("#1a0e0a")); c.rect(9, 18, 14, 6, hx("#e8642a")); c.rect(11, 20, 10, 3, hx("#ffd05a"))
    c.rect(10, 0, 12, 8, STONE[1])
    out["f_forge"] = c
    for k, col in enumerate(("#e85a8a", "#f6d24a", "#c98bf0", "#ffffff")):  # flower pots
        c = mk(16, 16)
        c.rect(4, 9, 8, 6, hx("#b8653a")); c.hline(3, 9, 10, hx("#d47a4a"))
        c.vline(8, 4, 5, hx("#3f8a3a")); c.p(6, 6, hx("#4f9e48")); c.p(10, 5, hx("#4f9e48"))
        c.ellipse(8, 4, 2.5, 2, hx(col)); c.p(8, 4, hx("#f6e27a"))
        out[f"f_pot{k}"] = c
    c = mk(16, 32)  # clinic bed
    c.rect(1, 1, 14, 30, hx("#c8ccd4")); c.rect(2, 3, 12, 6, hx("#ffffff")); c.rect(2, 10, 12, 19, hx("#e8eef4"))
    c.hline(2, 10, 12, hx("#ffffff")); c.rect(6, 15, 4, 1, hx("#d0473b")); c.rect(7, 13, 2, 5, hx("#d0473b"))
    out["f_clinicbed"] = c
    c = mk(32, 32)  # fireplace (stands against the wall)
    c.rect(0, 0, 32, 32, STONE[2]); c.hline(0, 0, 32, STONE[4])
    for y in range(4, 32, 5):
        c.hline(0, y, 32, STONE[1])
    c.rect(7, 12, 18, 20, hx("#1a0e0a")); c.rect(10, 24, 12, 4, hx("#e8642a")); c.rect(13, 22, 6, 3, hx("#ffd05a"))
    c.rect(4, 8, 24, 3, W[3])
    out["f_fireplace"] = c
    c = mk(64, 24)  # bar
    c.rect(0, 0, 64, 8, W[3]); c.hline(0, 0, 64, W[4]); c.rect(0, 8, 64, 14, W[1])
    for x in range(4, 62, 10):
        c.rect(x, 11, 7, 8, W[2])
    for x in (8, 26, 44):
        c.rect(x, -1, 4, 1, hx("#e0a836"))
    out["f_bar"] = c
    c = mk(16, 24)  # potted plant
    c.rect(4, 16, 8, 7, hx("#b8653a")); c.hline(3, 16, 10, hx("#d47a4a"))
    c.blob(8, 9, 6, hue_ramp("#3f8f34"), rng=random.Random(2))
    out["f_plant"] = c
    c = mk(16, 16)  # wall window
    c.rect(1, 1, 14, 14, W[1]); c.rect(2, 2, 12, 12, hx("#9fd3e6")); c.rect(2, 2, 12, 3, hx("#cfeef8"))
    c.vline(8, 2, 12, W[2]); c.hline(2, 8, 12, W[2]); c.p(4, 4, hx("#ffffff"))
    out["f_window"] = c
    c = mk(16, 16)  # painting
    c.rect(1, 2, 14, 12, hx("#c8a23a")); c.rect(2, 3, 12, 10, hx("#7fb0d8"))
    c.rect(2, 9, 12, 4, hx("#4f9e48")); c.ellipse(10, 6, 2, 2, hx("#f6d24a"))
    out["f_painting"] = c
    c = mk(16, 16)  # cabinet
    c.rect(1, 1, 14, 14, hx("#e8eef4")); c.vline(8, 1, 14, hx("#b8c8d4")); c.p(6, 8, hx("#5a6a7a")); c.p(10, 8, hx("#5a6a7a"))
    out["f_cabinet"] = c
    c = mk(16, 16)  # tool rack
    c.rect(0, 2, 16, 3, W[2])
    for x, col in ((2, "#8a8a98"), (7, "#6a6a78"), (12, "#8a8a98")):
        c.vline(x, 5, 9, W[1]); c.rect(x - 1, 12, 3, 3, hx(col))
    out["f_toolrack"] = c
    c = mk(32, 16)  # doormat (exit marker inside)
    c.rect(4, 4, 24, 10, hx("#8a5a32")); c.rect(6, 6, 20, 6, hx("#a8743f"))
    out["f_doormat"] = c
    for k, v in out.items():
        if k not in ("f_rug", "f_doormat"):
            v.outline()
    return out


# ---------------------------------------------------------------- maps
class MapBuilder:
    def __init__(self, key, w, h, base="grass", season_safe=True):
        self.key, self.w, self.h = key, w, h
        self.kind = [[base] * w for _ in range(h)]
        self.deco = [[0] * w for _ in range(h)]
        self.objs = []
        self.taken = set()
        self.oid = 0

    def fill(self, x0, y0, w, h, k):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if 0 <= x < self.w and 0 <= y < self.h:
                    self.kind[y][x] = k

    def obj(self, name, type_, x, y, w=0, h=0, **props):
        self.oid += 1
        o = {"id": self.oid, "name": name, "type": type_, "x": x * T, "y": y * T, "width": w * T, "height": h * T,
             "rotation": 0, "visible": True}
        if props:
            o["properties"] = [{"name": k, "type": "string", "value": str(v)} for k, v in props.items()]
        self.objs.append(o)

    def block(self, x0, y0, w=1, h=1):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                self.taken.add((x, y))

    def location(self, name, rect, anchor, items, people):
        x, y, w, h = rect
        self.obj(name, "location", x, y, w, h, anchor=f"{anchor[0]},{anchor[1]}",
                 items=";".join(f"{a},{b}" for a, b in items), people=";".join(f"{a},{b}" for a, b in people))
        for p in list(items) + list(people) + [anchor]:
            self.taken.add(tuple(p))

    def building(self, name, sprite, x, bottom, w, h=3, interior=None, loc=None):
        """x: left tile, bottom: bottom row of the sprite; the door is the tile below the middle."""
        door = (x + w // 2, bottom + 1)
        props = {"sprite": sprite}
        if interior:
            props.update(interior=interior, loc=loc or name, door=f"{door[0]},{door[1]}")
        self.obj(name, "building", x, bottom, w, h, **props)
        self.block(x - 1, bottom - 5, w + 2, 6)
        self.taken.discard(door)
        return door

    def exit(self, to, x, y, spawn):
        self.obj(f"to_{to}", "exit", x, y, 1, 1, to=to, spawn=f"{spawn[0]},{spawn[1]}")
        self.taken.add((x, y))

    def trees(self, seed, n, area, choices, avoid_kinds=("path", "stone", "water", "sand", "ocean")):
        rng = random.Random(seed)
        planted = []
        x0, y0, x1, y1 = area
        for _ in range(n * 8):
            if len(planted) >= n:
                break
            x, y = rng.randrange(x0, x1), rng.randrange(max(1, y0), y1)
            if self.kind[y][x] in avoid_kinds or (x, y) in self.taken:
                continue
            if any(abs(x - a) < 2 and abs(y - b) < 2 for a, b in planted):
                continue
            if any((x + dx, y + dy) in self.taken for dx in (-1, 0, 1) for dy in (0, 1)):
                continue
            planted.append((x, y))
            self.obj("tree", "tree", x, y + 1, sprite=rng.choice(choices))

    def sprinkle(self, seed, n):
        rng = random.Random(seed)
        for _ in range(n):
            x, y = rng.randrange(self.w), rng.randrange(self.h)
            if (x, y) in self.taken:
                continue
            if self.kind[y][x] == "grass":
                self.deco[y][x] = 80 + rng.randrange(8) + 1
            elif self.kind[y][x] == "sand":
                self.deco[y][x] = TILE_BEACH_DECOR + rng.randrange(7) + 1

    def tile_index(self, x, y):
        k = self.kind[y][x]
        r = random.Random(x * 131 + y * 7 + len(self.key))
        if k == "grass":
            return r.choice((0, 0, 0, 1, 1, 2, 3, 4, 5, 6, 7))
        if k == "sand":
            return TILE_SAND + r.choice((0, 0, 1, 2, 3, 4, 5, 6, 7))
        if k.startswith("floor_"):
            base = {"floor_wood": 0, "floor_dark": 4, "floor_stone": 8, "floor_check": 12}[k]
            return TILE_FLOOR + base + (x + y) % 4
        if k.startswith("wall_"):
            _, col, part = k.split("_")
            return TILE_WALL + WALLPAPERS.index(col) * 3 + ("top", "mid", "base").index(part)
        if k == "void":
            return TILE_WALL + 12
        base = {"path": 16, "stone": 32, "water": 48, "ocean": TILE_OCEAN_A}[k]
        m = 0
        for bit, (dx, dy) in ((N_, (0, -1)), (E_, (1, 0)), (S_, (0, 1)), (W_, (-1, 0))):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < self.w and 0 <= ny < self.h) or self.kind[ny][nx] == k:
                m |= bit
        return base + m

    def save(self):
        data = [self.tile_index(x, y) + 1 for y in range(self.h) for x in range(self.w)]
        deco = [self.deco[y][x] for y in range(self.h) for x in range(self.w)]
        tm = {
            "compressionlevel": -1, "height": self.h, "width": self.w, "infinite": False, "orientation": "orthogonal",
            "renderorder": "right-down", "tiledversion": "1.10.2", "tileheight": T, "tilewidth": T, "type": "map",
            "version": "1.10", "nextlayerid": 4, "nextobjectid": self.oid + 1,
            "tilesets": [{"firstgid": 1, "name": "terrain", "image": "../terrain_spring.png", "imagewidth": 256,
                          "imageheight": 160, "tilewidth": T, "tileheight": T, "tilecount": 160, "columns": 16,
                          "margin": 0, "spacing": 0}],
            "layers": [
                {"id": 1, "name": "ground", "type": "tilelayer", "width": self.w, "height": self.h, "x": 0, "y": 0,
                 "opacity": 1, "visible": True, "data": data},
                {"id": 2, "name": "decor", "type": "tilelayer", "width": self.w, "height": self.h, "x": 0, "y": 0,
                 "opacity": 1, "visible": True, "data": deco},
                {"id": 3, "name": "objects", "type": "objectgroup", "draworder": "topdown", "x": 0, "y": 0,
                 "opacity": 1, "visible": True, "objects": self.objs},
            ],
        }
        (OUT / "maps").mkdir(exist_ok=True)
        (OUT / "maps" / f"{self.key}.json").write_text(json.dumps(tm))


OUTDOOR_TREES = ["oak0", "oak1", "oak2", "bush0", "bush1"]
FOREST_TREES = ["oak0", "oak1", "oak2", "pine0", "pine1", "pine0"]


def farm_map():
    m = MapBuilder("farm", 36, 28)
    m.fill(5, 8, 2, 5, "path"); m.fill(5, 11, 31, 2, "path")
    door = m.building("farmhouse", "farmhouse", 3, 7, 5, 3)
    m.obj("farmdoor", "farmdoor", door[0], door[1])
    m.location("farm", (0, 0, 36, 28), (12, 10),
               items=[(9, 8), (10, 8), (11, 8), (12, 8), (13, 8), (14, 8), (9, 9), (14, 9), (20, 9), (21, 9), (22, 9), (23, 9)],
               people=[(16, 10), (18, 9)])
    m.obj("shipping_bin", "prop", 9, 7, sprite="shipping_bin", w="2"); m.block(9, 6, 2, 1)
    m.obj("mailbox", "prop", 7, 9, sprite="mailbox"); m.block(7, 8, 1, 1)
    m.obj("well", "prop", 25, 7, sprite="well", w="2"); m.block(25, 6, 2, 1)
    for i, x in enumerate((6, 9, 12, 15)):
        m.obj(f"plot{i + 1}", "plot", x, 16, 2, 2)
    m.block(4, 14, 16, 6)
    for x in range(4, 20):
        if x not in (11, 12):
            m.obj("fence", "fence_h", x, 14)
        m.obj("fence", "fence_h", x, 19)
    for y in range(14, 20):
        m.obj("fence", "fence_v", 3, y); m.obj("fence", "fence_v", 20, y)
    m.fill(11, 13, 2, 1, "path")
    m.fill(27, 18, 6, 4, "water")
    for (x, y) in ((8, 12), (24, 12)):
        m.obj("lamppost", "lamppost", x, y + 1); m.block(x, y)
    m.exit("town", 35, 11, (1, 18))
    m.trees(1, 26, (0, 0, 36, 28), OUTDOOR_TREES)
    m.sprinkle(2, 50)
    m.save()


TOWN_BUILDINGS = [  # (location id, sprite, x, bottom, width)
    ("shop", "shop", 20, 8, 8), ("bakery", "bakery", 9, 8, 5), ("smithy", "smithy", 33, 8, 5),
    ("florist", "florist", 5, 17, 4), ("clinic", "clinic", 5, 27, 5), ("library", "library", 39, 18, 6),
    ("inn", "inn", 37, 29, 7),
]


def town_map():
    m = MapBuilder("town", 48, 36)
    m.fill(17, 13, 15, 12, "stone")
    m.fill(0, 18, 17, 2, "path"); m.fill(32, 18, 16, 2, "path")      # west / east roads
    m.fill(23, 0, 3, 13, "path"); m.fill(23, 25, 3, 11, "path")      # north / south roads
    for loc, sprite, x, bottom, w in TOWN_BUILDINGS:
        door = (x + w // 2, bottom + 1)
        # short path from each door to the nearest road
        if door[1] < 13:
            m.fill(door[0], door[1], 1, 13 - door[1], "path")
            m.fill(min(door[0], 23), 12, abs(door[0] - 23) + 1, 1, "path")
        elif door[1] <= 24:
            xa, xb = sorted((door[0], 17 if door[0] < 17 else 31))
            m.fill(xa, door[1], xb - xa + 1, 1, "path")
        else:
            xa, xb = sorted((door[0], 23 if door[0] < 23 else 25))
            m.fill(xa, door[1], xb - xa + 1, 1, "path")
        m.building(loc, sprite, x, bottom, w, interior=f"int_{loc}", loc=loc)
    m.obj("fountain", "fountain", 23, 19, 3, 2); m.block(23, 16, 3, 4)
    m.location("plaza", (17, 13, 15, 12), (24, 22),
               items=[(18, 14), (19, 14), (29, 14), (30, 14), (18, 23), (30, 23), (18, 19), (30, 19), (21, 23), (27, 23), (20, 16), (28, 16)],
               people=[(20, 18), (28, 18), (21, 21), (27, 21), (20, 20), (28, 20), (22, 15), (26, 15), (19, 22), (29, 22), (21, 17), (27, 17)])
    for (x, y) in ((17, 13), (31, 13), (17, 24), (31, 24), (12, 20), (36, 20)):
        m.obj("lamppost", "lamppost", x, y + 1); m.block(x, y)
    for (x, y, sp) in ((20, 15, "bench"), (27, 15, "bench"), (18, 21, "flowerbed"), (29, 21, "flowerbed")):
        m.obj(sp, "plaza_decor", x, y + 1, sprite=sp); m.block(x, y, 2, 1)
    m.exit("farm", 0, 18, (34, 11)); m.exit("lane", 47, 18, (1, 15))
    m.exit("mountain", 24, 0, (22, 30)); m.exit("beach", 24, 35, (22, 1))
    m.trees(3, 30, (0, 0, 48, 36), OUTDOOR_TREES)
    m.sprinkle(4, 60)
    m.save()


def lane_map():
    m = MapBuilder("lane", 46, 30)
    m.fill(0, 15, 3, 2, "path"); m.fill(1, 10, 2, 13, "path")
    m.fill(1, 10, 45, 2, "path"); m.fill(1, 21, 45, 2, "path")
    xs = (4, 11, 18, 25, 32, 39)
    for i, x in enumerate(xs):
        m.building(f"home{i + 1}", f"house{i}", x, 8, 4, interior="int_house", loc=f"home{i + 1}")
        m.fill(x + 2, 9, 1, 1, "path")
        m.building(f"home{i + 7}", f"house{i + 6}", x, 19, 4, interior="int_house", loc=f"home{i + 7}")
        m.fill(x + 2, 20, 1, 1, "path")
        for (fx, fy) in ((x - 1, 9), (x + 4, 9), (x - 1, 20), (x + 4, 20)):
            m.obj("pot", "plaza_decor", fx, fy + 1, sprite=f"f_pot{(fx + fy) % 4}"); m.block(fx, fy)
    for x in range(8, 46, 7):
        m.obj("lamppost", "lamppost", x, 13); m.block(x, 12)
    m.exit("town", 0, 15, (46, 18))
    m.trees(5, 24, (0, 0, 46, 30), OUTDOOR_TREES)
    m.sprinkle(6, 50)
    m.save()


def mountain_map():
    m = MapBuilder("mountain", 44, 32)
    m.fill(21, 18, 3, 14, "path"); m.fill(10, 12, 13, 2, "path"); m.fill(10, 9, 2, 4, "path")
    m.fill(23, 18, 10, 2, "path")
    m.fill(30, 4, 7, 5, "water")
    m.obj("mine", "building", 4, 7, 6, 3, sprite="mine")
    m.block(3, 0, 9, 9)
    m.location("mine", (2, 0, 14, 15), (10, 11),
               items=[(7, 10), (8, 11), (13, 10), (14, 11), (6, 12), (13, 13)],
               people=[(9, 10), (12, 11), (11, 13)])
    m.location("forest", (24, 10, 18, 16), (31, 18),
               items=[(27, 14), (29, 22), (35, 21), (38, 15), (33, 13), (26, 20), (36, 24), (30, 12)],
               people=[(29, 17), (33, 17), (31, 20)])
    m.obj("cart", "plaza_decor", 13, 12, sprite="cart_orange"); m.block(13, 11, 2, 1)
    m.exit("town", 22, 31, (24, 1))
    m.trees(7, 70, (0, 0, 44, 32), FOREST_TREES)
    m.sprinkle(8, 60)
    m.save()


def beach_map():
    m = MapBuilder("beach", 44, 26, base="sand")
    m.fill(0, 0, 44, 3, "grass")
    m.fill(0, 17, 44, 9, "ocean")
    for x in range(44):  # wavy shoreline
        if math.sin(x * .6) > .3:
            m.kind[16][x] = "ocean"
    m.fill(21, 0, 3, 4, "path")
    m.fill(20, 12, 4, 13, "floor_dark")  # the pier, walkable over the water
    for y in (14, 18, 22):
        for x in (19, 24):
            m.obj("post", "prop", x, y, sprite="pier_post"); m.block(x, y)
    m.obj("boat", "plaza_decor", 25, 21, sprite="boat")
    m.location("pier", (14, 8, 16, 17), (21, 14),
               items=[(20, 13), (23, 13), (20, 20), (23, 20), (17, 11), (26, 11)],
               people=[(21, 18), (22, 22), (22, 16)])
    m.exit("town", 22, 0, (24, 34))
    m.trees(9, 12, (0, 0, 44, 3), OUTDOOR_TREES)
    m.sprinkle(10, 40)
    m.save()


INTERIORS = {  # kind -> (wallpaper, floor, [(sprite, x, bottom_row, solid_w, solid_h)])
    "house": ("cream", "floor_wood", [("f_bed", 1, 6, 1, 2), ("f_table", 6, 7, 2, 1), ("f_chair", 5, 7, 1, 1),
                                      ("f_chair", 8, 7, 1, 1), ("f_rug", 5, 10, 0, 0), ("f_bookshelf", 12, 4, 2, 1),
                                      ("f_plant", 14, 6, 1, 1), ("f_fireplace", 9, 2, 2, 1)]),
    "shop": ("blue", "floor_wood", [("f_counter", 6, 5, 3, 1), ("f_shelf", 1, 4, 2, 1), ("f_shelf", 3, 4, 2, 1),
                                    ("f_shelf", 11, 4, 2, 1), ("f_shelf", 13, 4, 2, 1), ("barrel_orange", 1, 9, 1, 1),
                                    ("barrel_green", 14, 9, 1, 1), ("f_plant", 14, 6, 1, 1)]),
    "bakery": ("rose", "floor_dark", [("f_oven", 1, 4, 2, 2), ("f_counter", 6, 5, 3, 1), ("f_shelf", 12, 4, 2, 1),
                                      ("f_table", 11, 9, 2, 1), ("f_chair", 10, 9, 1, 1), ("f_chair", 13, 9, 1, 1)]),
    "smithy": ("cream", "floor_stone", [("f_forge", 1, 4, 2, 2), ("f_anvil", 5, 6, 1, 1), ("f_toolrack", 10, 2, 0, 0),
                                        ("f_toolrack", 12, 2, 0, 0), ("barrel_purple", 13, 6, 1, 1), ("barrel_red", 14, 6, 1, 1),
                                        ("f_counter", 9, 9, 3, 1)]),
    "florist": ("green", "floor_wood", [("f_counter", 6, 5, 3, 1), ("f_pot0", 1, 4, 1, 1), ("f_pot1", 2, 4, 1, 1),
                                        ("f_pot2", 3, 4, 1, 1), ("f_pot3", 12, 4, 1, 1), ("f_pot0", 13, 4, 1, 1),
                                        ("f_pot2", 14, 4, 1, 1), ("f_plant", 1, 9, 1, 1), ("f_plant", 14, 9, 1, 1)]),
    "clinic": ("blue", "floor_check", [("f_clinicbed", 1, 6, 1, 2), ("f_clinicbed", 3, 6, 1, 2), ("f_counter", 9, 5, 3, 1),
                                       ("f_cabinet", 13, 3, 1, 1), ("f_cabinet", 14, 3, 1, 1), ("f_plant", 14, 9, 1, 1)]),
    "library": ("green", "floor_dark", [("f_bookshelf", 1, 4, 2, 1), ("f_bookshelf", 3, 4, 2, 1), ("f_bookshelf", 11, 4, 2, 1),
                                        ("f_bookshelf", 13, 4, 2, 1), ("f_table", 6, 8, 2, 1), ("f_chair", 5, 8, 1, 1),
                                        ("f_chair", 8, 8, 1, 1), ("f_rug", 5, 11, 0, 0)]),
    "inn": ("rose", "floor_wood", [("f_bar", 1, 5, 4, 1), ("barrel_orange", 6, 4, 1, 1), ("f_fireplace", 11, 2, 2, 1),
                                   ("f_table", 10, 8, 2, 1), ("f_chair", 9, 8, 1, 1), ("f_chair", 12, 8, 1, 1),
                                   ("f_table", 3, 9, 2, 1), ("f_chair", 2, 9, 1, 1), ("f_chair", 5, 9, 1, 1)]),
}


def interior_map(kind):
    wall, floor, furn = INTERIORS[kind]
    m = MapBuilder(f"int_{kind}", 16, 12, base=floor)
    for x in range(16):
        m.kind[0][x] = f"wall_{wall}_top"; m.kind[1][x] = f"wall_{wall}_mid"; m.kind[2][x] = f"wall_{wall}_base"
    m.block(0, 0, 16, 3)
    for x in (4, 11):
        m.obj("window", "furniture", x, 2, sprite="f_window", solid="0,0")
    m.obj("painting", "furniture", 7, 2, sprite="f_painting", solid="0,0")
    for sp, x, b, sw, sh in furn:
        m.obj(sp, "furniture", x, b + 1, sprite=sp, solid=f"{sw},{sh}")
        if sw:
            m.block(x, b - sh + 1, sw, sh)
    m.obj("doormat", "furniture", 7, 12, sprite="f_doormat", solid="0,0")
    m.location("here", (0, 3, 16, 9), (8, 10),
               items=[(4, 7), (6, 6), (9, 6), (11, 7), (4, 10), (12, 10), (3, 8), (13, 8)],
               people=[(8, 6), (5, 8), (11, 8), (7, 9), (10, 10), (3, 10)])
    m.exit("@parent", 8, 11, (0, 0))
    m.save()


def make_maps():
    farm_map(); town_map(); lane_map(); mountain_map(); beach_map()
    for k in INTERIORS:
        interior_map(k)
    # scene graph summary for the client
    graph = {"outdoor": ["farm", "town", "lane", "mountain", "beach"], "interiors": list(INTERIORS),
             "layout": {"mountain": [1, 0], "farm": [0, 1], "town": [1, 1], "lane": [2, 1], "beach": [1, 2]}}
    (OUT / "maps" / "scenes.json").write_text(json.dumps(graph))
