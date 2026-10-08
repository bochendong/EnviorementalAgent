"""Canvas memory: a fixed-size, multi-resolution picture of what the agent knows, rebuilt every step.

Instead of an ever-growing transcript, the model sees (``--context canvas``):

    the instructions, a CANVAS, and only the last few tool calls.

The canvas is drawn from the world as the agent has perceived it, at decreasing resolution:

    sharp     the place the agent is in, with every detail it has noticed (soils, jobs, categories)
    medium    the few places visited most recently: what is there, by name
    blurred   places visited longer ago: one line of counts
    map       places not visited yet (names only)

plus the recent events, the goal and status, and a NOTES section the agent rewrites itself with
``rewrite_notes`` (edited in place, never appended). Old detail is not lost: it is still in the
world, and the agent can go back and zoom in again (the world is the full-resolution memory).
Everything is cut to a character budget; when it is tight, older places are blurred first.
"""

from __future__ import annotations

NOTE_CHARS = 800
EVENTS = 6


class Canvas:
    def __init__(self, world, chars: int = 3000):
        self.w = world
        self.chars = chars
        self.notes = ""
        self.renders = 0
        self.rendered_chars = 0

    # ------------------------------------------------------------ notes (edited, not appended)
    def rewrite_notes(self, text: str) -> str:
        self.notes = (text or "").strip()[:NOTE_CHARS]
        return f"Notes rewritten ({len(self.notes)}/{NOTE_CHARS} characters)."

    # ------------------------------------------------------------ drawing
    def render(self) -> str:
        w = self.w
        if not hasattr(w, "visit_log"):  # other worlds: the plain views
            text = self._frame([w.view_world(), w.observe()])
        else:
            text = self._town()
        self.renders += 1
        self.rendered_chars += len(text)
        return text

    def _frame(self, body: list[str], n_events: int = EVENTS) -> str:
        events = [ev.line()[:140] for ev in self.w.events[-n_events:]] if n_events else []
        parts = ["CANVAS (your memory, redrawn every step; sharp where you are, blurrier further back in time)"]
        parts += body
        if events:
            parts.append("RECENT EVENTS:\n" + "\n".join("  " + e for e in events))
        parts.append("NOTES (yours; rewrite them with rewrite_notes):\n  " + (self.notes or "(empty)"))
        return "\n".join(parts)

    def _detail(self, o) -> str:
        """An object's label plus the fine details the agent has actually perceived."""
        w = self.w
        attrs = w.visible_attrs(o.id)  # the label already carries an item's category when it is visible
        extra = [f"{k}: {attrs[k]}" for k in ("soil", "job") if k in attrs]
        if o.kind == "villager" and o.id in w.seen_fine:
            extra.append(f"friendship {o.state['friendship']}")
        return w._label(o) + (" {" + "; ".join(extra) + "}" if extra else "")

    def _room(self, rid: str, level: int) -> str:
        w = self.w
        here = rid == w.agent_room
        objs = [o for o in w.room_objects(rid) if here or o.kind != "villager"]
        name = f"{rid} ({w.rooms[rid].name})"
        if level >= 2:
            return f"[{name}]" + (" <- you are here" if here else "") + "".join(
                "\n  " + self._detail(o) for o in objs)
        if level == 1:
            return f"[{name}] " + ", ".join(w._label(o).split(" -- ")[0] for o in objs)
        kinds: dict[str, int] = {}
        for o in objs:
            kinds[o.kind] = kinds.get(o.kind, 0) + 1
        return f"[{name}] " + (", ".join(f"{n} {k}" for k, n in kinds.items()) or "nothing noted")

    def _town(self) -> str:
        w = self.w
        order = []
        for rid in reversed(w.visit_log):
            if rid not in order:
                order.append(rid)
        if w.agent_room in order:
            order.remove(w.agent_room)
        order.insert(0, w.agent_room)
        unvisited = [rid for rid, r in w.rooms.items() if not r.visited]
        head = ["GOAL: " + w._goal_status(), w.status_line()]
        if getattr(w, "requests", None):
            head.append(w.board_text())
        tail = "MAP, not visited yet: " + (", ".join(unvisited) or "(none)")
        # resolution per place: 2 = sharp, 1 = names, 0 = counts. When over budget: blur the oldest places
        # first, then keep fewer recent events, then forget the oldest places, then cut.
        levels = [2] + [1] * min(3, len(order) - 1) + [0] * max(0, len(order) - 4)
        n_events = EVENTS
        while True:
            places = [self._room(rid, lv) for rid, lv in zip(order, levels)]
            text = self._frame(head + ["PLACES (most recent first):"] + places + [tail], n_events)
            if len(text) <= self.chars:
                return text
            demote = next((i for i in range(len(levels) - 1, 0, -1) if levels[i] > 0), None)
            if demote is not None:
                levels[demote] -= 1
            elif n_events > 2:
                n_events -= 2
            elif len(order) > 1:
                order.pop()
                levels.pop()
            else:
                return text[: self.chars]
