"""Shared pixel-art core: colour ramps, a tiny canvas with shading helpers, and an atlas packer."""

from __future__ import annotations

import json
import math

from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "assets"
T = 16
SEASONS = ["spring", "summer", "fall", "winter"]


# ============================================================================ colour
def hx(s: str) -> tuple:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)


def ramp(*cs):
    return [hx(c) for c in cs]


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def shade(c, f):
    return tuple(max(0, min(255, int(c[i] * f))) for i in range(3)) + (255,)


def hue_ramp(base: str):
    """5-step ramp from one base colour: darker hues lean cool, lighter lean warm (pixel-art rule)."""
    b = hx(base)
    cool, warm = hx("#2b2440"), hx("#fff3c4")
    return [mix(b, cool, .55), mix(b, cool, .3), b, mix(b, warm, .3), mix(b, warm, .6)]


GRASS = {
    "spring": ramp("#1f4524", "#2f6a30", "#4a8f3a", "#6eb048", "#a6d264"),
    "summer": ramp("#1b4020", "#285f26", "#3f862c", "#5fa834", "#8fcb4a"),
    "fall": ramp("#3f3520", "#6a5726", "#8f7a2e", "#b39a3c", "#d6bd5a"),
    "winter": ramp("#6e7f9c", "#97a8c2", "#c3d1e2", "#e2eaf3", "#fbfdff"),
}
DIRT = ramp("#4a2e1c", "#6b4429", "#8c5d37", "#ad7a4a", "#cf9d66")
STONE = ramp("#3d3b4a", "#5d5b6c", "#807e8f", "#a6a4b2", "#cac8d2")
WATER = ramp("#16305c", "#1f4c8a", "#2f6cb4", "#5094d4", "#a3d2f0")
WOOD = ramp("#2e1a10", "#4d2d1a", "#6e4428", "#925d37", "#b77d4d")
SOIL = ramp("#2c1a10", "#432818", "#5c3a22", "#764d2e")
SOIL_WET = ramp("#1e120b", "#2d1b10", "#3d2516", "#4f311d")
PLASTER = ramp("#7c6248", "#a88a66", "#cdb08a", "#e8d2ab", "#f7ead0")
OUTLINE = hx("#26160e")
CLEAR = (0, 0, 0, 0)

ITEM_COLORS = {"red": "#cf3f38", "blue": "#3c6fd8", "green": "#3f9e48", "yellow": "#e9c43c",
               "purple": "#8b52c8", "orange": "#e8842c", "gold": "#f2b632"}
COLOR_NAMES = ["red", "blue", "green", "yellow", "purple", "orange"]
ROOF = {"red": "#b8433a", "blue": "#3f6ab8", "teal": "#2f8a8a", "purple": "#7d4fb0", "green": "#4f8f3a",
        "orange": "#d17a2e"}


# ============================================================================ canvas
class C:
    def __init__(self, w, h):
        self.im = Image.new("RGBA", (w, h), CLEAR)
        self.px = self.im.load()
        self.w, self.h = w, h

    def p(self, x, y, c):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h and c is not None:
            if len(c) == 4 and c[3] < 255:
                o = self.px[x, y]
                a = c[3] / 255
                c = tuple(int(o[i] * (1 - a) + c[i] * a) for i in range(3)) + (max(o[3], c[3]),)
            self.px[x, y] = c

    def get(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.px[x, y]
        return CLEAR

    def rect(self, x, y, w, h, c):
        for j in range(int(h)):
            for i in range(int(w)):
                self.p(x + i, y + j, c)

    def hline(self, x, y, w, c):
        self.rect(x, y, w, 1, c)

    def vline(self, x, y, h, c):
        self.rect(x, y, 1, h, c)

    def ellipse(self, cx, cy, rx, ry, c):
        for j in range(-int(ry) - 1, int(ry) + 2):
            for i in range(-int(rx) - 1, int(rx) + 2):
                if (i / max(rx, .5)) ** 2 + (j / max(ry, .5)) ** 2 <= 1.0:
                    self.p(cx + i, cy + j, c)

    def blob(self, cx, cy, r, ramp_, light=(-1, -1), rng=None, dither=True):
        """Shaded sphere-ish blob, lit from ``light`` direction."""
        lx, ly = light
        n = math.hypot(lx, ly) or 1
        lx, ly = lx / n, ly / n
        for j in range(-r - 1, r + 2):
            for i in range(-r - 1, r + 2):
                d = math.hypot(i, j)
                if d > r + .3:
                    continue
                k = (-(i * lx + j * ly) / max(r, 1)) * .6 + (1 - d / (r + .5)) * .5  # -1..1-ish
                v = 1.6 + k * 2.2
                if dither and rng is not None:
                    v += rng.uniform(-.35, .35)
                idx = max(0, min(len(ramp_) - 1, int(round(v))))
                self.p(cx + i, cy + j, ramp_[idx])

    def outline(self, color=OUTLINE, sides="all"):
        """Add a 1px outline around opaque pixels (pixel-art sprite convention)."""
        src = self.im.copy().load()
        for y in range(self.h):
            for x in range(self.w):
                if src[x, y][3] > 0:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.w and 0 <= ny < self.h and src[nx, ny][3] > 200:
                        self.px[x, y] = color
                        break

    def paste(self, other: "C", x, y):
        self.im.alpha_composite(other.im, (int(x), int(y)))
        self.px = self.im.load()

    def flip(self) -> "C":
        c = C(self.w, self.h)
        c.im = self.im.transpose(Image.FLIP_LEFT_RIGHT)
        c.px = c.im.load()
        return c


class Atlas:
    """Simple shelf packer -> PNG + Phaser JSON-hash atlas."""

    def __init__(self, width=512):
        self.frames: list[tuple[str, C]] = []
        self.width = width

    def add(self, name, c: C):
        self.frames.append((name, c))

    def save(self, png: Path, js: Path):
        x = y = shelf = 0
        placed = []
        for name, c in self.frames:
            if x + c.w > self.width:
                x, y, shelf = 0, y + shelf + 1, 0
            placed.append((name, c, x, y))
            x += c.w + 1
            shelf = max(shelf, c.h)
        H = y + shelf + 1
        im = Image.new("RGBA", (self.width, H), CLEAR)
        frames = {}
        for name, c, px, py in placed:
            im.alpha_composite(c.im, (px, py))
            frames[name] = {"frame": {"x": px, "y": py, "w": c.w, "h": c.h}, "rotated": False, "trimmed": False,
                            "spriteSourceSize": {"x": 0, "y": 0, "w": c.w, "h": c.h},
                            "sourceSize": {"w": c.w, "h": c.h}}
        im.save(png)
        js.write_text(json.dumps({"frames": frames, "meta": {"image": png.name, "size": {"w": self.width, "h": H},
                                                              "scale": "1"}}))


