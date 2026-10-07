"""Trees and bushes for SeedVille.

Canopies are built from overlapping leaf clumps with scalloped edges. Each pixel is lit
from the top-left using its clump's sphere normal, darkened toward the canopy bottom and
under the clump in front of it, and quantised to a 5-tone ramp with ordered (Bayer)
dithering. Leaf-tuft marks add texture, and a coloured outline closes the silhouette.
Winter oaks are bare: recursive branches with snow on their upper edges.
"""

from __future__ import annotations

import math
import random

from PIL import Image

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def hx(s):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def ramp5(base, cool="#1b2238", warm="#fff1b8"):
    b = hx(base)
    return [mix(b, hx(cool), .62), mix(b, hx(cool), .34), b, mix(b, hx(warm), .28), mix(b, hx(warm), .55)]


BARK = [hx("#2b1a12"), hx("#47291a"), hx("#663d25"), hx("#875632"), hx("#a8744a")]
LEAVES = {
    "spring": ["#5fae4a", "#6cbc52"],
    "summer": ["#3f8f38", "#357f34"],
    "fall": ["#d9772e", "#c9542a", "#e0a536"],
    "winter": ["#4f6f60"],
}


class Img:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = {}

    def put(self, x, y, c):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[(x, y)] = c

    def get(self, x, y):
        return self.px.get((x, y))

    def outline(self, dark=hx("#14100c"), strength=.7):
        add = {}
        for (x, y), c in self.px.items():
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, y + dy)
                if n not in self.px and 0 <= n[0] < self.w and 0 <= n[1] < self.h:
                    add.setdefault(n, mix(c, dark, strength))
        self.px.update(add)

    def image(self, shadow=None) -> Image.Image:
        im = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        if shadow:
            cx, cy, rx, ry = shadow
            for y in range(self.h):
                for x in range(self.w):
                    d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
                    if d <= 1:
                        im.putpixel((x, y), (20, 30, 20, int(90 * (1 - d * .6))))
        for (x, y), c in self.px.items():
            im.putpixel((x, y), c)
        return im


def dither(v, x, y, n=5):
    base = math.floor(v)
    frac = v - base
    if frac < .38:
        step = 0
    elif frac > .62:
        step = 1
    else:  # dither only in a narrow band between two tones
        step = 1 if (frac - .38) / .24 > (BAYER[y % 4][x % 4] + .5) / 16 else 0
    return max(0, min(n - 1, base + step))


