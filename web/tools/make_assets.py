#!/usr/bin/env python
"""Generate SeedVille's original pixel-art assets and its Tiled scene maps.

    python web/tools/make_assets.py          # writes web/assets/*

Everything is drawn procedurally at 16 px per tile with hand-picked colour ramps, so the
whole set is original (no third-party art). Sheets follow common conventions (16x16 tile
sets, 16x32 characters in 4 directions x 4 frames, Tiled .json map) so a downloaded asset
pack can replace any of them later: keep the file names and frame layout.

Outputs
  terrain_<season>.png   tileset, 16 columns (see TILE_* constants below)
  props_<season>.png     trees/bushes/rocks per season (atlas + props.json)
  buildings_<season>.png farmhouse, shop, houses (atlas + buildings.json)
  objects.png            fountain, lamppost, benches, plots, crops, items, ... (+ objects.json)
  chars/<name>_<color>.png, chars/player.png   16x32 frames, rows: down, left, right, up
  portraits/<name>_<color>.png                 48x48
  ui.png (+ ui.json)     panels, slots, emotes, icons
  maps/<scene>.json      Tiled maps: farm, town, lane, mountain, beach and interiors (see scenes.py)
"""

from __future__ import annotations

import math
import random

import charart
import scenes
import treeart



from pixel import (C, CLEAR, COLOR_NAMES, DIRT, GRASS, ITEM_COLORS, OUT, PLASTER, ROOF, SEASONS, SOIL,  # noqa: E402
                   SOIL_WET, STONE, WATER, WOOD, Atlas, T, hue_ramp, hx, ramp, shade)


# ============================================================================ terrain tiles
# tileset index layout (16 columns)
TILE_GRASS = 0          # 0..7 grass variants (row 0)
TILE_PATH = 16          # +mask (row 1)   mask bits: N=1 E=2 S=4 W=8 (bit set = same terrain there)
TILE_STONE = 32         # +mask (row 2)
TILE_WATER_A = 48       # +mask (row 3)
TILE_WATER_B = 64       # +mask (row 4)
TILE_DECOR = 80         # row 5: flowers, pebbles, tall grass, mushrooms, fallen leaves, clover
N_, E_, S_, W_ = 1, 2, 4, 8


def grass_tile(season, variant, rng):
    g = GRASS[season]
    c = C(T, T)
    c.rect(0, 0, T, T, g[2])
    for _ in range(14):  # soft clumps
        x, y = rng.randrange(T), rng.randrange(T)
        c.p(x, y, g[1] if rng.random() < .5 else g[3])
    if season == "winter":
        for _ in range(5):
            x, y = rng.randrange(T), rng.randrange(T)
            c.p(x, y, g[1])
        if variant in (4, 5):
            for _ in range(3):
                x, y = rng.randrange(2, 14), rng.randrange(3, 14)
                c.p(x, y, WOOD[1]); c.p(x + 1, y - 1, WOOD[2])
        return c
    nblades = {0: 4, 1: 6, 2: 3, 3: 8, 4: 10, 5: 12, 6: 5, 7: 5}[variant]
    for _ in range(nblades):  # grass blades: shadow, body, tip
        x, y = rng.randrange(1, 15), rng.randrange(3, 15)
        c.p(x, y + 1, g[1]); c.p(x, y, g[3]); c.p(x, y - 1, g[4])
        if rng.random() < .5:
            c.p(x + 1, y, g[3])
    if variant >= 6:
        petals = {"spring": ["#f4a6c8", "#ffffff", "#f6d24a"], "summer": ["#f6d24a", "#ffffff", "#e8842c"],
                  "fall": ["#d2552a", "#e8a03a", "#b8433a"]}[season]
        for _ in range(2):
            x, y = rng.randrange(2, 13), rng.randrange(2, 13)
            col = hx(rng.choice(petals))
            c.p(x, y + 2, g[1])
            for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
                c.p(x + dx, y + dy, col)
            c.p(x, y, hx("#f6e27a") if col != hx("#f6d24a") else hx("#ffffff"))
    return c


def edge_noise(rng, n=T):
    return [rng.choice((0, 1, 1, 2)) for _ in range(n)]


def masked_tile(fill_fn, mask, season, rng, border_dark, rim=None):
    """Terrain with organic grass overhang on sides where the neighbour is not the same terrain."""
    g = GRASS[season]
    c = fill_fn(rng)
    for side, bit in (("n", N_), ("e", E_), ("s", S_), ("w", W_)):
        if mask & bit:
            continue
        depth = edge_noise(rng)
        for i in range(T):
            d = 2 + depth[i]
            for k in range(d):
                if side == "n":
                    x, y = i, k
                elif side == "s":
                    x, y = i, T - 1 - k
                elif side == "w":
                    x, y = k, i
                else:
                    x, y = T - 1 - k, i
                c.p(x, y, g[2] if k < d - 1 else g[3])
            # dark rim where the terrain meets the grass
            if side == "n":
                c.p(i, d, border_dark)
            elif side == "s":
                c.p(i, T - 1 - d, rim or border_dark)
            elif side == "w":
                c.p(d, i, border_dark)
            else:
                c.p(T - 1 - d, i, border_dark)
    # rounded outer corners
    for (bx, by, cx, cy) in ((N_, W_, 0, 0), (N_, E_, T - 3, 0), (S_, W_, 0, T - 3), (S_, E_, T - 3, T - 3)):
        if not (mask & bx) and not (mask & by):
            c.rect(cx, cy, 3, 3, g[2])
    return c


def dirt_fill(rng):
    c = C(T, T)
    c.rect(0, 0, T, T, DIRT[2])
    for _ in range(16):
        c.p(rng.randrange(T), rng.randrange(T), DIRT[1] if rng.random() < .55 else DIRT[3])
    for _ in range(3):  # pebbles
        x, y = rng.randrange(1, 14), rng.randrange(1, 14)
        c.p(x, y, DIRT[4]); c.p(x + 1, y + 1, DIRT[1])
    return c


