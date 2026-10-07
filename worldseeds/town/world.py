"""SeedVille world: a lazily grown, zoomable, persistent town with its own clock.

Levels:  town map -> location -> object -> component
Quest:   each goal is a trophy held by a quest villager, handed over (``talk``)
         once that villager's requirements are met:
           gifting  -> friendship 2 (two LIKED gifts; liking follows hidden laws)
           farming  -> one fresh crop (needs the right seed for the season and the
                       right soil, watering, and two nights of growth)
           shop     -> needed goods must be bought with just enough coins
           schedule -> villagers move: home mornings/evenings, a law-given place at midday
Time:    every valid action takes one tick; a day has 12 ticks (morning, midday,
         evening). ``sleep`` (at the farm) or running out of ticks ends the day; crops
         grow overnight. The world changes even when the agent does nothing (section 9's
         exogenous dynamics), and everything persists across goals.
"""

from __future__ import annotations

import copy
import random

from ..world import Event, Obj, Room, _h
from .seed import (
    CATEGORIES,
    COLORS,
    CROPS,
    FARMING,
    GIFTING,
    ITEM_NAMES,
    JOBS,
    WORKPLACE,
    SCHEDULE,
    SHOP,
    SOILS,
    TownSeed,
)

TICKS_PER_DAY = 12
VILLAGER_NAMES = ["Rosa", "Tomas", "Ivy", "Bram", "Lena", "Otto", "Mira", "Finn", "Hana", "Leo", "Clara", "Abe"]
JOB_LOOK = {"fisher": "rubber boots smelling of the sea", "doctor": "a stethoscope", "librarian": "ink-stained fingers",
            "innkeeper": "a towel over one shoulder",
            "baker": "a flour-dusted apron", "smith": "soot-stained gloves", "florist": "a pollen-covered smock",
            "miner": "a dented helmet with a lamp"}
DECOR = ["bench", "lamppost", "barrel", "signpost", "flowerbed", "cart"]
HARVEST_YIELD = 3


def phase_of(tick: int) -> str:
    return "morning" if tick < 4 else ("midday" if tick < 8 else "evening")