def canopy(img: Img, clumps, ramps, rng, light=(-.62, -.78), top=None, bottom=None):
    """clumps: list of (cx, cy, r, ramp_index), drawn back to front."""
    owner = {}
    for i, (cx, cy, r, _) in enumerate(clumps):
        ph = rng.uniform(0, 6.28)
        lobes = rng.choice((5, 6, 7))
        R = int(r + 2)
        for y in range(int(cy - R), int(cy + R) + 1):
            for x in range(int(cx - R), int(cx + R) + 1):
                a = math.atan2(y - cy, x - cx)
                rr = r * (1 + .11 * math.sin(a * lobes + ph)) + .3
                if math.hypot(x - cx, y - cy) <= rr:
                    owner[(x, y)] = i
    ys = [y for (_, y) in owner]
    top = min(ys) if top is None else top
    bottom = max(ys) if bottom is None else bottom
    lx, ly = light
    for (x, y), i in owner.items():
        cx, cy, r, ri = clumps[i]
        nx, ny = (x - cx) / r, (y - cy) / r
        nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
        lit = -(nx * lx + ny * ly) * .9 + nz * .55
        lit -= (y - top) / max(1, bottom - top) * .55
        # contact shadow under a clump that sits in front
        for d in (1, 2, 3):
            j = owner.get((x, y - d))
            if j is not None and j > i:
                lit -= .55 / d
                break
        v = 2.0 + lit * 1.7
        img.put(x, y, ramps[ri][dither(v, x, y)])
    # leaf tufts: small bright strokes on lit areas, dark pockets in shade
    keys = list(owner)
    for _ in range(len(keys) // 9):
        x, y = rng.choice(keys)
        c = img.get(x, y)
        ri = clumps[owner[(x, y)]][3]
        R = ramps[ri]
        idx = R.index(c) if c in R else 2
        if idx >= 3:
            img.put(x, y, R[4]); img.put(x + 1, y - 1, R[4]) if (x + 1, y - 1) in owner else None
        elif idx <= 1:
            img.put(x, y, R[0]); img.put(x - 1, y + 1, R[0]) if (x - 1, y + 1) in owner else None
        else:
            img.put(x, y, R[3])
    return owner


def trunk(img: Img, cx, y_top, y_bot, w_top=6, w_bot=9, roots=True, rng=None):
    rng = rng or random.Random(0)
    for y in range(y_top, y_bot + 1):
        t = (y - y_top) / max(1, y_bot - y_top)
        w = w_top + (w_bot - w_top) * t
        x0, x1 = int(round(cx - w / 2)), int(round(cx + w / 2))
        for x in range(x0, x1):
            u = (x - x0) / max(1, x1 - x0 - 1)
            idx = 3 if u < .25 else 2 if u < .6 else 1
            if u < .12:
                idx = 4
            img.put(x, y, BARK[idx])
    for _ in range((y_bot - y_top) // 2):  # bark grooves
        x = cx + rng.randint(-2, 2)
        y = rng.randint(y_top, y_bot - 2)
        img.put(x, y, BARK[1]); img.put(x, y + 1, BARK[1])
    if roots:
        yb = y_bot
        for side in (-1, 1):
            for k in range(4):
                x = cx + side * (w_bot / 2 + k)
                img.put(x, yb - (1 if k < 2 else 0), BARK[2 if side < 0 else 1])
                img.put(x, yb, BARK[2 if side < 0 else 1])


def oak(season: str, seed: int) -> Image.Image:
    rng = random.Random(seed * 31 + 7)
    img = Img(48, 64)
    if season == "winter":
        return bare_tree(seed)
    trunk(img, 24, 34, 58, 6, 9, rng=rng)
    # a fork that disappears into the canopy
    for k in range(6):
        img.put(21 - k // 2, 36 - k, BARK[2]); img.put(27 + k // 2, 36 - k, BARK[1])
    bases = LEAVES[season]
    ramps = [ramp5(b) for b in bases]
    pick = lambda: rng.randrange(len(ramps))
    jitter = lambda v: v + rng.randint(-1, 1)
    clumps = [
        (jitter(14), jitter(20), 9, pick()), (jitter(34), jitter(19), 9, pick()), (jitter(24), jitter(11), 10, pick()),
        (jitter(9), jitter(29), 8, pick()), (jitter(39), jitter(28), 8, pick()),
        (jitter(24), jitter(23), 12, pick()),
        (jitter(15), jitter(33), 9, pick()), (jitter(33), jitter(33), 9, pick()), (jitter(24), jitter(36), 8, pick()),
    ]
    canopy(img, clumps, ramps, rng)
    if season == "spring":
        keys = [k for k in img.px if k[1] < 38]
        for _ in range(22):
            x, y = rng.choice(keys)
            for dx, dy, c in ((0, 0, "#fff3f7"), (1, 0, "#f4a6c8"), (-1, 0, "#f4a6c8"), (0, 1, "#e07aa4")):
                if (x + dx, y + dy) in img.px:
                    img.put(x + dx, y + dy, hx(c))
    if season == "summer" and seed % 3 == 1:
        keys = [k for k in img.px if 14 < k[1] < 38]
        for _ in range(8):
            x, y = rng.choice(keys)
            img.put(x, y, hx("#c0392b")); img.put(x + 1, y, hx("#a8231c")); img.put(x, y + 1, hx("#a8231c"))
            img.put(x, y - 1, hx("#ff8a7a"))
    img.outline(hx("#13180f"), .62)
    out = img.image(shadow=(24, 59, 17, 4))
    if season == "fall":  # a few fallen leaves on the ground
        for _ in range(7):
            x, y = 24 + rng.randint(-16, 16), 59 + rng.randint(-2, 3)
            out.putpixel((x, y), hx(rng.choice(["#d9772e", "#c9542a", "#e0a536"])))
    return out


def bare_tree(seed: int) -> Image.Image:
    rng = random.Random(seed * 17 + 3)
    img = Img(48, 64)
    trunk(img, 24, 30, 58, 5, 9, rng=rng)
    snow = hx("#ffffff")

    def branch(x, y, ang, length, width, depth):
        if depth == 0 or length < 2:
            return
        ex, ey = x + math.cos(ang) * length, y + math.sin(ang) * length
        steps = int(max(abs(ex - x), abs(ey - y))) + 1
        for s in range(steps + 1):
            px = x + (ex - x) * s / steps
            py = y + (ey - y) * s / steps
            for w in range(int(width)):
                img.put(px + w - width // 2, py, BARK[2 if w == 0 else 1])
            if math.sin(ang) < .2 and rng.random() < .7:  # snow on the top of near-horizontal twigs
                img.put(px, py - 1, snow)
        spread = rng.uniform(.35, .6)
        for da in (-spread, spread * rng.uniform(.6, 1.1)):
            branch(ex, ey, ang + da, length * rng.uniform(.62, .78), max(1, width - 1), depth - 1)

    for ang, ln in ((-1.57, 12), (-2.25, 11), (-.9, 11), (-2.75, 8), (-.4, 8)):
        branch(24, 32, ang + rng.uniform(-.1, .1), ln, 3, 4)
    img.outline(hx("#1a120c"), .55)
    out = img.image(shadow=(24, 59, 14, 3))
    for x in range(14, 35):  # snow drift at the base
        for y in range(57, 60):
            if ((x - 24) / 10) ** 2 + ((y - 59) / 2.2) ** 2 <= 1:
                out.putpixel((x, y), hx("#f6fbff") if y < 59 else hx("#dde8f2"))
    return out


def pine(season: str, seed: int) -> Image.Image:
    rng = random.Random(seed * 13 + 5)
    img = Img(32, 48)
    trunk(img, 16, 37, 45, 3, 4, roots=False, rng=rng)
    base = {"spring": "#2f7a4a", "summer": "#2a6b40", "fall": "#356a40", "winter": "#3a5f50"}[season]
    R = ramp5(base)
    tiers = [(3, 4), (8, 7), (13, 9), (18, 11), (23, 13), (28, 14)]  # (top y, half width at bottom)
    for ti, (ty, hw) in enumerate(tiers):
        h = 8
        for j in range(h):
            w = max(1, int(hw * (j + 1) / h))
            yy = ty + j
            for x in range(16 - w, 16 + w + 1):
                if j == h - 1 and (x % 3 == 0):
                    continue  # jagged lower edge
                u = (x - (16 - w)) / max(1, 2 * w)  # 0 left .. 1 right
                v = 3.3 - u * 2.6 - j / h * .6 + (.4 if ti < 2 else 0)
                img.put(x, yy, R[dither(v, x, yy)])
            img.put(16 - w - 1, yy + 1, R[1]) if j == h - 1 else None
            img.put(16 + w + 1, yy + 1, R[0]) if j == h - 1 else None
        if season == "winter":
            for j in range(2):
                w = max(1, int(hw * (j + 1) / h))
                for x in range(16 - w, 16 + w // 2 + 1):
                    if rng.random() < .85:
                        img.put(x, ty + j + 1, hx("#ffffff") if j == 0 else hx("#e6eef6"))
    img.put(16, 2, R[3])
    img.outline(hx("#101810"), .6)
    return img.image(shadow=(16, 45, 10, 3))


def bush(season: str, seed: int) -> Image.Image:
    rng = random.Random(seed * 7 + 1)
    img = Img(20, 18)
    base = LEAVES[season][0] if season != "winter" else "#5f7a6c"
    ramps = [ramp5(base)]
    canopy(img, [(6, 10, 5, 0), (14, 10, 5, 0), (10, 7, 6, 0), (10, 11, 6, 0)], ramps, rng)
    if season == "summer":
        for (x, y) in ((6, 8), (12, 6), (14, 11), (8, 12), (10, 9)):
            img.put(x, y, hx("#3c5fd8")); img.put(x, y - 1, hx("#a9c4ff"))
    if season == "spring":
        for (x, y) in ((7, 7), (13, 8), (10, 11)):
            img.put(x, y, hx("#fff3f7")); img.put(x + 1, y, hx("#f4a6c8"))
    if season == "winter":
        for x in range(4, 16):
            if (x, 2) in img.px or (x, 3) in img.px or rng.random() < .3:
                for y in range(0, 18):
                    if (x, y) in img.px:
                        img.put(x, y, hx("#ffffff")); img.put(x, y + 1, hx("#e6eef6"))
                        break
    img.outline(hx("#13180f"), .6)
    return img.image(shadow=(10, 16, 9, 2))
