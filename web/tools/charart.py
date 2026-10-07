"""Character sprites for SeedVille: hand-authored 16x32 templates, Stardew-like proportions.

Body templates are drawn without outlines; hair/hats are layered on, then a coloured
outline (a darkened version of the neighbouring pixel) is added around the silhouette.
Frames: 4 rows (down, left, right, up) x 4 columns (stand, step A, stand, step B).
"""

from __future__ import annotations

from PIL import Image

W, H = 16, 32

# palette slots: S/s/k skin light/mid/shadow, C/c/d shirt light/mid/dark, p/P pants, b/B shoes,
# e eye, r blush, m mouth
DOWN = [
    "................",
    "................",
    "................",
    "....SSSSSSSS....",
    "...SSSSSSSSSS...",
    "..SSSSSSSSSSSS..",
    "..SSSSSSSSSSSs..",
    "..SSSSSSSSSSSs..",
    ".sSSSSSSSSSSSss.",
    ".sSSSSSSSSSSSss.",
    "..SSSSSSSSSSss..",
    "...sSSSSSSSss...",
    "....ssssssss....",
    "......kkkk......",
    "....dCCCCCCd....",
    "...cCCCCCCCCc...",
    "..ccdCCCCCCdcc..",
    "..ccdCCCCCCdcc..",
    "..ccdCCCCCCdcc..",
    "..ccdcCCCCcdcc..",
    "..ss.cccccc.ss..",
    "..ss.dddddd.ss..",
    ".....pppppp.....",
    ".....ppPPpp.....",
    ".....pp..pp.....",
    ".....pp..pp.....",
    ".....pP..pP.....",
    ".....bb..bb.....",
    "....bbB..bBb....",
    "................",
    "................",
    "................",
]
UP = [row for row in DOWN]
UP[14] = "....cCCCCCCc...."
UP[19] = "..ccdcccccdcc..."[:16]
UP[19] = "..ccdCCCCCCdcc.."

LEFT = [
    "................",
    "................",
    "................",
    ".....SSSSSSS....",
    "....SSSSSSSSS...",
    "...SSSSSSSSSSS..",
    "...SSSSSSSSSSs..",
    "..SSSSSSSSSSSs..",
    "..SSSSSSSSSSss..",
    ".SSSSSSSSSSSss..",
    "..SSSSSSSSsss...",
    "..sSSSSSSSsss...",
    "....sssssss.....",
    "......kkk.......",
    ".....dCCCd......",
    ".....CCCCCc.....",
    ".....CCCCCc.....",
    ".....CccCCc.....",
    ".....CccCCd.....",
    ".....CccCCd.....",
    ".....dsscdd.....",
    ".....dssddd.....",
    "......pppp......",
    "......pppp......",
    "......pPpp......",
    "......pPpp......",
    "......pPpp......",
    ".....bbbbb......",
    ".....bbbBB......",
    "................",
    "................",
    "................",
]
# side walk: legs apart
LEFT_STEP_LEGS = [
    "......pppp......",
    "......pppp......",
    ".....ppPppp.....",
    "....pp...pp.....",
    "....pP....pP....",
    "...bbb....bbb...",
    "...bbB....bbB...",
]


def _hx(s):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def ramp3(base, cool="#2b2440", warm="#fff3c4"):
    b = _hx(base)
    return _mix(b, _hx(cool), .38), b, _mix(b, _hx(warm), .28)


class Sprite:
    def __init__(self):
        self.px = [[None] * W for _ in range(H)]

    def put(self, x, y, c):
        if 0 <= x < W and 0 <= y < H and c is not None:
            self.px[y][x] = c

    def get(self, x, y):
        return self.px[y][x] if 0 <= x < W and 0 <= y < H else None

    def stamp(self, rows, pal, dx=0, dy=0, only_rows=None):
        for y, row in enumerate(rows):
            if only_rows and y not in only_rows:
                continue
            for x, ch in enumerate(row):
                if ch != "." and ch in pal:
                    self.put(x + dx, y + dy, pal[ch])

    def clear_rows(self, y0, y1):
        for y in range(y0, y1 + 1):
            self.px[y] = [None] * W

    def outline(self):
        src = [r[:] for r in self.px]
        for y in range(H):
            for x in range(W):
                if src[y][x] is not None:
                    continue
                nb = [src[y + dy][x + dx] for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1))
                      if 0 <= x + dx < W and 0 <= y + dy < H and src[y + dy][x + dx] is not None]
                if nb:
                    c = nb[0]
                    self.px[y][x] = _mix(c, _hx("#1e120c"), .72)

    def image(self) -> Image.Image:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for y in range(H):
            for x in range(W):
                if self.px[y][x] is not None:
                    im.putpixel((x, y), self.px[y][x])
        return im

    def flipped(self) -> "Sprite":
        s = Sprite()
        s.px = [list(reversed(r)) for r in self.px]
        return s


