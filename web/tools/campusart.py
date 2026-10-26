#!/usr/bin/env python
"""The AgentCity skin of the town (web/codeworld.html): a research campus instead of a farming village.

    python web/tools/campusart.py        # writes web/assets/campus.png + campus.json, chars/eng_*, portraits/eng_*

Same frames as kairoart.py (the page swaps one atlas for the other), drawn as a campus: lawns, gravel yards,
paving and asphalt, solar arrays where the fields were, chillers where the rocks were, labs of glass with
server racks, workstations and robot arms, a data centre for the library, a relay tower for the post office
and a big screen for the notice board. The people are engineers (dark trousers, sneakers, a badge).
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import charart  # noqa: E402
from isoart import tri  # noqa: E402
from kairoart import LOOKS_KINDS, TH, TW, Big, Thing, blob, ground, speckle, checker, planks  # noqa: E402
from make_people import HAIRS, SKINS, VILLAGERS  # noqa: E402
from pixel import COLOR_NAMES, ITEM_COLORS, OUT, Atlas, hx, mix, shade  # noqa: E402

WHITE = hx("#ffffff")
LED = [hx("#3fe08a"), hx("#4ab8ff"), hx("#ffd24a"), hx("#3fe08a"), hx("#3fe08a")]


# ---------------------------------------------------------------------------- ground
def joints(base, line, n=2):
    b, l_ = hx(base), hx(line)
    return lambda u, v, rng: l_ if (u * n) % 1 < .09 or (v * n) % 1 < .09 else (b if rng.random() > .08 else shade(b, .96))


def solar(u, v, rng):
    frame, cell, hi = hx("#c9ced6"), hx("#24467e"), hx("#6f95d0")
    if u < .08 or v < .08 or u > .92 or v > .92:
        return frame
    if (u * 4) % 1 < .1 or (v * 3) % 1 < .1:
        return hi
    return cell if rng.random() > .06 else hx("#2c5492")


def canal(phase):
    def f(u, v, rng):
        base, hi = hx("#2e8fb4"), hx("#a6e6f4")
        if ((u * 3 + v * 2 + phase * .5) % 1) < .07 and rng.random() < .8:
            return hi
        return base if rng.random() > .05 else hx("#3a9cc0")
    return f


def grating(u, v, rng):
    a, b = hx("#9aa4b2"), hx("#6f7a8a")
    return b if (u * 6) % 1 < .25 or (v * 6) % 1 < .25 else a


def raised_floor(u, v, rng):
    a, line, dot = hx("#d3d8e0"), hx("#aab2be"), hx("#b9c0cb")
    if (u * 2) % 1 < .06 or (v * 2) % 1 < .06:
        return line
    return dot if (int(u * 12) + int(v * 12)) % 3 == 0 else a


# ---------------------------------------------------------------------------- labs
LAB = {  # wall, accent, floor; the kinds are the town's (bakery is the ML lab, and so on)
    "bakery": ("#eef2f6", "#3f7fe0", speckle("#5d7096", ["#52658a", "#6a7ea4"], .25)),
    "smithy": ("#e6e9ee", "#59606e", checker("#8c939e", "#7f8792")),
    "florist": ("#f2f4f2", "#22a892", planks("#dcc8a4", "#c4ae88")),
    "mine": ("#eceef0", "#e8b032", checker("#a3a9b1", "#959ba3")),
    "clinic": ("#f6f8fb", "#33a866", checker("#ffffff", "#e2ecf6")),
    "inn": ("#f3efe8", "#e0763a", planks("#bb8d60", "#9c724a")),
    "shop": ("#e9e6f2", "#8456d4", speckle("#3d4456", ["#353c4c", "#465064"], .25)),
    "farm": ("#e2e6ec", "#2f3d52", raised_floor),
}
GLASS = hx("#8fc4e8")


def wall(kind, axis, low=False, window=False):
    """A lab wall: white panels with the lab's colour along the top; the window walls are mostly glass."""
    w, accent, _ = LAB[kind]
    h = 5 if low else 20
    t = Thing(h + 2)
    pal = {**tri(w), "top": hx(accent)}

    def deco(a, b, width, hh, base, rng, side):
        if low:
            return shade(GLASS, .95 if side == "l" else .8) if b >= 2 else base
        if b >= hh - 3:
            return shade(hx(accent), .95 if side == "l" else .75)
        if b < 2:
            return shade(base, .82)
        if window and 2 <= a <= width - 3 and 4 <= b <= hh - 5:
            g = mix(GLASS, WHITE, .45 if (a + b) % 7 == 0 else .1)
            return g if a % 6 else shade(hx("#c3cad4"), .9)
        return base

    if axis == "x":
        t.box(0, 13 if low else 0, 16, 3, h, pal, deco)
    else:
        t.box(13 if low else 0, 0, 3, 16, h, pal, deco)
    return t.done()