def stone_fill(rng):
    c = C(T, T)
    c.rect(0, 0, T, T, STONE[1])
    for row in range(4):
        off = 4 if row % 2 else 0
        for col in range(-1, 3):
            x0, y0 = col * 8 + off, row * 4
            v = rng.choice((2, 2, 3))
            c.rect(x0 + 1, y0 + 1, 6, 2, STONE[v])
            c.hline(x0 + 1, y0 + 1, 6, STONE[v + 1] if v < 4 else STONE[4])
            if rng.random() < .3:
                c.p(x0 + rng.randrange(2, 6), y0 + 2, STONE[1])
    return c


def water_fill(rng, frame):
    c = C(T, T)
    c.rect(0, 0, T, T, WATER[2])
    for _ in range(10):
        c.p(rng.randrange(T), rng.randrange(T), WATER[1])
    r2 = random.Random(frame * 99 + rng.randrange(10))
    for _ in range(3):
        x, y = r2.randrange(1, 12), r2.randrange(2, 14)
        c.hline(x, y, 3, WATER[3])
        c.p(x + 1, y - 1, WATER[4])
    return c


def decor_tiles(season, rng):
    g = GRASS[season]
    out = []
    # 0-1 flower clusters
    for k in range(2):
        c = grass_tile(season, 0, random.Random(500 + k))
        if season != "winter":
            cols = {"spring": ["#f4a6c8", "#c98bf0"], "summer": ["#f6d24a", "#e8842c"], "fall": ["#d2552a", "#e0a03a"]}[season]
            for (x, y) in ((4, 6), (9, 4), (7, 10), (12, 9)):
                col = hx(cols[(x + y + k) % 2])
                c.p(x, y + 2, g[1]); c.p(x, y + 1, g[1])
                for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1), (0, 0)):
                    c.p(x + dx, y + dy, col)
                c.p(x, y, hx("#fff6b0"))
        out.append(c)
    # 2-3 pebbles / small rocks
    for k in range(2):
        c = grass_tile(season, 1, random.Random(600 + k))
        for (x, y, r) in ((5, 9, 2), (10, 6, 1), (11, 11, 1)):
            c.ellipse(x, y, r + .5, r, STONE[2]); c.p(x - 1, y - 1, STONE[4]); c.hline(x - r, y + r, 2 * r + 1, STONE[0])
        out.append(c)
    # 4-5 tall grass
    for k in range(2):
        c = grass_tile(season, 3, random.Random(700 + k))
        for x in range(2, 14, 2):
            h = 5 + (x * 7 + k) % 4
            for y in range(h):
                c.p(x + (1 if y > h - 3 else 0), 14 - y, g[3] if y < h - 1 else g[4])
            c.p(x, 15, g[0])
        out.append(c)
    # 6 mushrooms
    c = grass_tile(season, 2, random.Random(800))
    for (x, y) in ((5, 10), (9, 8)):
        c.rect(x, y, 1, 3, hx("#efe6d2")); c.ellipse(x, y, 2.4, 1.4, hx("#c0392b")); c.p(x - 1, y - 1, hx("#ffffff"))
    out.append(c)
    # 7 fallen leaves / twigs
    c = grass_tile(season, 0, random.Random(900))
    for _ in range(6):
        x, y = rng.randrange(2, 14), rng.randrange(2, 14)
        col = hx(rng.choice(["#d2552a", "#e0a03a", "#b8433a"])) if season in ("fall", "summer") else WOOD[2]
        c.p(x, y, col); c.p(x + 1, y, shade(col, .8))
    out.append(c)
    return out


def make_terrain(season):
    sheet = C(16 * T, 10 * T)
    rng = random.Random(hash(season) & 0xFFFF)
    for v in range(8):
        sheet.paste(grass_tile(season, v, random.Random(100 + v)), v * T, 0)
    for m in range(16):
        sheet.paste(masked_tile(dirt_fill, m, season, random.Random(200 + m), DIRT[1], DIRT[0]), m * T, 1 * T)
        sheet.paste(masked_tile(stone_fill, m, season, random.Random(300 + m), STONE[0]), m * T, 2 * T)
        for f, row in ((0, 3), (1, 4)):
            wt = masked_tile(lambda r, f=f: water_fill(r, f), m, season, random.Random(400 + m), WATER[0],
                             WATER[4])
            sheet.paste(wt, m * T, row * T)
    for i, d in enumerate(decor_tiles(season, rng)):
        sheet.paste(d, i * T, 5 * T)
    scenes.extra_tiles(sheet, season)
    sheet.im.save(OUT / f"terrain_{season}.png")


# ============================================================================ props (trees etc.)
BARK = ramp("#2e1a10", "#4a2c1a", "#6b4228", "#8a5a36")


def rock(seed, big=False):
    rng = random.Random(seed)
    c = C(16, 16)
    r = 6 if big else 4
    c.blob(8, 11 - (1 if big else 0), r, STONE[1:], light=(-1, -1.4), rng=rng)
    c.p(6, 8, STONE[4])
    c.outline()
    return c


def stump():
    c = C(16, 16)
    c.ellipse(8, 10, 6, 4, BARK[2]); c.ellipse(8, 8, 5.5, 2.5, hx("#c99a62")); c.ellipse(8, 8, 3, 1.4, hx("#a87a48"))
    c.outline()
    return c


def make_props(season):
    a = Atlas(512)

    def wrap(im):
        c = C(im.width, im.height)
        c.im = im
        c.px = im.load()
        return c

    for k in range(3):
        a.add(f"oak{k}", wrap(treeart.oak(season, 10 + k)))
    for k in range(2):
        a.add(f"pine{k}", wrap(treeart.pine(season, 20 + k)))
    for k in range(2):
        a.add(f"bush{k}", wrap(treeart.bush(season, 30 + k)))
    a.add("rock0", rock(40)); a.add("rock1", rock(41, big=True)); a.add("stump", stump())
    a.save(OUT / f"props_{season}.png", OUT / f"props_{season}.json")