# --------------------------------------------------------------------------- hair
def _hair_pixels(style: str, direction: str) -> set[tuple[int, int]]:
    """Pixels covered by hair for a style and facing (before shading)."""
    P = set()

    def box(x0, y0, x1, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                P.add((x, y))

    if style in ("bald",):
        if direction == "up":
            box(2, 7, 13, 10)
        elif direction == "down":
            box(2, 6, 3, 9); box(12, 6, 13, 9)
        else:
            box(10, 7, 12, 9)
        return P
    if direction == "down":
        box(4, 2, 11, 2); box(3, 3, 12, 3); box(2, 4, 13, 5)
        fringe = {2: 7, 3: 7, 4: 6, 5: 6, 6: 5, 7: 6, 8: 6, 9: 5, 10: 6, 11: 6, 12: 7, 13: 7}
        for x, yb in fringe.items():
            box(x, 6, x, yb) if yb >= 6 else None
        box(2, 6, 2, 9); box(13, 6, 13, 9)  # sideburns
        if style == "long":
            box(1, 6, 2, 17); box(13, 6, 14, 17); box(3, 14, 3, 16); box(12, 14, 12, 16)
        if style == "bun":
            box(6, 0, 9, 1); box(5, 1, 10, 1)
        if style == "spiky":
            for x in (3, 5, 7, 9, 11):
                box(x, 1, x, 1)
            for x in (4, 8, 12):
                box(x, 0, x, 1)
        if style == "ponytail":
            box(1, 7, 1, 9); box(14, 7, 14, 9)
    elif direction == "left":
        box(5, 2, 11, 2); box(4, 3, 12, 3); box(3, 4, 13, 5)
        box(6, 6, 13, 8); box(8, 9, 13, 10); box(9, 11, 12, 11)
        box(3, 6, 4, 6); box(2, 6, 2, 6)
        P.discard((9, 8)); P.discard((9, 9))  # ear shows
        if style == "long":
            box(9, 9, 13, 17); box(8, 12, 12, 17)
        if style == "bun":
            box(9, 0, 12, 2); box(8, 1, 13, 1)
        if style == "ponytail":
            box(12, 6, 14, 8); box(13, 9, 14, 14); box(14, 15, 14, 15)
        if style == "spiky":
            for x in (4, 6, 8, 10, 12):
                box(x, 1, x, 1)
            box(3, 2, 3, 2); box(5, 0, 5, 0); box(9, 0, 9, 0)
    else:  # up: back of head
        box(4, 2, 11, 2); box(3, 3, 12, 3); box(2, 4, 13, 11); box(3, 12, 12, 12)
        if style == "long":
            box(2, 12, 13, 17)
        if style == "bun":
            box(6, 0, 9, 1); box(5, 1, 10, 1)
        if style == "ponytail":
            box(7, 13, 8, 18)
        if style == "spiky":
            for x in (3, 5, 7, 9, 11):
                box(x, 1, x, 1)
    return P


def _shade_hair(spr: Sprite, pixels, ramp):
    dk, md, lt = ramp
    for (x, y) in pixels:
        below = (x, y + 1) in pixels
        c = md
        if not below:
            c = dk
        elif y <= 3 and 3 <= x <= 8:
            c = lt
        elif x >= 12 and y > 3:
            c = dk
        spr.put(x, y, c)
    # a highlight streak
    for (x, y) in ((5, 3), (6, 3), (7, 4), (4, 4)):
        if (x, y) in pixels:
            spr.put(x, y, lt)


def _face(spr: Sprite, direction: str, skin, eye="#2a1810"):
    k = skin[0]
    if direction == "down":
        for x in (5, 10):
            spr.put(x, 8, _hx(eye)); spr.put(x, 9, _hx(eye))
        spr.put(4, 10, _hx("#f09a88")); spr.put(11, 10, _hx("#f09a88"))
        spr.put(7, 11, k); spr.put(8, 11, k)
    elif direction == "left":
        spr.put(4, 8, _hx(eye)); spr.put(4, 9, _hx(eye))
        spr.put(3, 10, _hx("#f09a88"))
        spr.put(3, 11, k)
        spr.put(9, 8, k); spr.put(9, 9, skin[1])  # ear


def _beard(spr, direction, ramp):
    dk, md, lt = ramp
    if direction == "down":
        for y in range(10, 13):
            for x in range(3, 13):
                if spr.get(x, y) is not None:
                    spr.put(x, y, md if y < 12 else dk)
        spr.put(7, 10, _hx("#7a3a2a")); spr.put(8, 10, _hx("#7a3a2a"))
    elif direction == "left":
        for y in range(10, 13):
            for x in range(2, 9):
                if spr.get(x, y) is not None:
                    spr.put(x, y, md if y < 12 else dk)


def _mustache(spr, direction, ramp):
    if direction == "down":
        for x in (5, 6, 9, 10, 7, 8):
            spr.put(x, 10, ramp[1])
    elif direction == "left":
        for x in (2, 3, 4):
            spr.put(x, 10, ramp[1])


def _hat(spr, direction):
    straw = ramp3("#e8c96a")
    band = _hx("#b8452f")
    if direction == "up":
        rows = {1: (4, 11), 2: (3, 12), 3: (3, 12), 4: (2, 13), 5: (0, 15)}
    elif direction == "down":
        rows = {1: (4, 11), 2: (3, 12), 3: (3, 12), 4: (3, 12), 5: (0, 15), 6: (1, 14)}
    else:
        rows = {1: (5, 11), 2: (4, 12), 3: (4, 12), 4: (4, 12), 5: (0, 15), 6: (1, 14)}
    for y, (x0, x1) in rows.items():
        for x in range(x0, x1 + 1):
            c = straw[2] if y <= 2 and x < 8 else straw[1]
            if y >= 5:
                c = straw[0] if y == 6 else straw[1]
            spr.put(x, y, c)
    for x in range(rows[4][0], rows[4][1] + 1):
        spr.put(x, 4, band)


def _overalls(spr, direction):
    blue = ramp3("#3f63b0")
    for y in range(17, 22):
        for x in range(4, 12):
            if spr.get(x, y) is not None and (direction != "left" or 5 <= x <= 10):
                spr.put(x, y, blue[1] if y > 17 else blue[2])
    if direction in ("down", "up"):
        for y in (14, 15, 16):
            spr.put(5, y, blue[1]); spr.put(10, y, blue[1])
        spr.put(5, 17, _hx("#f2b632")); spr.put(10, 17, _hx("#f2b632"))


def frame(direction, step, skin, hair_ramp, style, shirt, pants="#4a4f6e", shoes="#4a2c1a",
          hat=False, overalls=False):
    """direction: down|left|up (right = mirrored left); step: 0 stand, 1 step A, 2 step B."""
    sk = skin
    sh = ramp3(shirt)
    pn = ramp3(pants)
    so = ramp3(shoes)
    pal = {"S": sk[2], "s": sk[1], "k": sk[0], "C": sh[2], "c": sh[1], "d": sh[0],
           "p": pn[1], "P": pn[0], "b": so[1], "B": so[0]}
    rows = {"down": DOWN, "up": UP, "left": LEFT}[direction]
    spr = Sprite()
    spr.stamp(rows, pal)
    if step:
        if direction == "left":
            spr.clear_rows(22, 28)
            spr.stamp(LEFT_STEP_LEGS, pal, dy=22 - 0, only_rows=None) if False else None
            for i, row in enumerate(LEFT_STEP_LEGS):
                for x, ch in enumerate(row):
                    if ch != ".":
                        spr.put(x, 22 + i, pal[ch])
            # swing the visible arm
            hand = (6, 20) if step == 1 else (8, 20)
            spr.put(6, 20, sh[0]); spr.put(7, 20, sh[0]); spr.put(*hand, sk[1]); spr.put(hand[0], 21, sk[1])
        else:
            lift = 5 if step == 1 else 9  # which leg (left col) lifts
            for x in (lift, lift + 1):
                col = [spr.get(x, y) for y in range(22, 29)]
                for i, y in enumerate(range(22, 29)):
                    spr.px[y][x] = None
                for i, y in enumerate(range(22, 28)):
                    spr.px[y][x] = col[i] if i < 4 else col[i + 1]
            # arms swing opposite to legs
            arm_dn, arm_up = ((2, 3), (12, 13)) if step == 1 else ((12, 13), (2, 3))
            for x in arm_dn:
                for y in range(21, 14, -1):
                    spr.px[y][x] = spr.px[y - 1][x]
            for x in arm_up:
                for y in range(15, 22):
                    spr.px[y][x] = spr.px[y + 1][x]
                spr.px[21][x] = None
    if overalls:
        _overalls(spr, direction)
    if direction != "up":
        _face(spr, direction, sk)
    hp = _hair_pixels(style if not hat else "short", direction)
    if hat and direction != "up":
        hp = {(x, y) for (x, y) in hp if y >= 6}
    _shade_hair(spr, hp, hair_ramp)
    if style == "beard" and direction != "up":
        _beard(spr, direction, hair_ramp)
    if style == "bald" and direction != "up":
        _mustache(spr, direction, hair_ramp)
    if hat:
        _hat(spr, direction)
    spr.outline()
    return spr


def sheet(**kw) -> Image.Image:
    im = Image.new("RGBA", (W * 4, H * 4), (0, 0, 0, 0))
    for r, d in enumerate(("down", "left", "right", "up")):
        for f, step in enumerate((0, 1, 0, 2)):
            spr = frame("left" if d == "right" else d, step, **kw)
            if d == "right":
                spr = spr.flipped()
            im.alpha_composite(spr.image(), (f * W, r * H))
    return im


def portrait_from(**kw) -> Image.Image:
    """48x48 portrait: the front-facing sprite's head and shoulders, scaled 3x on a backdrop."""
    spr = frame("down", 0, **kw).image().crop((0, 0, 16, 16))
    bg = Image.new("RGBA", (48, 48), _hx("#e9cf98"))
    for y in range(0, 48, 4):
        for x in range(48):
            bg.putpixel((x, y), _hx("#e2c58a"))
    big = spr.resize((48, 48), Image.NEAREST)
    bg.alpha_composite(big, (0, 2))
    return bg