class TownWorld:
    def __init__(self, seed: TownSeed, eager: bool = False, max_actions: int = 60):
        self.seed = seed
        self.laws = seed.laws
        self.eager = eager
        self.max_actions = max_actions
        self.season = seed.season
        self.rooms: dict[str, Room] = {}
        self.objs: dict[str, Obj] = {}
        self.inventory: list[str] = []
        self.coins = 0
        self.day, self.tick = 1, 0
        self.agent_room = "farm"
        self.focus: list[str] = []
        self.seen_fine: set[str] = set()
        self.events: list[Event] = []
        self.goals: list[dict] = []
        self.goal_index = 0
        self.actions = self.invalid_actions = self.zoom_ops = self.nodes_grown = 0
        self.home_of: dict[str, str] = {}
        self.requirements: list[tuple] = []
        self._counter: dict[str, int] = {}
        self._rng = random.Random(seed.surface_seed)
        self._build()
        self._update_schedule()
        self._enter("farm")
        if eager:
            for r in self.rooms:
                self._grow_room(r)

    # ================================================================ building
    def _new_id(self, prefix: str) -> str:
        n = self._counter.get(prefix, 0) + 1
        self._counter[prefix] = n
        return f"{prefix}{n}"

    def _add(self, o: Obj) -> Obj:
        self.objs[o.id] = o
        self.nodes_grown += 1
        return o

    def _item(self, category: str, color: str, loc: str, price: int | None = None, critical=True) -> Obj:
        o = Obj(self._new_id("i"), "item", self._rng.choice(ITEM_NAMES[category]), color,
                fine={"category": category}, location=loc, critical=critical)
        if price is not None:
            o.state.update(for_sale=True, price=price)
        return self._add(o)

    def _build(self) -> None:
        rng, s, L = self._rng, self.seed, self.laws
        for rid, name in [("farm", "your farm"), ("plaza", "the plaza"), ("shop", "the general store"),
                          ("forest", "the forest edge")]:
            self.rooms[rid] = Room(rid, name)
        names = VILLAGER_NAMES[:]
        rng.shuffle(names)
        jobs = JOBS[:]
        rng.shuffle(jobs)
        villagers = []
        self.work_of: dict[str, str] = {}
        for k in range(min(s.n_villagers, len(VILLAGER_NAMES))):
            vid = f"v{k + 1}"
            home = f"home{k + 1}"
            self.rooms[home] = Room(home, f"{names[k]}'s house")
            job = jobs[k % len(jobs)]
            v = self._add(Obj(vid, "villager", names[k], rng.choice(COLORS), fine={"job": job},
                              state={"friendship": 0, "got_crop": False, "got_request": False},
                              location=home, critical=True))
            self.home_of[vid] = home
            wid, wname = WORKPLACE[job]
            self.work_of[vid] = wid
            if wid not in self.rooms:
                self.rooms[wid] = Room(wid, wname)
            villagers.append(v)
        order = ["farm", "plaza", "shop", "forest"] + [w for w, _ in WORKPLACE.values() if w in self.rooms] + \
            [h for h in self.rooms if h.startswith("home")]
        self.rooms = {k: self.rooms[k] for k in order}
        self.nodes_grown += len(self.rooms)
        self._add(Obj("bed", "bed", "bed", "", location="farm", critical=True))

        found_spots = ["forest", "plaza"] + sorted(set(self.work_of.values())) + list(self.home_of.values())
        shop_needed: list[Obj] = []

        # ---- farming: plots (one per soil), seed packets (one per crop), watering can
        if FARMING in s.blocks:
            soils = SOILS[:]
            rng.shuffle(soils)
            for soil in soils:
                self._add(Obj(self._new_id("p"), "plot", "plot", "", fine={"soil": soil},
                              state={"crop": None, "stage": 0, "status": "empty", "watered": False},
                              location="farm", critical=True))
            self._add(Obj(self._new_id("t"), "tool", "watering can", rng.choice(COLORS), location="farm",
                          critical=True))
            good = next(c for c in CROPS if L.season_for[c] == self.season)
            self.crop_color = {c: rng.choice(COLORS) for c in CROPS}
            packs = {}
            for c in CROPS:
                packs[c] = self._add(Obj(self._new_id("s"), "seeds", f"{c} seeds", "", fine={"crop": c},
                                         state={"uses": max(1, s.n_goals) + 1}, location="farm", critical=True))
            if SHOP in s.blocks:
                decoy = rng.choice([c for c in CROPS if c != good])
                for c in (good, decoy):
                    packs[c].state.update(for_sale=True, price=3)
                    packs[c].location = "shop"
                shop_needed.append(packs[good])
            self.requirements.append(("grow", good, L.soil_for[good]))
        else:
            self.crop_color = {c: rng.choice(COLORS) for c in CROPS}

        # ---- quests
        for k in range(max(1, s.n_goals)):
            v = villagers[k % len(villagers)]
            trophy = self._add(Obj(self._new_id("trophy"), "trophy", "trophy", "gold", location=v.id, critical=True))
            self.goals.append({"trophy": trophy.id, "villager": v.id})
            if GIFTING in s.blocks:
                liked_cat = L.likes[v.fine["job"]]
                for j in range(2):
                    in_shop = SHOP in s.blocks and k == 0 and j == 0
                    loc = "shop" if in_shop else rng.choice([x for x in found_spots if x != self.home_of[v.id]])
                    price = 4 if in_shop else None
                    if L.gift_attr == "color":
                        liked = (rng.choice([c for c in CATEGORIES if c != liked_cat]), v.color)
                        decoy = (liked_cat, rng.choice([c for c in COLORS if c != v.color]))
                    else:
                        liked = (liked_cat, rng.choice([c for c in COLORS if c != v.color]))
                        decoy = (rng.choice([c for c in CATEGORIES if c != liked_cat]), v.color)
                    li = self._item(*liked, loc, price)
                    self._item(*decoy, loc, price)
                    if in_shop:
                        shop_needed.append(li)
                    self.requirements.append(("gift", v.id, li.id))
            if SHOP in s.blocks and GIFTING not in s.blocks and FARMING not in s.blocks:
                cat, col = rng.choice(CATEGORIES), rng.choice(COLORS)
                req = self._item(cat, col, "shop", 3)
                self._item(cat, rng.choice([c for c in COLORS if c != col]), "shop", 3)
                v.state["request"] = req.id
                shop_needed.append(req)
            if FARMING in s.blocks:
                self.requirements.append(("deliver_crop", v.id))
        self.coins = sum(o.state["price"] for o in shop_needed)

    # ================================================================ lazy growth
    def _grow_room(self, rid: str) -> None:
        room = self.rooms[rid]
        if room.grown:
            return
        room.grown = True
        r = random.Random(_h(self.seed.surface_seed, "town", rid))
        for _ in range(self.seed.n_distractors):
            if r.random() < 0.5 and rid != "shop":
                cat = r.choice(CATEGORIES)
                o = Obj(self._new_id("i"), "item", r.choice(ITEM_NAMES[cat]), r.choice(COLORS),
                        fine={"category": cat}, location=rid)
            else:
                o = Obj(self._new_id("o"), "decor", r.choice(DECOR), r.choice(COLORS),
                        fine={"condition": r.choice(["weathered", "freshly painted", "rickety", "sturdy"])},
                        location=rid)
            self._add(o)

    # ================================================================ schedule / time
    @property
    def phase(self) -> str:
        return phase_of(self.tick)

    def villager_location(self, vid: str, tick: int | None = None) -> str:
        ph = phase_of(self.tick if tick is None else tick % TICKS_PER_DAY)
        if SCHEDULE not in self.seed.blocks or ph != "midday":
            return self.home_of[vid]
        place = self.laws.midday_place
        if place == "home":
            return self.home_of[vid]
        if place == "work":
            return self.work_of[vid]
        return place

    def _update_schedule(self) -> None:
        for o in self.objs.values():
            if o.kind == "villager":
                o.location = self.villager_location(o.id)

    def _place_type(self, loc: str, vid: str) -> str:
        if loc == self.work_of.get(vid):
            return "work"
        if loc.startswith("home"):
            return "home" if self.home_of[vid] == loc else "other_home"
        return loc

    def _sighting(self) -> None:
        """Record which villagers are/aren't here at midday (evidence for the schedule law)."""
        if self.phase != "midday" or SCHEDULE not in self.seed.blocks:
            return
        here = self.agent_room
        eff = []
        for o in self.objs.values():
            if o.kind != "villager":
                continue
            present = o.location == here
            if present or self.home_of[o.id] == here or self.work_of.get(o.id) == here:
                eff.append({"villager": o.id, "place": self._place_type(here, o.id), "present": present})
        if eff:
            self.events.append(Event(self.actions, "see", here, None, True, True,
                                     f"midday sighting at {here}", effects=eff))

    def _advance(self, ticks: int = 1) -> str:
        msg = ""
        old_phase = self.phase
        self.tick += ticks
        if self.tick >= TICKS_PER_DAY:
            msg = " " + self._night(forced=True)
        else:
            self._update_schedule()
            if self.phase != old_phase:
                msg = f" It is now {self.phase}."
                self._sighting()
        return msg

    def _night(self, forced: bool = False) -> str:
        reports = []
        for p in self.objs.values():
            if p.kind != "plot" or p.state["status"] not in ("planted", "growing"):
                continue
            crop = p.state["crop"]
            attrs = dict(self.visible_attrs(p.id), crop=crop, season=self.season, watered=p.state["watered"])
            if p.fine["soil"] != self.laws.soil_for[crop]:
                p.state["status"], outcome = "withered", "withered"
            elif not p.state["watered"]:
                outcome = "dry"
            elif self.laws.season_for[crop] != self.season:
                p.state["status"], outcome = "dormant", "dormant"
            else:
                p.state["stage"] += 1
                p.state["status"] = "ripe" if p.state["stage"] >= 2 else "growing"
                outcome = p.state["status"]
            p.state["watered"] = False
            text = {"withered": f"the {crop} in {p.id} withered", "dry": f"the {crop} in {p.id} was too dry to grow",
                    "dormant": f"the {crop} in {p.id} lies dormant", "growing": f"the {crop} in {p.id} sprouted",
                    "ripe": f"the {crop} in {p.id} is ripe!"}[outcome]
            reports.append(text)
            self.events.append(Event(self.actions, "night", p.id, None, outcome in ("growing", "ripe"), True,
                                     text, target_attrs=attrs, effects=[{"outcome": outcome}]))
        self.day += 1
        self.tick = 0
        self._update_schedule()
        self._enter("farm")
        lead = "Exhausted, you stumble home." if forced else "You sleep."
        return f"{lead} Day {self.day} begins at your farm." + (" Overnight: " + "; ".join(reports) + "." if reports else "")

    # ================================================================ queries
    def room_objects(self, rid: str) -> list[Obj]:
        return [o for o in self.objs.values() if o.location == rid]

    def accessible(self, oid: str) -> bool:
        o = self.objs.get(oid)
        return o is not None and (o.location == "inv" or o.location == self.agent_room)

    @property
    def goal(self) -> str | None:
        return self.goals[self.goal_index]["trophy"] if self.goal_index < len(self.goals) else None

    @property
    def done(self) -> bool:
        return self.goal is not None and self.goal in self.inventory

    @property
    def out_of_budget(self) -> bool:
        return self.actions >= self.max_actions

    def visible_attrs(self, oid: str | None) -> dict:
        if not oid or oid not in self.objs:
            return {}
        o = self.objs[oid]
        d = {"id": o.id, "kind": o.kind, "name": o.name}
        if o.color:
            d["color"] = o.color
        if o.kind in ("item", "crop"):
            d["category"] = o.fine["category"]
        if o.kind == "seeds":
            d["crop"] = o.fine["crop"]
        if o.kind == "plot":
            d["crop"] = o.state["crop"]
        if oid in self.seen_fine:
            if o.kind == "villager":
                d["job"] = o.fine["job"]
            if o.kind == "plot":
                d["soil"] = o.fine["soil"]
        return d

    # ================================================================ text
    def task_text(self) -> str:
        g = self.goals[self.goal_index]
        v = self.objs[g["villager"]]
        return (f"obtain the trophy {g['trophy']} held by {v.name} ({v.id}, who lives in {self.home_of[v.id]}). "
                f"Talk to {v.name} to learn what they need before they hand it over.")

    def verbs_text(self) -> str:
        return ("go <location>, take <item>, buy <item> (in the shop, costs coins), give <villager> with <item>, "
                "talk <villager>, plant <plot> with <seeds>, water <plot> (hold a watering can), "
                "harvest <plot> (also clears dead plants), sleep (at the farm: ends the day), wait (one tick)")

    def prompt_spec(self) -> dict:
        return {
            "intro": ("You are a newcomer farmer in SeedVille, a small town with your farm, a plaza, a general "
                      "store, the forest edge and the villagers' houses."),
            "goal": self.task_text(),
            "levels": "town map -> locations -> objects and people",
            "details": "(a plot's soil, a villager's job and friendship, an item's category)",
            "verbs": self.verbs_text(),
            "notes": self.world_notes() + " You can only act on things at your current location (or items you "
                     "hold). Everything you change persists.",
            "laws_hint": ("Laws of this universe (which soil and season each crop needs, which gifts villagers "
                          "love, where villagers spend middays) are consistent across towns but NOT necessarily "
                          "what you would expect."),
            "done_text": "When you hold the trophy the episode ends automatically.",
        }

    def world_notes(self) -> str:
        return ("Every valid action takes one tick of a 12-tick day (morning, midday, evening); at night "
                "crops grow and you wake at your farm. Villagers may move around during the day.")

    def _label(self, o: Obj) -> str:
        if o.kind == "villager":
            return f"{o.id} {o.name} (in {'an' if o.color[0] in 'aeiou' else 'a'} {o.color} shirt)"
        if o.kind in ("item", "crop"):
            base = f"{o.id} {o.color} {o.name} ({o.fine['category']})"
        elif o.kind == "seeds":
            base = f"{o.id} packet of {o.name} ({o.state['uses']} left)"
        elif o.kind == "plot":
            st = o.state
            if st["status"] == "empty":
                base = f"{o.id} plot [empty]"
            else:
                base = f"{o.id} plot [{st['crop']}: {st['status']}{', watered' if st['watered'] else ''}]"
        else:
            base = f"{o.id} {o.color + ' ' if o.color else ''}{o.name}"
        if o.state.get("for_sale"):
            base += f" -- for sale, {o.state['price']} coins"
        return base

    def _fine_str(self, o: Obj) -> str:
        self.seen_fine.add(o.id)
        if o.kind == "villager":
            return f" {{wears {JOB_LOOK[o.fine['job']]} -> {o.fine['job']}; friendship {o.state['friendship']}}}"
        if o.kind == "plot":
            return f" {{soil: {o.fine['soil']}}}"
        if o.kind == "decor":
            return f" {{{o.fine['condition']}}}"
        return ""

    def status_line(self) -> str:
        inv = ", ".join(self._label(self.objs[i]) for i in self.inventory) or "nothing"
        return (f"(Day {self.day}, {self.season}, {self.phase} [tick {self.tick}/{TICKS_PER_DAY}] | coins {self.coins} "
                f"| holding: {inv} | goal: obtain {self.goal} | actions used {self.actions}/{self.max_actions} "
                f"| zoom: {'/'.join(['town'] + self.focus)})")

    def view_world(self) -> str:
        lines = [f"[TOWN MAP] You are at {self.agent_room} ({self.rooms[self.agent_room].name})."]
        for rid, room in self.rooms.items():
            tag = "" if room.visited else " (not visited yet)"
            here = " <- you are here" if rid == self.agent_room else ""
            lines.append(f"  {rid}: {room.name}{tag}{here}")
        lines.append(self.status_line())
        return "\n".join(lines)

    def view_room(self, rid: str) -> str:
        self._grow_room(rid)
        remote = rid != self.agent_room
        lines = [f"[{rid}: {self.rooms[rid].name}]" + (" (remembered from your last visit)" if remote else "")]
        for o in self.room_objects(rid):
            if remote and o.kind == "villager":
                continue  # people move; you only see them where you are
            lines.append("  " + self._label(o) + (self._fine_str(o) if self.eager else ""))
        lines.append(self.status_line())
        return "\n".join(lines)

    def view_obj(self, oid: str) -> str:
        o = self.objs[oid]
        self.seen_fine.add(oid)
        lines = [f"[{self._label(o)}]"]
        if o.kind == "villager":
            need = []
            if GIFTING in self.seed.blocks:
                need.append(f"friendship {o.state['friendship']}/2")
            lines += [f"  wears {JOB_LOOK[o.fine['job']]} (a {o.fine['job']})", f"  shirt: {o.color}",
                      "  " + (", ".join(need) or "seems approachable")]
        elif o.kind == "plot":
            lines.append(f"  soil: {o.fine['soil']}")
            if o.state["crop"]:
                lines.append(f"  growth stage {o.state['stage']}/2, {'watered today' if o.state['watered'] else 'dry'}")
        elif o.kind in ("item", "crop"):
            lines.append(f"  colour: {o.color}, category: {o.fine['category']}")
        elif o.kind == "seeds":
            lines.append(f"  label: '{o.fine['crop']}' -- no planting instructions")
        elif o.kind == "decor":
            lines.append(f"  {o.fine['condition']}")
        lines.append(self.status_line())
        return "\n".join(lines)

    def observe(self) -> str:
        if self.eager:
            return self.view_world() + "\n" + self.view_room(self.agent_room)
        if not self.focus:
            return self.view_world()
        f = self.focus[-1]
        return self.view_room(f) if f in self.rooms else self.view_obj(f)

    def zoom_in(self, target: str) -> str:
        self.zoom_ops += 1
        target = (target or "").strip()
        cur = self.focus[-1] if self.focus else None
        if cur is None:
            if target not in self.rooms:
                return f"Cannot zoom into '{target}' from the town map; choose a location id.\n" + self.observe()
            if not self.rooms[target].visited:
                return f"You have not visited {target} yet.\n" + self.observe()
            self.focus = [target]
            return self.observe()
        if cur in self.rooms:
            visible = {o.id for o in self.room_objects(cur) if cur == self.agent_room or o.kind != "villager"}
            if target not in visible | set(self.inventory):
                return f"No '{target}' visible at {cur}.\n" + self.observe()
            self.focus.append(target)
            return self.observe()
        return "Nothing finer to see here.\n" + self.observe()

    def zoom_out(self) -> str:
        self.zoom_ops += 1
        if self.focus:
            self.focus.pop()
        return self.observe()

    def _enter(self, rid: str) -> None:
        self.agent_room = rid
        self.rooms[rid].visited = True
        self._grow_room(rid)
        self.focus = [rid]

    # ================================================================ dynamics
    def liked(self, villager: Obj, item: Obj) -> bool:
        if self.laws.gift_attr == "color":
            return item.color == villager.color
        return item.fine.get("category") == self.laws.likes[villager.fine["job"]]

    def requirements_met(self, v: Obj) -> tuple[bool, str]:
        s = self.seed.blocks
        if GIFTING in s and v.state["friendship"] < 2:
            return False, f"'We hardly know each other yet.' (friendship {v.state['friendship']}/2)"
        if FARMING in s and not v.state["got_crop"]:
            return False, "'I'd love something fresh from your farm.'"
        req = v.state.get("request")
        if req and not v.state["got_request"]:
            r = self.objs[req]
            return False, f"'Could you buy me the {r.color} {r.name} ({r.id}) from the store?'"
        return True, ""

    def act(self, verb: str, target: str | None = None, instrument: str | None = None) -> tuple[str, bool]:
        verb = (verb or "").strip().lower()
        target = (target or "").strip() or None
        instrument = (instrument or "").strip() or None
        if self.out_of_budget:
            return "Out of action budget.", False
        self.actions += 1
        ev = Event(self.actions, verb, target, instrument, False, True, "",
                   target_attrs=self.visible_attrs(target), instr_attrs=self.visible_attrs(instrument),
                   inventory=[self.objs[i].name for i in self.inventory])
        msg, ok, valid = self._dispatch(verb, target, instrument, ev)
        ev.success, ev.valid, ev.message = ok, valid, msg
        self.events.append(ev)
        if not valid:
            self.invalid_actions += 1
        elif verb != "sleep":
            msg += self._advance(1)
        if self.done:
            msg += f" GOAL COMPLETE: you hold {self.goal}."
        elif self.out_of_budget:
            msg += " You have run out of actions."
        return msg, ok

    def _dispatch(self, verb, target, instrument, ev) -> tuple[str, bool, bool]:
        O = self.objs
        if verb == "wait":
            return "You wait a while.", True, True
        if verb == "sleep":
            if self.agent_room != "farm":
                return "You can only sleep in your bed at the farm.", False, False
            return self._night(), True, True
        if verb == "go":
            if target not in self.rooms:
                return f"No location '{target}'.", False, False
            if target == self.agent_room:
                return f"You are already at {target}.", False, False
            self._enter(target)
            self._sighting()
            return f"You walk to {target} ({self.rooms[target].name}).\n" + self.view_room(target), True, True
        if target is None or target not in O:
            return f"Unknown target '{target}'.", False, False
        o = O[target]
        if not self.accessible(target):
            return f"{target} is not here (you are at {self.agent_room}).", False, False
        tool = None
        if instrument:
            if instrument not in O or instrument not in self.inventory:
                return f"You are not holding '{instrument}'.", False, False
            tool = O[instrument]

        if verb == "take":
            if o.kind not in ("item", "crop", "seeds", "tool"):
                return f"You cannot take {o.id}.", False, False
            if o.location == "inv":
                return f"You already hold {o.id}.", False, False
            if o.state.get("for_sale"):
                return f"{o.id} is for sale; use buy.", False, False
            o.location = "inv"
            self.inventory.append(o.id)
            return f"You take {self._label(o)}.", True, True
        if verb == "buy":
            if not o.state.get("for_sale"):
                return f"{o.id} is not for sale.", False, False
            if self.coins < o.state["price"]:
                return f"You cannot afford {o.id} ({o.state['price']} coins; you have {self.coins}).", False, True
            self.coins -= o.state["price"]
            o.state["for_sale"] = False
            o.location = "inv"
            self.inventory.append(o.id)
            return f"You buy {self._label(o)}.", True, True
        if verb == "talk":
            if o.kind != "villager":
                return f"{o.id} does not answer.", False, False
            ok, why = self.requirements_met(o)
            trophy = next((x for x in O.values() if x.kind == "trophy" and x.location == o.id), None)
            if ok and trophy is not None:
                trophy.location = "inv"
                self.inventory.append(trophy.id)
                return f"{o.name} beams and hands you the trophy {trophy.id}!", True, True
            if trophy is None:
                return f"{o.name} chats about the weather.", True, True
            return f"{o.name}: {why}", False, True
        if verb == "give":
            if o.kind != "villager":
                return "You can only give things to villagers.", False, False
            if tool is None:
                return "Give what? Use give <villager> with <item>.", False, False
            if tool.kind not in ("item", "crop"):
                return f"{o.name} has no use for that.", False, False
            liked = self.liked(o, tool)
            self.inventory.remove(tool.id)
            tool.location = o.id
            parts = []
            if tool.kind == "crop" and FARMING in self.seed.blocks and not o.state["got_crop"]:
                o.state["got_crop"] = True
                parts.append(f"{o.name} is delighted with the fresh {tool.name}.")
            if o.state.get("request") == tool.id:
                o.state["got_request"] = True
                parts.append(f"{o.name}: 'Exactly what I asked for!'")
            if liked:
                o.state["friendship"] += 1
                parts.append(f"{o.name} loves the {tool.color} {tool.name}! (friendship {o.state['friendship']})")
            else:
                parts.append(f"{o.name} accepts the {tool.color} {tool.name} politely, but seems unmoved.")
            ev.effects = [{"liked": liked}]
            return " ".join(parts), liked, True
        if verb == "plant":
            if o.kind != "plot":
                return "You can only plant in a plot.", False, False
            if tool is None or tool.kind != "seeds":
                return "Plant what? Use plant <plot> with <seeds>.", False, False
            if o.state["status"] != "empty":
                return f"Plot {o.id} is not empty.", False, True
            o.state.update(crop=tool.fine["crop"], stage=0, status="planted", watered=False)
            tool.state["uses"] -= 1
            if tool.state["uses"] <= 0:
                self.inventory.remove(tool.id)
                tool.location = None
            return f"You plant {tool.fine['crop']} in plot {o.id}.", True, True
        if verb == "water":
            if o.kind != "plot":
                return "You can only water plots.", False, False
            if not any(O[i].name == "watering can" for i in self.inventory):
                return "You need to hold a watering can.", False, False
            if o.state["status"] not in ("planted", "growing"):
                return f"Nothing living to water in {o.id}.", False, True
            o.state["watered"] = True
            return f"You water plot {o.id}.", True, True
        if verb == "harvest":
            if o.kind != "plot":
                return "You can only harvest plots.", False, False
            st = o.state["status"]
            if st == "ripe":
                crop = o.state["crop"]
                got = []
                for _ in range(HARVEST_YIELD):
                    c = self._add(Obj(self._new_id("c"), "crop", crop, self.crop_color[crop],
                                      fine={"category": "food"}, location="inv"))
                    self.inventory.append(c.id)
                    got.append(c.id)
                o.state.update(crop=None, stage=0, status="empty", watered=False)
                return f"You harvest {len(got)} {crop}s ({', '.join(got)}).", True, True
            if st in ("withered", "dormant"):
                o.state.update(crop=None, stage=0, status="empty", watered=False)
                return f"You clear the {st} plant from {o.id}.", False, True
            return f"Nothing ripe in {o.id}.", False, True
        return (f"Unknown verb '{verb}'. Valid: go, take, buy, give, talk, plant, water, harvest, sleep, wait."), False, False

    # ================================================================ episodes
    def next_goal(self, reset_agent: bool = True) -> bool:
        if self.goal_index + 1 >= len(self.goals):
            return False
        self.goal_index += 1
        self.actions = self.invalid_actions = self.zoom_ops = 0
        self.events = []
        if reset_agent:
            self._enter("farm")
        return True

    def snapshot(self) -> dict:
        """JSON-able full state for the pixel UI (ui/seedville.html). Not shown to agents."""
        objs = []
        for o in self.objs.values():
            d = {"id": o.id, "kind": o.kind, "name": o.name, "color": o.color, "location": o.location,
                 "label": self._label(o), "seen": o.id in self.seen_fine}
            if o.kind in ("item", "crop"):
                d["category"] = o.fine["category"]
            if o.kind == "seeds":
                d.update(crop=o.fine["crop"], uses=o.state["uses"])
            if o.kind == "plot":
                d.update(soil=o.fine["soil"], crop=o.state["crop"], stage=o.state["stage"],
                         status=o.state["status"], watered=o.state["watered"])
            if o.kind == "villager":
                d.update(job=o.fine["job"], friendship=o.state["friendship"], home=self.home_of[o.id],
                         work=self.work_of.get(o.id),
                         got_crop=o.state["got_crop"], request=o.state.get("request"),
                         got_request=o.state["got_request"], needs=self.requirements_met(o)[1])
            if o.state.get("for_sale"):
                d.update(for_sale=True, price=o.state["price"])
            if o.kind == "decor":
                d["condition"] = o.fine["condition"]
            objs.append(d)
        g = self.goals[self.goal_index] if self.goal_index < len(self.goals) else None
        return {
            "day": self.day, "tick": self.tick, "ticks_per_day": TICKS_PER_DAY, "phase": self.phase,
            "season": self.season, "coins": self.coins, "agent_room": self.agent_room,
            "goal": self.goal, "goal_villager": g["villager"] if g else None, "done": self.done,
            "actions": self.actions, "max_actions": self.max_actions, "blocks": list(self.seed.blocks),
            "rooms": [{"id": r.id, "name": r.name, "visited": r.visited} for r in self.rooms.values()],
            "objects": objs, "inventory": list(self.inventory),
        }

    def clone(self) -> "TownWorld":
        return copy.deepcopy(self)


def grow_town(seed: TownSeed, **kw) -> TownWorld:
    return TownWorld(seed, **kw)