# ============================================================================ buildings
def shingles(c, x, y, w, h, base, rng):
    R = hue_ramp(base)
    for row in range(h // 3 + 1):
        yy = y + row * 3
        off = 3 if row % 2 else 0
        c.rect(x, yy, w, 3, R[2] if row % 2 else R[1])
        c.hline(x, yy, w, R[3])
        for xx in range(x - off, x + w, 6):
            c.vline(xx, yy, 3, R[0])
        if rng.random() < .3:
            c.p(x + rng.randrange(w), yy + 1, R[4])
    return R


def window(c, x, y, w=10, h=9, lit=False):
    c.rect(x - 1, y - 1, w + 2, h + 2, WOOD[1])
    c.rect(x, y, w, h, hx("#f6d98a") if lit else hx("#3c6fa0"))
    if not lit:
        c.rect(x, y, w, 2, hx("#6aa4d0")); c.p(x + 1, y + 2, hx("#cfe8f6")); c.p(x + 2, y + 3, hx("#cfe8f6"))
    c.vline(x + w // 2, y, h, WOOD[2]); c.hline(x, y + h // 2, w, WOOD[2])
    c.rect(x - 2, y + h + 1, w + 4, 2, WOOD[3])  # sill


def door(c, x, y, w=12, h=18, col="#7a4a2c"):
    D = hue_ramp(col)
    c.rect(x - 1, y - 1, w + 2, h + 1, WOOD[0])
    c.rect(x, y, w, h, D[2])
    for xx in range(x + 2, x + w, 4):
        c.vline(xx, y + 1, h - 1, D[1])
    c.rect(x + 1, y + 1, w - 2, 2, D[3])
    c.p(x + w - 3, y + h // 2, hx("#f2b632"))


def siding(c, x, y, w, h, base):
    R = hue_ramp(base)
    c.rect(x, y, w, h, R[2])
    for yy in range(y, y + h, 4):
        c.hline(x, yy, w, R[1]); c.hline(x, yy + 1, w, R[3])
    return R


def flowerbox(c, x, y, w, rng):
    c.rect(x, y, w, 3, WOOD[2]); c.hline(x, y, w, WOOD[3])
    for xx in range(x + 1, x + w - 1, 2):
        c.p(xx, y - 1, hx(rng.choice(["#f4a6c8", "#f6d24a", "#e85a4a", "#ffffff"])))
        c.p(xx, y - 2 + (xx % 2), hx("#4a8f3a"))


def snow_roof(c, x, y, w, h, rng):
    for row in range(0, h, 3):
        for xx in range(x, x + w):
            if rng.random() < .85:
                c.p(xx, y + row, hx("#ffffff"))
                if rng.random() < .5:
                    c.p(xx, y + row + 1, hx("#e2eaf3"))


def house(roof, wall_kind, season, seed, w=64, h=64, chimney=True):
    rng = random.Random(seed)
    c = C(w, h + 8)
    top = 8
    roof_h = int(h * .5)
    wall_y = top + roof_h - 4
    wall_h = h - roof_h + 4 - 6
    # foundation
    c.rect(2, top + h - 7, w - 4, 7, STONE[1]); c.hline(2, top + h - 7, w - 4, STONE[3])
    for xx in range(4, w - 4, 7):
        c.vline(xx, top + h - 6, 6, STONE[0])
    if wall_kind == "plaster":
        c.rect(4, wall_y, w - 8, wall_h, PLASTER[2])
        for xx in (4, w - 8):
            c.rect(xx, wall_y, 4, wall_h, WOOD[2])
        c.hline(4, wall_y + wall_h // 2, w - 8, WOOD[2])
    else:
        siding(c, 4, wall_y, w - 8, wall_h, wall_kind)
    # roof: shingles with eaves overhang
    R = shingles(c, 0, top, w, roof_h, roof, rng)
    for row in range(roof_h):  # slanted sides
        cut = max(0, 10 - row)
        c.rect(0, top + row, cut, 1, CLEAR); c.rect(w - cut, top + row, cut, 1, CLEAR)
    c.hline(0, top + roof_h - 1, w, R[0]); c.hline(1, top + roof_h, w - 2, shade(R[0], .7))
    if chimney:
        c.rect(w - 18, 0, 8, top + 8, STONE[2]); c.hline(w - 19, 0, 10, STONE[3]); c.vline(w - 18, 1, top + 6, STONE[1])
    # door + windows
    dx = w // 2 - 6
    door(c, dx, top + h - 7 - 18, col="#8a4a2c" if seed % 2 else "#4f6f8f")
    window(c, 9, wall_y + 6)
    window(c, w - 19, wall_y + 6)
    flowerbox(c, 7, wall_y + 18, 16, rng)
    flowerbox(c, w - 21, wall_y + 18, 16, rng)
    if season == "winter":
        snow_roof(c, 0, top, w, roof_h, rng)
    c.outline()
    return c


def shop_building(season):
    rng = random.Random(77)
    w, h = 128, 96
    c = house("#2f6f8f", "#b8956a", season, 5, w, h, chimney=False)
    # awning over the shop front
    for i in range(0, 96, 8):
        col = hx("#c0392b") if (i // 8) % 2 == 0 else hx("#f6ead0")
        c.rect(16 + i, 58, 8, 7, col); c.rect(16 + i, 65, 8, 2, shade(col, .75))
        c.p(16 + i + 3, 67, shade(col, .75)); c.p(16 + i + 4, 68, shade(col, .75))
    # sign board with a bag icon
    c.rect(44, 44, 40, 12, WOOD[1]); c.rect(45, 45, 38, 10, hx("#f1d9a7"))
    c.rect(58, 47, 12, 7, hx("#c08a56")); c.hline(60, 46, 8, WOOD[1]); c.p(63, 50, hx("#f2b632")); c.p(64, 50, hx("#f2b632"))
    # crates out front
    for x in (8, 104):
        c.rect(x, 86, 14, 11, WOOD[2]); c.rect(x, 86, 14, 2, WOOD[3]); c.vline(x + 7, 86, 11, WOOD[1])
        for k in range(4):
            c.ellipse(x + 3 + k * 3, 85, 1.6, 1.4, hx(["#c0392b", "#f6d24a", "#3f9e48", "#e8842c"][k]))
    if season == "winter":
        snow_roof(c, 0, 8, w, 46, rng)
    c.outline()
    return c


def farmhouse(season):
    c = house("#a8432f", "#a86a3a", season, 3, 80, 80)
    return c


def make_buildings(season):
    a = Atlas(512)
    a.add("farmhouse", farmhouse(season))
    a.add("shop", shop_building(season))
    roofs = ["purple", "blue", "red", "green", "orange", "teal"]
    walls = ["plaster", "#9c6a44", "#b8956a", "plaster", "#8a6a8a", "#7a8a6a"]
    for i in range(12):  # 12 homes: every roof colour with two wall styles
        a.add(f"house{i}", house(ROOF[roofs[i % 6]], walls[(i + i // 6 * 3) % 6], season, 11 + i))
    for kind in ("bakery", "smithy", "florist", "clinic", "library", "inn"):
        a.add(kind, scenes.workplace(kind, season, house))
    a.add("mine", scenes.mine_entrance(season))
    a.save(OUT / f"buildings_{season}.png", OUT / f"buildings_{season}.json")


# ============================================================================ objects (season-independent)
def fountain(frame):
    c = C(48, 48)
    c.ellipse(24, 30, 22, 13, STONE[1]); c.ellipse(24, 29, 21, 12, STONE[3]); c.ellipse(24, 30, 18, 9.5, STONE[1])
    c.ellipse(24, 31, 17, 8.5, WATER[2])
    rng = random.Random(frame)
    for _ in range(8):
        x, y = rng.randrange(10, 38), rng.randrange(26, 37)
        if c.get(x, y) == WATER[2]:
            c.hline(x, y, 3, WATER[3])
    c.rect(21, 14, 6, 16, STONE[2]); c.rect(21, 14, 2, 16, STONE[3]); c.rect(25, 14, 2, 16, STONE[1])
    c.ellipse(24, 14, 7, 3, STONE[3]); c.ellipse(24, 14, 5.5, 2, WATER[3])
    for k, (dx, dy) in enumerate(((-4, -3), (4, -3), (0, -6))):
        h = 4 + ((frame + k) % 3)
        for j in range(h):
            c.p(24 + dx + (j // 3) * (1 if dx > 0 else -1 if dx < 0 else 0), 12 + dy + j - h, WATER[4])
    for (dx, dy) in ((-9, 7), (9, 7), (0, 12)):
        c.p(24 + dx + (frame % 2), 29 + dy - 8, WATER[4])
    c.outline()
    return c


def lamppost():
    c = C(16, 32)
    c.rect(7, 10, 2, 20, hx("#2a2a33")); c.rect(5, 29, 6, 2, hx("#2a2a33")); c.p(7, 11, hx("#5a5a66"))
    c.rect(4, 3, 8, 8, hx("#2a2a33")); c.rect(5, 4, 6, 6, hx("#f6e08a")); c.rect(5, 4, 2, 6, hx("#fff6c8"))
    c.hline(3, 2, 10, hx("#2a2a33")); c.p(7, 1, hx("#2a2a33")); c.p(8, 1, hx("#2a2a33"))
    c.outline()
    return c


def bench(col):
    R = hue_ramp(ITEM_COLORS.get(col, "#9c663c")) if col else WOOD
    c = C(32, 16)
    c.rect(2, 3, 28, 3, R[2]); c.hline(2, 3, 28, R[3])
    c.rect(2, 8, 28, 3, R[2]); c.hline(2, 8, 28, R[3])
    for x in (4, 26):
        c.rect(x, 3, 2, 12, hx("#2a2a33"))
    c.outline()
    return c


def barrel(col):
    R = hue_ramp(ITEM_COLORS.get(col, "#9c663c"))
    c = C(16, 16)
    c.rect(3, 2, 10, 13, WOOD[2]); c.rect(4, 2, 3, 13, WOOD[3]); c.rect(11, 2, 2, 13, WOOD[1])
    c.hline(3, 4, 10, R[1]); c.hline(3, 12, 10, R[1]); c.ellipse(8, 2, 5, 1.2, WOOD[3])
    c.outline()
    return c


def signpost(col):
    R = hue_ramp(ITEM_COLORS.get(col, "#9c663c"))
    c = C(16, 16)
    c.rect(7, 7, 2, 9, WOOD[2]); c.rect(2, 2, 12, 6, R[2]); c.hline(2, 2, 12, R[3]); c.hline(4, 4, 7, R[0])
    c.p(13, 4, R[2]); c.p(14, 5, R[2])
    c.outline()
    return c


def flowerbed(col):
    R = hue_ramp(ITEM_COLORS.get(col, "#cf3f38"))
    c = C(32, 16)
    c.rect(1, 8, 30, 7, WOOD[2]); c.hline(1, 8, 30, WOOD[3]); c.rect(2, 9, 28, 2, SOIL[1])
    rng = random.Random(col)
    for x in range(3, 30, 3):
        y = 5 + rng.randrange(3)
        c.vline(x, y + 1, 9 - y, hx("#4a8f3a"))
        c.p(x, y, R[3]); c.p(x - 1, y + 1, R[2]); c.p(x + 1, y + 1, R[2]); c.p(x, y + 1, hx("#fff3b0"))
    c.outline()
    return c


def cart(col):
    R = hue_ramp(ITEM_COLORS.get(col, "#9c663c"))
    c = C(32, 24)
    c.rect(3, 6, 26, 10, R[2]); c.hline(3, 6, 26, R[3]); c.rect(3, 14, 26, 2, R[0])
    for x in range(6, 28, 6):
        c.vline(x, 7, 7, R[1])
    for x in (9, 23):
        c.ellipse(x, 18, 4, 4, WOOD[1]); c.ellipse(x, 18, 2, 2, WOOD[3]); c.p(x, 18, WOOD[0])
    c.rect(28, 10, 4, 2, WOOD[2])
    c.outline()
    return c


def lamppost_light():
    c = C(64, 64)
    for y in range(64):
        for x in range(64):
            d = math.hypot(x - 31.5, y - 31.5) / 32
            if d < 1:
                a = int(255 * (1 - d) ** 1.6)
                c.px[x, y] = (255, 255, 255, a)
    return c


def plot_tile(wet):
    S = SOIL_WET if wet else SOIL
    c = C(32, 32)
    c.rect(1, 1, 30, 30, S[2])
    for y in range(4, 30, 6):
        c.rect(2, y, 28, 2, S[1]); c.hline(2, y + 2, 28, S[3])
    for x in (1, 30):
        c.vline(x, 1, 30, S[1])
    c.hline(1, 1, 30, S[3]); c.hline(1, 30, 30, S[0])
    rng = random.Random(wet)
    for _ in range(18):
        c.p(rng.randrange(2, 30), rng.randrange(2, 30), S[3] if rng.random() < .5 else S[1])
    if wet:
        for _ in range(6):
            x, y = rng.randrange(3, 28), rng.randrange(3, 28)
            c.hline(x, y, 2, hx("#5a7a9a"))
    return c


CROP_SPEC = {  # main fruit ramp base, leaf base
    "turnip": ("#f0ead8", "#5fae45"), "melon": ("#5fae45", "#3f8a34"),
    "pumpkin": ("#e8842c", "#4f8f3a"), "berry": ("#3c5fd8", "#3f8a34"),
}


def crop_sprite(crop, stage, color=None):
    """stage: planted | growing | ripe | withered | dormant ; 16x32 so tall plants fit."""
    fruit_base, leaf_base = CROP_SPEC[crop]
    if color:
        fruit_base = ITEM_COLORS[color]
    F, Lf = hue_ramp(fruit_base), hue_ramp(leaf_base)
    c = C(16, 32)
    gy = 28  # ground line
    if stage == "planted":
        for (x, y) in ((4, gy - 1), (8, gy), (11, gy - 1)):
            c.p(x, y, SOIL[0]); c.p(x + 1, y, SOIL[3])
        return c
    if stage == "dormant":
        c.ellipse(8, gy - 1, 4, 2, SOIL[3]); c.p(7, gy - 3, hx("#8a7a5a")); c.p(8, gy - 3, hx("#8a7a5a"))
        c.outline()
        return c
    if stage == "withered":
        c.vline(8, gy - 9, 9, hx("#7a5a32")); c.hline(4, gy - 7, 4, hx("#8a6a3a")); c.hline(9, gy - 5, 4, hx("#8a6a3a"))
        c.p(3, gy - 6, hx("#6a4a2a")); c.p(13, gy - 4, hx("#6a4a2a"))
        c.outline(hx("#3a2414"))
        return c
    if stage == "growing":
        c.vline(8, gy - 8, 8, Lf[1])
        c.ellipse(5, gy - 7, 3, 1.5, Lf[2]); c.ellipse(11, gy - 9, 3, 1.5, Lf[3]); c.p(4, gy - 8, Lf[4])
        c.outline()
        return c
    # ripe
    if crop == "turnip":
        c.ellipse(8, gy - 3, 5, 4, F[3]); c.ellipse(8, gy - 1, 5, 2, hx("#a55aa8")); c.p(6, gy - 5, F[4])
        for dx in (-3, 0, 3):
            c.vline(8 + dx, gy - 13, 7, Lf[2]); c.ellipse(8 + dx, gy - 13, 1.5, 2.5, Lf[3])
    elif crop == "melon":
        for dx in (-5, 5):
            c.ellipse(8 + dx, gy - 6, 2.5, 1.5, Lf[2])
        c.ellipse(8, gy - 4, 6.5, 5, F[2])
        for x in range(3, 14, 3):
            c.vline(x, gy - 8, 8, F[1])
        c.p(6, gy - 7, F[4]); c.p(7, gy - 8, F[4])
    elif crop == "pumpkin":
        c.vline(8, gy - 11, 3, Lf[1]); c.ellipse(5, gy - 10, 2.5, 1.4, Lf[2])
        c.ellipse(8, gy - 4, 7, 5, F[2])
        for x in (5, 8, 11):
            c.vline(x, gy - 8, 9, F[1])
        c.p(4, gy - 6, F[4]); c.p(5, gy - 7, F[4])
    else:  # berry bush
        c.blob(8, gy - 7, 6, Lf, rng=random.Random(3))
        for (x, y) in ((5, gy - 9), (10, gy - 10), (11, gy - 5), (6, gy - 4), (8, gy - 7)):
            c.rect(x, y, 2, 2, F[2]); c.p(x, y, F[4])
    c.outline()
    return c


def item_icon(name, category, color):
    R = hue_ramp(ITEM_COLORS.get(color, "#888888"))
    c = C(16, 16)
    if category == "food":
        # coloured cloth under the food
        c.ellipse(8, 12, 7, 2.5, R[2]); c.hline(2, 12, 12, R[3]); c.p(3, 13, R[1]); c.p(12, 13, R[1])
        if name == "bread":
            c.ellipse(8, 8, 6, 3.5, hx("#c9894a")); c.ellipse(8, 7, 5, 2.5, hx("#e0a866"))
            for x in (5, 8, 11):
                c.p(x, 6, hx("#f6d8a0")); c.p(x + 1, 7, hx("#a8673a"))
        elif name == "pie":
            c.ellipse(8, 9, 6, 3, hx("#d99a5a")); c.ellipse(8, 8, 5, 2, hx("#a83a4a"))
            c.hline(4, 8, 9, hx("#f0c890")); c.vline(8, 6, 4, hx("#f0c890"))
        else:  # cheese
            for y in range(5, 11):
                c.hline(3 + (10 - y) // 2, y, 10 - (10 - y) // 2, hx("#f2cf4a"))
            c.hline(3, 10, 10, hx("#d9a62a")); c.p(7, 8, hx("#d9a62a")); c.p(10, 9, hx("#d9a62a"))
    elif category == "flower":
        c.vline(8, 7, 8, hx("#3f8a3a")); c.hline(5, 11, 3, hx("#4f9e48")); c.hline(9, 9, 3, hx("#4f9e48"))
        if name == "rose":
            c.blob(8, 5, 3, R[1:], rng=random.Random(1)); c.p(8, 4, R[0]); c.p(7, 5, R[4])
        elif name == "tulip":
            c.rect(6, 3, 5, 5, R[2]); c.p(6, 2, R[2]); c.p(8, 2, R[3]); c.p(10, 2, R[2]); c.vline(7, 4, 3, R[3])
        else:
            for dx, dy in ((0, -3), (-3, 0), (3, 0), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2)):
                c.p(8 + dx, 5 + dy, R[3]); c.p(8 + dx // 2, 5 + dy // 2, R[2])
            c.rect(7, 4, 2, 2, hx("#f6d24a"))
    elif category == "metal":
        if name == "ingot":
            for y in range(7, 12):
                c.hline(3 + (11 - y) // 2, y, 10 + (y - 7), R[2])
            c.hline(4, 7, 8, R[4]); c.hline(3, 11, 11, R[0])
        elif name == "bell":
            c.ellipse(8, 8, 4, 4, R[2]); c.rect(4, 8, 9, 4, R[2]); c.hline(3, 12, 11, R[1]); c.p(6, 6, R[4])
            c.p(8, 3, R[1]); c.p(8, 13, hx("#555566"))
        else:  # horseshoe
            for a in range(0, 180, 12):
                x = 8 + 5 * math.cos(math.radians(a + 180)); y = 9 + 5 * math.sin(math.radians(a + 180))
                c.rect(x, y, 2, 2, R[2])
            c.vline(3, 9, 4, R[2]); c.vline(12, 9, 4, R[2]); c.p(5, 5, R[4])
    elif category == "gem":
        if name == "ruby":
            c.hline(5, 4, 6, R[3]); c.rect(4, 5, 8, 3, R[2]); c.rect(5, 8, 6, 2, R[2]); c.rect(6, 10, 4, 2, R[1])
            c.p(7, 12, R[0]); c.p(8, 12, R[0]); c.p(5, 5, R[4]); c.p(6, 5, R[4])
        elif name == "opal":
            c.ellipse(8, 8, 4.5, 5.5, R[2]); c.p(6, 6, R[4]); c.p(7, 5, R[4]); c.p(9, 9, hx("#ffffff")); c.p(10, 7, R[3])
        else:  # quartz
            for x, h in ((5, 6), (8, 9), (11, 5)):
                c.rect(x - 1, 13 - h, 3, h, R[2]); c.p(x, 13 - h - 1, R[3]); c.vline(x - 1, 13 - h, h, R[4])
    c.outline()
    return c


def produce_icon(crop, color):
    s = crop_sprite(crop, "ripe", color)
    c = C(16, 16)
    c.im.alpha_composite(s.im.crop((0, 14, 16, 30)), (0, 0))
    c.px = c.im.load()
    return c


def seed_packet(crop):
    fruit, leaf = CROP_SPEC[crop]
    c = C(16, 16)
    c.rect(3, 2, 10, 13, hx("#efe2c2")); c.hline(3, 2, 10, hx("#d8c49a")); c.rect(3, 2, 10, 2, hx("#b89a6a"))
    c.ellipse(8, 9, 3, 3, hx(fruit)); c.p(8, 5, hx(leaf)); c.p(7, 6, hx(leaf))
    c.hline(4, 13, 8, hx("#b89a6a"))
    c.outline()
    return c


def watering_can(color):
    R = hue_ramp(ITEM_COLORS.get(color, "#7a8a9a"))
    c = C(16, 16)
    c.rect(3, 7, 8, 7, R[2]); c.rect(3, 7, 8, 2, R[3]); c.vline(10, 7, 7, R[1])
    for k in range(4):
        c.p(11 + k, 8 - k, R[2])
    c.rect(14, 4, 2, 2, R[1])
    c.hline(4, 4, 6, R[1]); c.vline(4, 4, 3, R[1]); c.vline(9, 4, 3, R[1])
    c.outline()
    return c


def trophy():
    G = hue_ramp("#f2b632")
    c = C(16, 16)
    c.rect(4, 2, 8, 6, G[2]); c.rect(4, 2, 2, 6, G[4]); c.rect(10, 2, 2, 6, G[1])
    c.rect(2, 3, 2, 3, G[1]); c.rect(12, 3, 2, 3, G[1]); c.rect(6, 8, 4, 2, G[1]); c.rect(7, 10, 2, 2, G[2])
    c.rect(4, 12, 8, 3, WOOD[2]); c.hline(4, 12, 8, WOOD[3])
    c.outline()
    return c


def coin():
    G = hue_ramp("#f2b632")
    c = C(16, 16)
    c.ellipse(8, 8, 5, 5, G[2]); c.ellipse(8, 8, 3, 3, G[3]); c.p(6, 5, G[4]); c.vline(8, 6, 5, G[1])
    c.outline()
    return c


def bed():
    c = C(16, 24)
    c.rect(1, 2, 14, 21, WOOD[2]); c.rect(2, 4, 12, 5, hx("#f6f0e0")); c.rect(2, 9, 12, 12, hx("#3f6fd6"))
    c.hline(2, 9, 12, hx("#6a92e8")); c.rect(2, 19, 12, 2, hx("#2f55a8"))
    c.outline()
    return c


def fence(kind):
    c = C(16, 16)
    if kind == "h":
        c.rect(0, 6, 16, 2, WOOD[3]); c.rect(0, 10, 16, 2, WOOD[2])
        c.rect(1, 3, 3, 12, WOOD[2]); c.rect(1, 3, 1, 12, WOOD[3]); c.p(2, 2, WOOD[3])
    else:
        c.rect(6, 0, 3, 16, WOOD[2]); c.rect(6, 0, 1, 16, WOOD[3])
    c.outline()
    return c


def shipping_bin():
    c = C(32, 24)
    c.rect(2, 6, 28, 16, WOOD[2])
    for x in range(4, 30, 5):
        c.vline(x, 7, 15, WOOD[1])
    c.rect(1, 3, 30, 5, WOOD[3]); c.hline(1, 3, 30, WOOD[4]); c.rect(13, 10, 6, 4, hx("#f2b632"))
    c.outline()
    return c


def mailbox():
    c = C(16, 24)
    c.rect(7, 10, 2, 13, WOOD[2]); c.rect(3, 4, 10, 7, hx("#3f6fd6")); c.ellipse(8, 4, 5, 2, hx("#3f6fd6"))
    c.rect(12, 2, 1, 5, hx("#cf3f38")); c.rect(12, 2, 3, 2, hx("#cf3f38"))
    c.outline()
    return c


def well():
    c = C(32, 32)
    c.ellipse(16, 22, 12, 7, STONE[1]); c.ellipse(16, 21, 11, 6, STONE[3]); c.ellipse(16, 21, 8, 4, WATER[1])
    c.rect(5, 4, 2, 18, WOOD[2]); c.rect(25, 4, 2, 18, WOOD[2])
    for row in range(5):
        c.hline(3 + row, 2 + row, 26 - 2 * row, WOOD[3] if row % 2 else WOOD[2])
    c.outline()
    return c


def make_objects():
    a = Atlas(512)
    for f in range(3):
        a.add(f"fountain{f}", fountain(f))
    a.add("lamppost", lamppost())
    a.add("light", lamppost_light())
    a.add("plot_dry", plot_tile(False)); a.add("plot_wet", plot_tile(True))
    a.add("bed", bed()); a.add("fence_h", fence("h")); a.add("fence_v", fence("v"))
    a.add("shipping_bin", shipping_bin()); a.add("mailbox", mailbox()); a.add("well", well())
    for col in COLOR_NAMES:
        a.add(f"bench_{col}", bench(col)); a.add(f"barrel_{col}", barrel(col)); a.add(f"signpost_{col}", signpost(col))
        a.add(f"flowerbed_{col}", flowerbed(col)); a.add(f"cart_{col}", cart(col))
        a.add(f"can_{col}", watering_can(col))
    for crop in CROP_SPEC:
        for st in ("planted", "growing", "ripe", "withered", "dormant"):
            a.add(f"crop_{crop}_{st}", crop_sprite(crop, st))
        a.add(f"seeds_{crop}", seed_packet(crop))
        for col in COLOR_NAMES:
            a.add(f"produce_{crop}_{col}", produce_icon(crop, col))
    names = {"food": ["bread", "pie", "cheese"], "metal": ["ingot", "bell", "horseshoe"],
             "flower": ["rose", "tulip", "daisy"], "gem": ["ruby", "opal", "quartz"]}
    for cat, ns in names.items():
        for n in ns:
            for col in COLOR_NAMES:
                a.add(f"item_{n}_{col}", item_icon(n, cat, col))
    a.add("trophy", trophy()); a.add("coin", coin())
    sh = C(14, 5)
    for y in range(5):
        for x in range(14):
            d = ((x - 6.5) / 7) ** 2 + ((y - 2) / 2.5) ** 2
            if d <= 1:
                sh.px[x, y] = (20, 30, 20, int(85 * (1 - d * .5)))
    a.add("shadow", sh)
    for k, c in scenes.furniture().items():
        a.add(k, c)
    a.add("pier_post", scenes.pier_post()); a.add("boat", scenes.boat())
    a.save(OUT / "objects.png", OUT / "objects.json")


# ============================================================================ characters
SKINS = [ramp("#8a5a3c", "#c98d64", "#efc29a", "#fadcbc"), ramp("#6a3f28", "#a86a44", "#d4935e", "#e8b07c"),
         ramp("#3f2418", "#6b3f28", "#93603c", "#b07a50")]
HAIRS = {"brown": ramp("#2a160c", "#4a2a16", "#6e4224", "#8e5a32"), "blonde": ramp("#7a5a1a", "#b8902e", "#e0bc4a", "#f6dc7a"),
         "black": ramp("#0e0e14", "#1e1e2a", "#33334a", "#4a4a66"), "red": ramp("#5a1a0e", "#8a2e16", "#b8482a", "#d9683f"),
         "grey": ramp("#4a4a52", "#7a7a86", "#a8a8b4", "#d0d0d8"), "teal": ramp("#123a3a", "#1f5f5f", "#2f8a86", "#56b2aa")}
VILLAGERS = {  # name -> (skin, hair, style)
    "Rosa": (0, "red", "long"), "Tomas": (1, "black", "short"), "Ivy": (0, "blonde", "bun"),
    "Bram": (2, "black", "beard"), "Lena": (1, "teal", "ponytail"), "Otto": (0, "grey", "bald"),
    "Mira": (2, "black", "long"), "Finn": (0, "red", "spiky"),
    "Hana": (0, "black", "bun"), "Leo": (1, "blonde", "short"), "Clara": (0, "brown", "ponytail"),
    "Abe": (1, "grey", "beard"),
}


def make_chars():
    (OUT / "chars").mkdir(exist_ok=True)
    (OUT / "portraits").mkdir(exist_ok=True)
    player = dict(skin=SKINS[0], hair_ramp=tuple(HAIRS["brown"][1:4]), style="short", shirt="#f6f0e0",
                  hat=True, overalls=True)
    charart.sheet(**player).save(OUT / "chars" / "player.png")
    charart.portrait_from(**player).save(OUT / "portraits" / "player.png")
    for name, (sk, hair, style) in VILLAGERS.items():
        for col in COLOR_NAMES:
            kw = dict(skin=SKINS[sk], hair_ramp=tuple(HAIRS[hair][1:4]), style=style, shirt=ITEM_COLORS[col])
            charart.sheet(**kw).save(OUT / "chars" / f"{name}_{col}.png")
            charart.portrait_from(**kw).save(OUT / "portraits" / f"{name}_{col}.png")


# ============================================================================ UI
def make_ui():
    a = Atlas(256)
    # 9-slice panel 24x24: wood frame + parchment
    p = C(24, 24)
    p.rect(0, 0, 24, 24, WOOD[1]); p.rect(1, 1, 22, 22, WOOD[3]); p.rect(2, 2, 20, 20, WOOD[2])
    p.rect(4, 4, 16, 16, hx("#f1d9a7")); p.hline(4, 4, 16, hx("#d9b878")); p.vline(4, 4, 16, hx("#d9b878"))
    for (x, y) in ((1, 1), (22, 1), (1, 22), (22, 22)):
        p.p(x, y, WOOD[4])
    a.add("panel", p)
    s = C(20, 20)
    s.rect(0, 0, 20, 20, WOOD[2]); s.rect(1, 1, 18, 18, hx("#d9b878")); s.rect(2, 2, 16, 16, hx("#ecd09a"))
    s.hline(2, 2, 16, hx("#c9a466")); s.vline(2, 2, 16, hx("#c9a466"))
    a.add("slot", s)
    sel = C(22, 22)
    for i in range(22):
        for (x, y) in ((i, 0), (i, 1), (i, 20), (i, 21), (0, i), (1, i), (20, i), (21, i)):
            sel.p(x, y, hx("#f2b632") if (i // 3) % 2 else hx("#c0392b"))
    a.add("slot_sel", sel)

    def bubble(draw):
        b = C(16, 16)
        b.ellipse(8, 7, 7, 6, hx("#ffffff")); b.p(5, 13, hx("#ffffff")); b.p(4, 14, hx("#ffffff"))
        b.outline(hx("#3a2312"))
        draw(b)
        return b

    a.add("emote_heart", bubble(lambda b: (b.ellipse(6, 6, 2, 2, hx("#e0457b")), b.ellipse(10, 6, 2, 2, hx("#e0457b")),
                                            [b.hline(4 + k, 7 + k, 9 - 2 * k, hx("#e0457b")) for k in range(4)])))
    a.add("emote_bang", bubble(lambda b: (b.rect(7, 3, 2, 6, hx("#c0392b")), b.rect(7, 10, 2, 2, hx("#c0392b")))))
    a.add("emote_q", bubble(lambda b: (b.hline(6, 3, 4, hx("#3a6fd8")), b.p(10, 4, hx("#3a6fd8")), b.p(10, 5, hx("#3a6fd8")),
                                        b.p(9, 6, hx("#3a6fd8")), b.p(8, 7, hx("#3a6fd8")), b.p(8, 8, hx("#3a6fd8")),
                                        b.p(8, 10, hx("#3a6fd8")), b.p(5, 4, hx("#3a6fd8")))))
    a.add("emote_dots", bubble(lambda b: [b.rect(x, 7, 2, 2, hx("#6e4b2c")) for x in (4, 7, 10)]))
    a.add("emote_zzz", bubble(lambda b: (b.hline(4, 4, 4, hx("#3a6fd8")), b.p(6, 5, hx("#3a6fd8")), b.p(5, 6, hx("#3a6fd8")),
                                          b.hline(4, 7, 4, hx("#3a6fd8")), b.hline(9, 8, 3, hx("#3a6fd8")), b.p(10, 9, hx("#3a6fd8")),
                                          b.hline(9, 10, 3, hx("#3a6fd8")))))
    a.add("emote_note", bubble(lambda b: (b.vline(9, 3, 7, hx("#3a2312")), b.ellipse(7, 10, 2, 1.5, hx("#3a2312")), b.hline(9, 3, 3, hx("#3a2312")))))
    heart = C(9, 8)
    for (x, y, w) in ((1, 0, 3), (5, 0, 3), (0, 1, 9), (0, 2, 9), (1, 3, 7), (2, 4, 5), (3, 5, 3), (4, 6, 1)):
        heart.hline(x, y, w, hx("#e0457b"))
    heart.p(2, 1, hx("#ff9ab8"))
    a.add("heart", heart)
    he = C(9, 8)
    for (x, y, w) in ((1, 0, 3), (5, 0, 3), (0, 1, 9), (0, 2, 9), (1, 3, 7), (2, 4, 5), (3, 5, 3), (4, 6, 1)):
        he.hline(x, y, w, hx("#b8a07a"))
    a.add("heart_empty", he)
    sun = C(12, 12)
    sun.ellipse(6, 6, 3.5, 3.5, hx("#f6c84a"))
    for (dx, dy) in ((0, -6), (0, 5), (-6, 0), (5, 0), (-4, -4), (4, -4), (-4, 4), (4, 4)):
        sun.p(6 + dx, 6 + dy, hx("#f2a33a"))
    a.add("sun", sun)
    moon = C(12, 12)
    moon.ellipse(6, 6, 4, 4, hx("#f6f0c8")); moon.ellipse(8, 5, 3, 3, CLEAR)
    a.add("moon", moon)
    cur = C(12, 12)
    for i in range(9):
        cur.hline(0, i, max(1, 9 - i), hx("#ffffff"))
    cur.outline(hx("#3a2312"))
    a.add("cursor", cur)
    a.save(OUT / "ui.png", OUT / "ui.json")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for s in SEASONS:
        make_terrain(s)
        make_props(s)
        make_buildings(s)
    make_objects()
    make_chars()
    make_ui()
    scenes.make_maps()
    print("assets written to", OUT)


if __name__ == "__main__":
    main()
