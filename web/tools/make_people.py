#!/usr/bin/env python
"""Generate the people and the UI icons of SeedVille Workshops (web/codeworld.html).

    python web/tools/make_people.py      # writes web/assets/chars/, portraits/, ui.png (+ ui.json)

The town itself (tiles, workshops, machines, buildings) comes from kairoart.py.
"""

from __future__ import annotations

import charart
from pixel import CLEAR, COLOR_NAMES, ITEM_COLORS, OUT, WOOD, Atlas, C, hx, ramp


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
    make_chars()
    make_ui()
    print("people and UI written to", OUT)


if __name__ == "__main__":
    main()