def leds(rows, cols, top, bottom, seed):
    """A face full of status lights."""
    rng = random.Random(seed)

    def f(a, b, width, h, base, r, side):
        if side == "l" and 1 <= a < width - 1 and bottom <= b < h - top and b % rows == 1 and a % cols == 1:
            return rng.choice(LED)
        if side == "l" and 1 <= a < width - 1 and bottom <= b < h - top and b % rows == 0:
            return shade(base, .7)
        return base
    return f


def tech():
    """One sprite per kind of machine (worldseeds/codeworld/recipes.py LOOK names), as lab equipment."""
    out = {}
    dark, steel, white = tri("#3a4150"), tri("#9aa2ae"), tri("#e8ecf2")
    # mill -> server rack
    t = Thing(22); t.box(4, 4, 8, 8, 19, dark, leds(3, 2, 2, 2, 1)); out["mill"] = t.done()
    # churn -> GPU node (wide, with fans)
    t = Thing(16)
    t.box(2, 3, 12, 10, 10, dark, lambda a, b, w, h, base, r, s:
          (hx("#76e04a") if b == h - 2 and s == "l" else hx("#1d2230") if s == "l" and (a % 5 in (1, 2, 3)) and 2 <= b <= 6 else base))
    out["churn"] = t.done()
    # rack -> storage array (drive bays)
    t = Thing(20); t.box(3, 4, 10, 8, 16, steel, lambda a, b, w, h, base, r, s:
        (hx("#2a3140") if s == "l" and b % 4 in (1, 2) and 1 <= a < w - 1 else hx("#4ab8ff") if s == "l" and b % 4 == 3 and a == w - 2 else base))
    out["rack"] = t.done()
    # press -> 3D printer (frame with a print bed)
    t = Thing(18)
    t.box(3, 3, 10, 10, 3, white)
    for gx, gy in ((3, 3), (12, 3), (3, 12), (12, 12)):
        t.box(gx, gy, 1, 1, 14, dark)
    t.box(3, 3, 10, 10, 0, white)
    t.box(6, 6, 4, 4, 5, tri("#e0763a"))
    out["press"] = t.done()
    # oven -> workstation: a desk with two monitors
    t = Thing(18)
    t.box(2, 4, 12, 8, 6, tri("#c9b08a"))
    t.box(4, 6, 3, 1, 12, dark, lambda a, b, w, h, base, r, s: hx("#4ab8ff") if 7 <= b <= 11 else base)
    t.box(9, 6, 3, 1, 12, dark, lambda a, b, w, h, base, r, s: hx("#76e0c0") if 7 <= b <= 11 else base)
    out["oven"] = t.done()
    # furnace -> liquid cooling unit (pipes)
    t = Thing(16); t.box(2, 3, 12, 10, 10, steel, lambda a, b, w, h, base, r, s:
        hx("#3fa0e0") if s == "l" and b in (3, 7) else base)
    t.box(11, 4, 2, 2, 14, tri("#3fa0e0"))
    out["furnace"] = t.done()
    # anvil -> robot arm on a base
    t = Thing(22)
    t.box(4, 4, 8, 8, 4, dark)
    t.box(7, 7, 2, 2, 12, tri("#e8b032"))
    t.box(4, 7, 5, 2, 2, tri("#e8b032"))
    c = t.done()
    ox, oy = 16 - 3, t.base - 12
    for k in range(5):
        c.p(ox - k, oy - k // 2, hx("#f2c44a")); c.p(ox - k, oy - k // 2 + 1, hx("#c08a22"))
    c.p(ox - 6, oy - 3, hx("#3a4150")); c.p(ox - 6, oy - 1, hx("#3a4150"))
    out["anvil"] = c
    # cart -> delivery robot
    t = Thing(14); t.box(4, 4, 8, 8, 7, white, lambda a, b, w, h, base, r, s:
        hx("#22a892") if b == h - 2 else hx("#1d2230") if s == "l" and b == 4 and 2 <= a <= w - 3 else base)
    for gx, gy in ((4, 11), (11, 11)):
        ox, oy = t.at(gx, gy); t.iso.c.ellipse(ox - 1, oy - 1, 1.5, 1.5, hx("#22262e"))
    out["cart"] = t.done()
    # still -> lab bench with flasks
    t = Thing(18); t.box(2, 4, 12, 8, 7, white)
    c = t.iso.c
    for k, col in enumerate(("#4ab8ff", "#3fe08a", "#e0457b")):
        x, y = 12 + k * 4, t.base - 5 + (k % 2)
        c.rect(x, y - 3, 2, 4, mix(hx(col), WHITE, .2)); c.p(x, y - 4, hx("#c9d6e2"))
    out["still"] = t.done()
    # shelf -> whiteboard with plots
    t = Thing(22)
    t.box(3, 7, 10, 2, 16, white, lambda a, b, w, h, base, r, s:
          (hx("#e0457b") if s == "l" and 8 <= b <= 13 and (a + b) % 5 == 0 else
           hx("#3f7fe0") if s == "l" and b == 6 + (a % 6 > 2) and 1 < a < w - 1 else
           hx("#9aa2ae") if s == "l" and (a in (0, w - 1) or b in (2, h - 1)) else base))
    t.box(4, 7, 1, 1, 3, steel); t.box(11, 7, 1, 1, 3, steel)
    out["shelf"] = t.done()
    # table -> desk with a laptop
    t = Thing(14); t.box(2, 3, 12, 10, 6, tri("#d8c4a0"))
    c = t.iso.c
    c.rect(13, t.base - 5, 6, 2, hx("#3a4150")); c.rect(14, t.base - 9, 5, 4, hx("#4ab8ff")); c.p(20, t.base - 4, hx("#f2d27a"))
    out["table"] = t.done()
    return out


def machine(kind, v):
    """Fallback machines (worlds without looks): a rack or a workstation."""
    return tech()["mill" if v == 0 else "oven"]


# ---------------------------------------------------------------------------- outdoors
GREEN = [hx("#2c6a44"), hx("#37845a"), hx("#4fa070"), hx("#7cc48e")]


def tree_round(seed):
    rng = random.Random(seed)
    t = Thing(30)
    t.box(5, 5, 6, 6, 3, tri("#9aa2ae"))  # a planter
    t.box(7, 7, 2, 2, 9, tri("#7a5a40"))
    blob(t, 16, t.base - 12, 7, GREEN, rng)
    return t.done()


def tree_column(seed):
    t = Thing(34)
    t.box(7, 7, 2, 2, 4, tri("#6a4e38"))
    c = t.iso.c
    for j in range(26):
        y = t.base - 2 - j
        half = 1 + min(j, 25 - j) // 4
        for x in range(16 - half, 16 + half + 1):
            c.p(x, y, GREEN[2] if x < 16 else GREEN[1] if x < 17 + half // 2 else GREEN[0])
            t.iso.face[y][x] = 501
    return t.done()


def tree_birch(seed):
    rng = random.Random(seed)
    t = Thing(34)
    c = t.iso.c
    for k in range(20):
        y = t.base + 4 - k
        c.p(16, y, hx("#eef0ea") if k % 4 else hx("#3a3a3a")); c.p(17, y, hx("#c9ccc4"))
        t.iso.face[y][16] = t.iso.face[y][17] = 502
    blob(t, 16, t.base - 20, 6, [hx("#3f8a3a"), hx("#5aa84a"), hx("#7cc45e"), hx("#a6dc7a")], rng)
    return t.done()


def hedge(seed, flowers=None):
    t = Thing(12)
    if flowers:
        t.box(3, 3, 10, 10, 5, tri("#9aa2ae"))
        rng = random.Random(seed)
        for _ in range(8):
            t.iso.c.p(16 + rng.randint(-4, 4), t.base - 2 + rng.randint(-2, 3), hx(flowers))
        blob(t, 16, t.base - 1, 3, GREEN, rng)
    else:
        t.box(3, 3, 10, 10, 7, {"top": GREEN[3], "left": GREEN[2], "right": GREEN[1]})
    return t.done()


def chiller(big=False):
    t = Thing(14 if big else 9)
    pal = tri("#b4bac4")
    if big:
        t.box(1, 1, 14, 14, 9, pal, lambda a, b, w, h, base, r, s: shade(base, .8) if b % 3 == 0 else base)
        for gx, gy in ((4, 4), (9, 9)):
            ox, oy = t.at(gx, gy)
            t.iso.c.ellipse(ox + 1, oy - 9, 3, 1.5, hx("#3a4150"))
    else:
        t.box(3, 4, 10, 8, 6, pal, lambda a, b, w, h, base, r, s:
              hx("#3a4150") if s == "l" and 2 <= a <= 6 and 1 <= b <= 4 and (a + b) % 2 else base)
    return t.done()


def office(seed):
    """A small office block: glass bands, flat roof."""
    cols = [("#e8ecf2", "#3f7fe0"), ("#dfe4ea", "#22a892"), ("#ece8e2", "#e0763a")][seed % 3]
    t = Thing(26)
    t.box(2, 2, 12, 12, 20, tri(cols[0]), lambda a, b, w, h, base, r, s:
          (mix(GLASS, WHITE, .25 if (a + b) % 9 else .6) if b % 6 in (2, 3, 4) and 1 <= a < w - 1 else
           hx(cols[1]) if b == h - 1 else base))
    return t.done()


def streetlight():
    t = Thing(24)
    t.box(7, 7, 1, 1, 20, tri("#3a4150"))
    t.box(4, 6, 4, 2, 1, {"top": hx("#ffffff"), "left": hx("#e8f6ff"), "right": hx("#bfe6ff")})
    c = t.done()
    return c


def small(kind):
    t = Thing(12)
    if kind == "barrel":  # recycling bins
        t.box(3, 5, 4, 5, 7, tri("#33a866")); t.box(9, 5, 4, 5, 7, tri("#3f7fe0"))
    elif kind == "crate":  # parcel lockers
        t.box(3, 5, 10, 5, 9, tri("#e8ecf2"), lambda a, b, w, h, base, r, s:
              hx("#9aa2ae") if s == "l" and (a % 3 == 0 or b % 3 == 0) else base)
    elif kind == "umbrella":  # a café table under a sail
        t.box(6, 6, 4, 4, 4, tri("#d8c4a0")); t.box(7, 7, 1, 1, 9, tri("#e8ecf2"))
        ox, oy = t.at(2, 2)
        t.iso.pyramid(ox, oy - 9, 12, 12, tri("#22a892"), 80)
    elif kind == "sign":  # a digital kiosk
        t.box(6, 7, 4, 2, 11, tri("#3a4150"), lambda a, b, w, h, base, r, s:
              hx("#4ab8ff") if s == "l" and 4 <= b <= 9 and 0 < a < w - 1 else base)
    return t.done()


def fountain():
    t = Thing(14)
    t.box(1, 1, 14, 14, 3, tri("#c9ced6"))
    ox, oy = t.at(3, 3)
    t.iso.diamond(ox, oy - 3, 10, 10, hx("#4ab8e6"), 60)
    t.box(6, 6, 4, 4, 10, tri("#e8ecf2"))  # a sculpture
    t.box(7, 7, 2, 2, 14, tri("#3f7fe0"))
    return t.done()


# ---------------------------------------------------------------------------- campus buildings
def data_centre():
    b = Big(4, 3, 30)
    rng = random.Random(3)

    def face(a, bb, w, h, base, r, s):
        if bb >= h - 2:
            return hx("#4ab8ff")
        if a % 6 == 0 and 3 <= bb <= h - 4:
            return rng.choice(LED) if bb % 2 else hx("#1d2230")
        return base

    b.box(2, 2, 60, 44, 20, tri("#3a4150"), face)
    for gx, gy in ((10, 8), (24, 8), (38, 8), (10, 24), (24, 24)):  # chillers on the roof
        ox, oy = b.at(2 + gx, 2 + gy)
        b.iso.box(ox, oy - 20, 10, 10, 4, tri("#b4bac4"), None, rng)
    b.box(30, 46, 10, 4, 10, tri("#9aa2ae"))  # door
    return b.iso.finish()


def relay_tower():
    b = Big(4, 3, 54)
    rng = random.Random(4)
    b.box(2, 14, 44, 32, 14, tri("#e8ecf2"), lambda a, bb, w, h, base, r, s:
          mix(GLASS, WHITE, .2) if 4 <= bb <= 10 and a % 7 in (1, 2, 3, 4, 5) else hx("#e0763a") if bb == h - 1 else base)
    ox, oy = b.at(50, 10)
    c = b.iso.c
    for k in range(46):  # a lattice mast, red and white
        col = hx("#e04a3a") if (k // 6) % 2 else hx("#f4f4f4")
        c.p(ox - 1, oy - k, col); c.p(ox + 1, oy - k, col)
        if k % 3 == 0:
            c.p(ox, oy - k, hx("#3a4150"))
        b.iso.face[oy - k][ox - 1] = b.iso.face[oy - k][ox + 1] = 700
    c.ellipse(ox - 5, oy - 30, 3, 4, hx("#d8dee6")); c.p(ox - 5, oy - 30, hx("#3a4150"))  # a dish
    c.p(ox, oy - 47, hx("#ff4a3a"))
    _ = rng
    return b.iso.finish()


def big_screen():
    t = Thing(24)
    t.box(4, 7, 1, 1, 10, tri("#3a4150")); t.box(11, 7, 1, 1, 10, tri("#3a4150"))
    t.box(1, 7, 14, 2, 12, tri("#1d2230"), lambda a, b, w, h, base, r, s:
          ((hx("#3fe08a") if b < 2 + (a * 7) % 9 else hx("#24304a")) if s == "l" and 1 <= a < w - 1 and 1 <= b < h - 1 else base))
    return t.done()


# ---------------------------------------------------------------------------- people
def engineers():
    """Every villager as an engineer, in each team colour: chars/eng_<Name>_<colour>.png and a portrait."""
    (OUT / "chars").mkdir(exist_ok=True)
    (OUT / "portraits").mkdir(exist_ok=True)
    for name, (sk, hair, style) in VILLAGERS.items():
        for col in COLOR_NAMES:
            kw = dict(skin=SKINS[sk], hair_ramp=tuple(HAIRS[hair][1:4]), style=style, shirt=ITEM_COLORS[col],
                      pants="#2e3442", shoes="#e8ecf2", badge=True)
            charart.sheet(**kw).save(OUT / "chars" / f"eng_{name}_{col}.png")
            im = charart.portrait_from(**kw)
            px = im.load()
            for y in range(48):  # a cool backdrop instead of parchment
                for x in range(48):
                    if px[x, y][:3] in ((0xe9, 0xcf, 0x98), (0xe2, 0xc5, 0x8a)):
                        px[x, y] = hx("#cfd8e4") if y % 4 else hx("#c2ccda")
            im.save(OUT / "portraits" / f"eng_{name}_{col}.png")


def main():
    at = Atlas(1024)
    grounds = {
        "g_town": speckle("#5fae5a", ["#529e4f", "#72bf68"], .15),
        "g_farm": speckle("#a4acb6", ["#949ca7", "#b4bbc4"], .3),
        "g_beach": joints("#e4dfd4", "#cfc8b8"),
        "g_mountain": speckle("#4f9466", ["#45875b", "#5ea474"], .2),
        "path_town": speckle("#5a606b", ["#50565f", "#666c78"], .2),
        "path_dirt": joints("#bfc4cc", "#a6acb6"),
        "path_sand": joints("#d8d2c4", "#c4bcab"),
        "plaza": checker("#dde2ea", "#c9d0da", 3),
        "pier": grating,
        "field": solar,
        "water0": canal(0), "water1": canal(1),
    }
    for k, f in grounds.items():
        at.add(k, ground(f, 7))
    for kind, (_, _, floor) in LAB.items():
        at.add(f"floor_{kind}", ground(floor, 3))
    for i in range(2):
        at.add(f"tree_round{i}", tree_round(i))
    at.add("tree_pine", tree_column(0))
    at.add("tree_palm", tree_birch(0))
    at.add("bush", hedge(1))
    at.add("bush_flower", hedge(2, "#e0457b"))
    at.add("rock", chiller())
    at.add("rock_big", chiller(True))
    for i in range(3):
        at.add(f"house{i}", office(i))
    at.add("fountain", fountain())
    at.add("lamp", streetlight())
    for k in ("barrel", "crate", "umbrella", "sign"):
        at.add(k, small(k))
    for kind in LAB:
        at.add(f"wall_x_{kind}", wall(kind, "x"))
        at.add(f"wall_xw_{kind}", wall(kind, "x", window=True))
        at.add(f"wall_y_{kind}", wall(kind, "y"))
        at.add(f"wall_yw_{kind}", wall(kind, "y", window=True))
        at.add(f"low_x_{kind}", wall(kind, "x", low=True))
        at.add(f"low_y_{kind}", wall(kind, "y", low=True))
        for v in range(2):
            at.add(f"m_{kind}_{v}", machine(kind, v))
    at.add("b_library", data_centre())
    at.add("b_post", relay_tower())
    at.add("b_board", big_screen())
    looks = tech()
    assert set(looks) == set(LOOKS_KINDS), set(LOOKS_KINDS) ^ set(looks)
    for k, c in looks.items():
        at.add(f"mc_{k}", c)
    at.save(OUT / "campus.png", OUT / "campus.json")
    engineers()
    print("wrote", OUT / "campus.png", "and the engineers")


if __name__ == "__main__":
    main()
