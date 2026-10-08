"""Pictures for vision-language agents: what the agent sees, and its memory canvas as images.

    render_view(world)        the agent's current view as a picture. Resolution follows the zoom level:
                              the town map is a small schematic, a place is a sheet of object cards,
                              an object is a large icon with the details the agent has perceived.
    text_pages(text)          a memory canvas (worldseeds.canvas) rendered into page images. Older
                              memories are drawn in smaller type, i.e. at lower resolution: forgetting
                              by blur (cf. optical context compression).
    canvas_content(world, text)  both, as OpenAI-style message content (input_text / input_image parts)

Only what the agent has perceived is drawn (labels and details come from the world's views).
Sprites come from web/assets; objects without a sprite (e.g. extra crops) get a lettered tile.
With a skin (worldseeds.skin) every label is translated and the farm's sprites give way to neutral
lab tiles (a compound is a flask, a plot a well coloured by its state, the watering can an incubator).
"""

from __future__ import annotations

import base64
import io
import json
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parents[1] / "web" / "assets"
INK, PAPER, WOOD, GOLD, GREEN, GREY = (58, 35, 18), (241, 217, 167), (122, 74, 38), (242, 182, 50), (106, 168, 79), (160, 150, 130)
MONO = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]


@lru_cache(maxsize=None)
def font(size: int):
    for p in MONO:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=1)
def _atlas():
    meta = json.loads((ASSETS / "objects.json").read_text())["frames"]
    return Image.open(ASSETS / "objects.png").convert("RGBA"), meta


@lru_cache(maxsize=512)
def _sprite(name: str):
    sheet, meta = _atlas()
    f = meta.get(name)
    if f is None:
        return None
    r = f["frame"]
    return sheet.crop((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]))


@lru_cache(maxsize=256)
def _portrait(name: str, color: str):
    p = ASSETS / "portraits" / f"{name}_{color}.png"
    return Image.open(p).convert("RGBA") if p.exists() else None


def _frame_name(o) -> str | None:
    k = o.kind
    if k == "item":
        return f"item_{o.name}_{o.color}"
    if k == "crop":
        return f"produce_{o.name}_{o.color}"
    if k == "seeds":
        return f"seeds_{o.fine['crop']}"
    if k == "tool":
        return f"can_{o.color}"
    if k == "trophy":
        return "trophy"
    if k == "decor":
        return "lamppost" if o.name == "lamppost" else f"{o.name}_{o.color}"
    if k == "board":
        return "board"
    if k == "shelf":
        return f"shelf_{o.fine['category']}"
    if k == "plot":
        st = o.state.get("status")
        return f"crop_{o.state['crop']}_{st}" if o.state.get("crop") and st != "empty" else "plot_wet" if o.state.get("watered") else "plot_dry"
    return None


STATUS_COLOR = {"empty": (200, 190, 170), "planted": (190, 210, 160), "growing": (106, 168, 79),
                "ripe": (242, 182, 50), "withered": (170, 60, 50), "dormant": (110, 140, 190)}
COLOR_RGB = {"red": (200, 60, 50), "blue": (60, 100, 200), "green": (70, 160, 80), "yellow": (230, 200, 60),
             "purple": (140, 80, 170), "orange": (230, 140, 50)}


def _lab_tile(o) -> Image.Image | None:
    """A neutral tile for the lab skin (no farm imagery): flask, sample tube, well, incubator."""
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = COLOR_RGB.get(o.color, (120, 160, 200))
    if o.kind == "crop":  # a compound: a flask
        d.rectangle((6, 1, 9, 6), outline=INK, fill=(230, 235, 240))
        d.polygon([(6, 6), (9, 6), (14, 14), (1, 14)], outline=INK, fill=col)
    elif o.kind == "seeds":  # samples: a tube
        d.rectangle((5, 1, 10, 14), outline=INK, fill=(230, 235, 240))
        d.rectangle((6, 8, 9, 13), fill=(120, 160, 200))
    elif o.kind == "plot":  # a well, coloured by its state
        d.ellipse((1, 1, 14, 14), outline=INK, fill=STATUS_COLOR.get(o.state.get("status"), (200, 190, 170)))
        if o.state.get("watered"):
            d.ellipse((5, 5, 10, 10), outline=(60, 100, 200))
    elif o.kind == "tool":  # an incubator
        d.rectangle((1, 3, 14, 14), outline=INK, fill=(210, 215, 220))
        d.rectangle((4, 6, 11, 11), outline=INK, fill=col)
    else:
        return None
    return img


def _icon(o, size: int, skin=None) -> Image.Image:
    img = _lab_tile(o) if skin is not None else None
    if img is not None:
        w, h = img.size
        k = max(1, size // max(w, h))
        return img.resize((w * k, h * k), Image.NEAREST)
    img = _portrait(o.name, o.color) if o.kind == "villager" else None
    if img is None:
        name = _frame_name(o)
        img = _sprite(name) if name else None
    if img is None:  # no sprite: a lettered tile
        img = Image.new("RGBA", (16, 16), PAPER + (255,))
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, 15, 15), outline=WOOD)
        name = skin.out(o.name) if skin is not None else o.name
        d.text((4, 2), (name or "?")[0].upper(), fill=INK, font=font(10))
    w, h = img.size
    k = max(1, size // max(w, h))
    return img.resize((w * k, h * k), Image.NEAREST)


def _wrap(text: str, width: int) -> list[str]:
    out = []
    for line in text.splitlines():
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = cut if cut > 0 else width
            out.append(line[:cut])
            line = "  " + line[cut:].lstrip()
        out.append(line)
    return out


# ---------------------------------------------------------------------------- the view
def render_view(world, skin=None) -> Image.Image:
    """The agent's current view; the deeper the zoom, the higher the resolution."""
    focus = list(getattr(world, "focus", []) or [])
    if not focus:
        return _map(world, skin)
    if len(focus) == 1:
        return _place(world, focus[0], skin)
    return _object(world, focus[-1], skin)


def _t(skin, text: str) -> str:
    return skin.out(text) if skin is not None else text


def _map(world, skin=None) -> Image.Image:
    rooms = list(world.rooms.items())
    cols = 5
    rows = (len(rooms) + cols - 1) // cols
    W, cw, ch = 520, 100, 34
    img = Image.new("RGB", (W, 24 + rows * (ch + 6) + 8), PAPER)
    d = ImageDraw.Draw(img)
    d.text((8, 4), _t(skin, "TOWN MAP"), fill=INK, font=font(12))
    for i, (rid, r) in enumerate(rooms):
        x, y = 6 + (i % cols) * (cw + 3), 24 + (i // cols) * (ch + 6)
        fill = GOLD if rid == world.agent_room else GREEN if r.visited else GREY
        d.rectangle((x, y, x + cw, y + ch), fill=fill, outline=WOOD, width=2)
        d.text((x + 4, y + 4), _t(skin, rid)[:14], fill=INK, font=font(10))
        d.text((x + 4, y + 18), ("here" if rid == world.agent_room else "visited" if r.visited else "?"), fill=INK,
               font=font(9))
    return img


def _place(world, rid: str, skin=None) -> Image.Image:
    here = rid == world.agent_room
    objs = [o for o in world.room_objects(rid) if here or o.kind != "villager"]
    cols, cw, ch = 4, 176, 92
    rows = max(1, (len(objs) + cols - 1) // cols)
    W = 16 + cols * (cw + 8)
    img = Image.new("RGB", (W, 64 + rows * (ch + 8)), PAPER)
    d = ImageDraw.Draw(img)
    title = _t(skin, f"{rid}: {world.rooms[rid].name}" + ("" if here else " (remembered)"))
    d.rectangle((0, 0, W, 30), fill=WOOD)
    d.text((10, 6), title, fill=PAPER, font=font(16))
    d.text((10, 36), _t(skin, world.status_line())[1:120], fill=INK, font=font(10))
    for i, o in enumerate(objs):
        x, y = 8 + (i % cols) * (cw + 8), 56 + (i // cols) * (ch + 8)
        d.rectangle((x, y, x + cw, y + ch), outline=WOOD, width=2)
        icon = _icon(o, 48, skin)
        img.paste(icon, (x + 6, y + 6), icon)
        attrs = world.visible_attrs(o.id)
        lines = [_t(skin, o.id), *_wrap(_t(skin, world._label(o)).split(" ", 1)[-1], 14)[:2]]
        lines += [_t(skin, f"{k}: {attrs[k]}") for k in ("soil", "job") if k in attrs]
        for j, ln in enumerate(lines[:5]):
            d.text((x + 60, y + 6 + j * 16), ln[:15], fill=INK, font=font(12 if j == 0 else 11))
    return img


def _object(world, oid: str, skin=None) -> Image.Image:
    o = world.objs[oid]
    W = 640
    text = _t(skin, world.view_obj(oid).rsplit("\n(", 1)[0])  # the object's details, without the status line
    lines = _wrap(text, 48)
    img = Image.new("RGB", (W, max(260, 40 + len(lines) * 22)), PAPER)
    d = ImageDraw.Draw(img)
    icon = _icon(o, 192, skin)
    img.paste(icon, (16, 24), icon)
    for j, ln in enumerate(lines):
        d.text((232, 24 + j * 22), ln, fill=INK, font=font(16))
    return img


# ---------------------------------------------------------------------------- text as pictures
def text_pages(text: str, width: int = 760, page_height: int = 1000) -> list[Image.Image]:
    """Render a canvas into page images; older places get smaller type (lower resolution)."""
    sized: list[tuple[str, int]] = []
    place = -1
    for line in text.splitlines():
        if line.startswith("["):
            place += 1
        if place < 0 or line.startswith(("RECENT EVENTS", "NOTES", "MAP")):
            size = 15
            if line.startswith(("RECENT EVENTS", "NOTES", "MAP")):
                place = 99  # past the places: normal size again
        elif place == 0:
            size = 15  # where you are: sharp
        elif place <= 3:
            size = 12  # recent places
        elif place < 99:
            size = 9  # long ago: blurred
        else:
            size = 13
        chars = max(20, int(width / (size * 0.6)))
        sized += [(ln, size) for ln in _wrap(line, chars)]
    pages, y, img, d = [], 0, None, None
    for ln, size in sized:
        if img is None or y + size + 4 > page_height:
            img = Image.new("RGB", (width, page_height), PAPER)
            d = ImageDraw.Draw(img)
            pages.append(img)
            y = 8
        d.text((8, y), ln, fill=INK, font=font(size))
        y += size + 4
    for k, p in enumerate(pages):  # trim the last page
        if k == len(pages) - 1:
            pages[k] = p.crop((0, 0, width, min(page_height, y + 8)))
    return pages


def data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def text_pages_content(text: str) -> list[dict]:
    parts = [{"type": "input_text", "text": "Your memory canvas, as images (older memories in smaller type):"}]
    parts += [{"type": "input_image", "image_url": data_url(p), "detail": "auto"} for p in text_pages(text)]
    return parts


def canvas_content(world, text: str, skin=None) -> list[dict]:
    """What a vision-language agent sees each step: its current view and its canvas, as pictures.
    ``text`` is the canvas as the agent reads it (already in the skin's words, if any)."""
    return ([{"type": "input_text", "text": "What you see now:"},
             {"type": "input_image", "image_url": data_url(render_view(world, skin)), "detail": "auto"}]
            + text_pages_content(text))
