"""SeedVille world: a lazily grown, zoomable, persistent town with its own clock.

Levels:  town map -> location -> object -> component
Quest:   each goal is a trophy held by a quest villager, handed over (``talk``)
         once that villager's requirements are met:
           gifting  -> friendship 2 (two LIKED gifts; liking follows hidden laws)
           farming  -> one fresh crop (needs the right seed for the season and the
                       right soil, watering, and two nights of growth)
           shop     -> needed goods must be bought with just enough coins
           schedule -> villagers move: home mornings/evenings, a law-given place at midday
Board:   with ``seed.board = k`` the goal is instead the town board in the plaza: k requests
         posted by different villagers, to finish before the end of day ``seed.days``:
           harvest -> bring the villager a fresh crop        (farming laws)
           friends -> reach friendship 2 with the villager   (gifting laws)
           fetch   -> bring an item another villager keeps; that villager hands it over
                      once you are on good terms (friendship 1, with gifting)
           buy     -> bring an item sold at the store; coins come from finished requests
         Every finished request pays REQUEST_REWARD coins.
Time:    every valid action takes one tick; a day has 12 ticks (morning, midday,
         evening). ``sleep`` (at the farm) or running out of ticks ends the day; crops
         grow overnight. The world changes even when the agent does nothing (section 9's
         exogenous dynamics), and everything persists across goals.
"""

from __future__ import annotations

import copy
import random

from ..world import Event, Obj, Room, _h
from .library import CATEGORIES as LIB_CATEGORIES, entry_line
from .seed import (
    CATEGORIES,
    COLORS,
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
REQUEST_REWARD = 4
ITEM_PRICE = 4
SEED_PRICE = 3


def phase_of(tick: int) -> str:
    return "morning" if tick < 4 else ("midday" if tick < 8 else "evening")


class TownWorld:
    def __init__(self, seed: TownSeed, eager: bool = False, max_actions: int = 60, library=None,
                 testimony: float | None = None, zoom_budget: int | None = None, noise: float = 0.0,
                 screen_error: float | None = None, confounder: bool = False):
        self.seed = seed
        self.library = library  # LibraryArchive or None: memory that lives in the town library
        # testimony: None = villagers do not answer questions; else the share of villagers who are
        # consistently wrong when you ``ask`` them what they know
        self.testimony = testimony
        self.liars: set[str] = set()
        self.asked: dict[str, int] = {}
        self.clock_divisor, self._clock_acc = 1, 0
        # perception budget: looking closely at something new costs attention (None = free); refills at night
        self.zoom_budget = zoom_budget
        self.zoom_left = zoom_budget
        self.perception_spent = 0
        # science realism (all off by default):
        #   noise         each night a crop's outcome flips with this probability (pests, lucky sprouts)
        #   screen_error  enables 'screen <plot> with <seeds>': a quick test that takes no time but is
        #                 wrong this often (a cheap in-silico screen vs the slow, exact real experiment)
        #   confounder    daily weather; on rainy nights one soil floods and kills what grows in it
        self.noise = noise
        self.screen_error = screen_error
        self.confounder = confounder
        self.screens = 0
        self.pile_page = 0
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
        self.visit_log: list[str] = []  # places in the order the agent entered them (canvas memory)
        self.focus: list[str] = []
        self.seen_fine: set[str] = set()
        self.events: list[Event] = []
        self.goals: list[dict] = []
        self.goal_index = 0
        self.requests: list[dict] = []  # town board mode (seed.board > 0)
        self.town_crops = seed.town_crops()
        self.actions = self.invalid_actions = self.zoom_ops = self.nodes_grown = 0
        self.home_of: dict[str, str] = {}
        self.requirements: list[tuple] = []
        self._counter: dict[str, int] = {}
        self._rng = random.Random(seed.surface_seed)
        self._build()
        if testimony is not None:
            vids = sorted(o.id for o in self.objs.values() if o.kind == "villager")
            n = round(testimony * len(vids))
            self.liars = set(random.Random(_h(seed.surface_seed, "liars")).sample(vids, n))
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
        if self.library is not None:
            self.rooms.setdefault("library", Room("library", "the library"))
            if self.library.mode == "flat":
                self._add(Obj("shelf_pile", "shelf", "pile of unsorted notes", "", fine={"category": "pile"},
                              location="library", critical=True))
            else:
                for cat in LIB_CATEGORIES:
                    self._add(Obj(f"shelf_{cat}", "shelf", f"{cat} shelf", "", fine={"category": cat},
                                  location="library", critical=True))
        order = ["farm", "plaza", "shop", "forest"] + [w for w, _ in WORKPLACE.values() if w in self.rooms] + \
            [h for h in self.rooms if h.startswith("home")]
        if "library" in self.rooms and "library" not in order:
            order.insert(4, "library")
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
            crops = self.town_crops
            good = next(c for c in crops if L.season_for[c] == self.season)
            self.crop_color = {c: rng.choice(COLORS) for c in crops}
            packs = {}
            for c in crops:
                packs[c] = self._add(Obj(self._new_id("s"), "seeds", f"{c} seeds", "", fine={"crop": c},
                                         state={"uses": max(1, s.n_goals, s.board) + 1}, location="farm", critical=True))
            if SHOP in s.blocks:
                decoy = rng.choice([c for c in crops if c != good])
                for c in (good, decoy):
                    packs[c].state.update(for_sale=True, price=SEED_PRICE)
                    packs[c].location = "shop"
                shop_needed.append(packs[good])
            self.requirements.append(("grow", good, L.soil_for[good]))
        else:
            self.crop_color = {c: rng.choice(COLORS) for c in self.town_crops}

        if s.board:
            self._build_board(villagers, found_spots, shop_needed)
            return
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

    def _gift_pair(self, v: Obj, loc: str) -> Obj:
        """One item the villager loves and one decoy matching the *other* attribute, both at ``loc``."""
        rng, L = self._rng, self.laws
        liked_cat = L.likes[v.fine["job"]]
        if L.gift_attr == "color":
            liked = (rng.choice([c for c in CATEGORIES if c != liked_cat]), v.color)
            decoy = (liked_cat, rng.choice([c for c in COLORS if c != v.color]))
        else:
            liked = (liked_cat, rng.choice([c for c in COLORS if c != v.color]))
            decoy = (rng.choice([c for c in CATEGORIES if c != liked_cat]), v.color)
        li = self._item(*liked, loc)
        self._item(*decoy, loc)
        return li

    def _build_board(self, villagers: list[Obj], found_spots: list[str], shop_needed: list[Obj]) -> None:
        rng, s = self._rng, self.seed
        kinds_on = (["harvest"] if FARMING in s.blocks else []) + (["friends"] if GIFTING in s.blocks else []) + \
            ["fetch"] + (["buy"] if SHOP in s.blocks else [])
        k = max(1, min(s.board, len(villagers) - 1))
        kinds = kinds_on[:]
        rng.shuffle(kinds)
        kinds = kinds[:k]
        while len(kinds) < k:
            kinds.append(rng.choice(kinds_on))
        # buys are paid from rewards: at most as many buys as other requests (unless buys are all there is)
        while "buy" in kinds and kinds.count("buy") > max(1, k - kinds.count("buy")) and len(kinds_on) > 1:
            kinds[kinds.index("buy")] = rng.choice([x for x in kinds_on if x != "buy"])
        order = villagers[:]
        rng.shuffle(order)
        requesters, others = order[:k], order[k:] or order[:1]
        self._add(Obj("board", "board", "town board", "", location="plaza", critical=True))
        for i, (kind, v) in enumerate(zip(kinds, requesters)):
            r = {"id": f"r{i + 1}", "kind": kind, "villager": v.id, "item": None, "holder": None, "done": False,
                 "reward": REQUEST_REWARD}
            if kind == "friends":
                for _ in range(2):
                    li = self._gift_pair(v, rng.choice([x for x in found_spots if x != self.home_of[v.id]]))
                    self.requirements.append(("gift", v.id, li.id))
            elif kind == "fetch":
                h = rng.choice([o for o in others if o.id != v.id] or [o for o in order if o.id != v.id])
                it = self._item(rng.choice(CATEGORIES), rng.choice(COLORS), h.id)
                r.update(item=it.id, holder=h.id)
                v.state["request"] = it.id
                if GIFTING in s.blocks and not any(q[0] == "gift" and q[1] == h.id for q in self.requirements):
                    li = self._gift_pair(h, rng.choice([x for x in found_spots if x != self.home_of[h.id]]))
                    self.requirements.append(("gift", h.id, li.id))
            elif kind == "buy":
                cat, col = rng.choice(CATEGORIES), rng.choice(COLORS)
                it = self._item(cat, col, "shop", ITEM_PRICE)
                self._item(cat, rng.choice([c for c in COLORS if c != col]), "shop", ITEM_PRICE)
                r["item"] = it.id
                v.state["request"] = it.id
            self.requests.append(r)
        # start with enough for the seeds; buys are funded by rewards (or one buy, if buys are all there is)
        self.coins = sum(o.state["price"] for o in shop_needed) + (ITEM_PRICE if all(r["kind"] == "buy" for r in self.requests) else 0)

    # ================================================================ board
    @property
    def board_mode(self) -> bool:
        return bool(self.requests)

    def request_of(self, vid: str) -> dict | None:
        return next((r for r in self.requests if r["villager"] == vid and not r["done"]), None)

    def request_met(self, r: dict) -> tuple[bool, str]:
        v = self.objs[r["villager"]]
        if r["kind"] == "harvest":
            return (True, "") if v.state["got_crop"] else (False, "'I'd love something fresh from your farm.'")
        if r["kind"] == "friends":
            f = v.state["friendship"]
            return (True, "") if f >= 2 else (False, f"'We hardly know each other yet.' (friendship {f}/2)")
        if v.state["got_request"]:
            return True, ""
        it = self.objs[r["item"]]
        where = (f"{self.objs[r['holder']].name} ({r['holder']}) keeps one" if r["kind"] == "fetch"
                 else "the general store sells it")
        return False, f"'Could you bring me the {it.color} {it.name} ({it.id})? {where}.'"

    def request_text(self, r: dict) -> str:
        v = self.objs[r["villager"]]
        who = f"{v.name} ({v.id}, lives in {self.home_of[v.id]})"
        if r["kind"] == "harvest":
            what = "wants something fresh from your farm"
        elif r["kind"] == "friends":
            what = "wants to become friends (friendship 2)"
        else:
            it = self.objs[r["item"]]
            src = (f"which {self.objs[r['holder']].name} ({r['holder']}) keeps" if r["kind"] == "fetch"
                   else f"sold at the general store for {ITEM_PRICE} coins")
            what = f"needs the {it.color} {it.name} {it.id}, {src}"
        return f"{r['id']}. {who} {what}. Reward {r['reward']} coins." + (" [DONE]" if r["done"] else "")

    def board_text(self) -> str:
        n = sum(r["done"] for r in self.requests)
        return (f"TOWN BOARD ({n}/{len(self.requests)} done, until the end of day {self.seed.days}):\n"
                + "\n".join("  " + self.request_text(r) for r in self.requests))

    def _board_talk(self, o: Obj) -> tuple[str, bool, bool]:
        r = self.request_of(o.id)
        if r is not None:
            ok, why = self.request_met(r)
            if not ok:
                return f"{o.name}: {why}", False, True
            r["done"] = True
            self.coins += r["reward"]
            n = sum(x["done"] for x in self.requests)
            return (f"{o.name} ticks request {r['id']} off the town board and pays you {r['reward']} coins! "
                    f"({n}/{len(self.requests)} requests done)"), True, True
        held = next((x for x in self.objs.values() if x.location == o.id and x.kind == "item"
                     and any(q["item"] == x.id and q["kind"] == "fetch" for q in self.requests)), None)
        if held is not None:
            if GIFTING in self.seed.blocks and o.state["friendship"] < 1:
                return (f"{o.name}: 'The {held.color} {held.name}? Maybe once we know each other a little better.' "
                        f"(friendship {o.state['friendship']}/1)"), False, True
            held.location = "inv"
            self.inventory.append(held.id)
            return f"{o.name} hands you the {held.color} {held.name} ({held.id}).", True, True
        return f"{o.name} chats about the weather.", True, True

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

    @property
    def weather(self) -> str:
        if not self.confounder:
            return "fair"
        return "rainy" if random.Random(_h(self.seed.surface_seed, "weather", self.day)).random() < 0.35 else "sunny"

    @property
    def flood_soil(self) -> str:
        """The soil that floods on rainy nights (fixed per universe, hidden)."""
        return SOILS[_h("flood", *sorted(self.laws.soil_for.items())) % len(SOILS)]

    def _night(self, forced: bool = False) -> str:
        reports = []
        rainy = self.weather == "rainy"
        for p in self.objs.values():
            if p.kind != "plot" or p.state["status"] not in ("planted", "growing"):
                continue
            crop = p.state["crop"]
            watered = p.state["watered"] or rainy  # rain waters every plot
            attrs = dict(self.visible_attrs(p.id), crop=crop, season=self.season, watered=watered)
            if self.confounder:
                attrs["weather"] = self.weather
            if p.fine["soil"] != self.laws.soil_for[crop]:
                outcome = "withered"
            elif not watered:
                outcome = "dry"
            elif self.laws.season_for[crop] != self.season:
                outcome = "dormant"
            else:
                outcome = "ripe" if p.state["stage"] + 1 >= 2 else "growing"
            if rainy and p.fine["soil"] == self.flood_soil and outcome != "dry":
                outcome = "withered"  # waterlogged: the confounder
            if self.noise and outcome != "dry" and \
                    random.Random(_h(self.seed.surface_seed, "noise", self.day, p.id)).random() < self.noise:
                outcome = "withered" if outcome in ("growing", "ripe") else (
                    "ripe" if p.state["stage"] + 1 >= 2 else "growing")
            if outcome in ("growing", "ripe"):
                p.state["stage"] += 1
            if outcome != "dry":
                p.state["status"] = outcome
            p.state["watered"] = False
            text = {"withered": f"the {crop} in {p.id} withered", "dry": f"the {crop} in {p.id} was too dry to grow",
                    "dormant": f"the {crop} in {p.id} lies dormant", "growing": f"the {crop} in {p.id} sprouted",
                    "ripe": f"the {crop} in {p.id} is ripe!"}[outcome]
            reports.append(text)
            self.events.append(Event(self.actions, "night", p.id, None, outcome in ("growing", "ripe"), True,
                                     text, target_attrs=attrs, effects=[{"outcome": outcome}]))
        self.day += 1
        self.tick = 0
        self.zoom_left = self.zoom_budget
        self._update_schedule()
        self._enter("farm")
        lead = ("Exhausted, you stumble home." if forced else "You sleep.") + (" It rained in the night." if rainy else "")
        return f"{lead} Day {self.day} begins at your farm." + (" Overnight: " + "; ".join(reports) + "." if reports else "")

    # ================================================================ queries
    def room_objects(self, rid: str) -> list[Obj]:
        return [o for o in self.objs.values() if o.location == rid]

    def accessible(self, oid: str) -> bool:
        o = self.objs.get(oid)
        return o is not None and (oid in self.inventory or o.location == self.agent_room)

    @property
    def goal(self) -> str | None:
        if self.requests:
            return "board"
        return self.goals[self.goal_index]["trophy"] if self.goal_index < len(self.goals) else None

    @property
    def done(self) -> bool:
        if self.requests:
            return all(r["done"] for r in self.requests)
        return self.goal is not None and self.goal in self.inventory

    @property
    def out_of_time(self) -> bool:
        return bool(self.requests) and self.day > self.seed.days

    @property
    def out_of_budget(self) -> bool:
        return self.actions >= self.max_actions or self.out_of_time

    def board_metrics(self) -> dict:
        if not self.requests:
            return {}
        return {"board_done": sum(r["done"] for r in self.requests), "board_total": len(self.requests),
                "days_used": min(self.day, self.seed.days), "coins": self.coins,
                **{f"board_{k}_done": sum(r["done"] for r in self.requests if r["kind"] == k)
                   for k in ("harvest", "friends", "fetch", "buy")},
                **{f"board_{k}_total": sum(1 for r in self.requests if r["kind"] == k)
                   for k in ("harvest", "friends", "fetch", "buy")}}

    def visible_attrs(self, oid: str | None) -> dict:
        if not oid or oid not in self.objs:
            return {}
        o = self.objs[oid]
        d = {"id": o.id, "kind": o.kind, "name": o.name}
        if o.color:
            d["color"] = o.color
        if o.kind in ("item", "crop") and not (self.zoom_budget is not None and oid not in self.seen_fine
                                                and o.location != "inv"):
            d["category"] = o.fine["category"]
        if o.kind == "seeds":
            d["crop"] = o.fine["crop"]
        if o.kind == "plot":
            d["crop"] = o.state["crop"]
        if o.kind == "shelf":
            d["category"] = o.fine["category"]
        if oid in self.seen_fine:
            if o.kind == "villager":
                d["job"] = o.fine["job"]
            if o.kind == "plot":
                d["soil"] = o.fine["soil"]
        return d

    # ================================================================ text
    def task_text(self) -> str:
        if self.requests:
            return ("complete the requests on the town board (in the plaza) before the end of day "
                     f"{self.seed.days}. Finished requests pay coins.\n" + "\n".join(
                         "  " + self.request_text(r) for r in self.requests)
                     + "\nWhen a request is fulfilled, talk to the villager who posted it to tick it off.")
        g = self.goals[self.goal_index]
        v = self.objs[g["villager"]]
        return (f"obtain the trophy {g['trophy']} held by {v.name} ({v.id}, who lives in {self.home_of[v.id]}). "
                f"Talk to {v.name} to learn what they need before they hand it over.")

    def verbs_text(self) -> str:
        v = ("go <location>, take <item>, buy <item> (in the shop, costs coins), give <villager> with <item>, "
             "talk <villager>, plant <plot> with <seeds>, water <plot> (hold a watering can), "
             "harvest <plot> (also clears dead plants), sleep (at the farm: ends the day), wait (one tick)")
        if self.library is not None:
            v += ", read <shelf> (in the library)"
        if self.requests:
            v += ", read board (in the plaza)"
        if self.testimony is not None:
            v += ", ask <villager> (they tell you what their trade has taught them)"
        if self.screen_error is not None:
            v += (", screen <plot> with <seeds> (a quick test kit: takes no time, uses an action, and is wrong "
                  "about one time in " + f"{round(1 / self.screen_error) if self.screen_error else 'never'})")
        return v

    def prompt_spec(self) -> dict:
        return {
            "intro": ("You are a newcomer farmer in SeedVille, a town with your farm, a plaza, a general store, "
                      "the villagers' workplaces, the forest edge, the mountain, the beach and the villagers' houses."),
            "goal": self.task_text(),
            "levels": "town map -> locations -> objects and people",
            "details": "(a plot's soil, a villager's job and friendship, an item's category)",
            "verbs": self.verbs_text(),
            "notes": self.world_notes() + " You can only act on things at your current location (or items you "
                     "hold). Everything you change persists.",
            "laws_hint": ("Laws of this universe (which soil and season each crop needs, which gifts villagers "
                          "love, where villagers spend middays) are consistent across towns but NOT necessarily "
                          "what you would expect."),
            "done_text": ("The episode ends when every request is ticked off, or when the last day ends. "
                          "Each request ticked off counts." if self.requests else
                          "When you hold the trophy the episode ends automatically."),
        }

    def world_notes(self) -> str:
        return ("Every valid action takes one tick of a 12-tick day (morning, midday, evening); at night "
                "crops grow and you wake at your farm. Villagers may move around during the day.")

    def _label(self, o: Obj) -> str:
        if o.kind == "villager":
            return f"{o.id} {o.name} (in {'an' if o.color[0] in 'aeiou' else 'a'} {o.color} shirt)"
        if o.kind in ("item", "crop"):
            # with a perception budget an item's category is a fine detail: look closer to see it
            hidden = self.zoom_budget is not None and o.id not in self.seen_fine and o.location != "inv"
            base = f"{o.id} {o.color} {o.name}" + ("" if hidden else f" ({o.fine['category']})")
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
                f"| holding: {inv} | goal: {self._goal_status()} | actions used {self.actions}/{self.max_actions} "
                f"| zoom: {'/'.join(['town'] + self.focus)}"
                + (f" | attention left today {self.zoom_left}/{self.zoom_budget}" if self.zoom_budget is not None else "")
                + (f" | weather: {self.weather}" if self.confounder else "")
                + ")")

    def _goal_status(self) -> str:
        if self.requests:
            return (f"board {sum(r['done'] for r in self.requests)}/{len(self.requests)} done, "
                    f"last day {self.seed.days}")
        return f"obtain {self.goal}"

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
            r = self.request_of(o.id) if self.requests else None
            if r is not None:
                lines.append(f"  posted board request {r['id']} ({r['kind']})")
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
        elif o.kind == "board":
            lines.append(self.board_text())
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
            if self.zoom_budget is not None and target not in self.seen_fine:
                if self.zoom_left <= 0:
                    return (f"[{self._label(self.objs[target])}] You are too tired to take in the details today "
                            f"(attention {self.zoom_budget}/{self.zoom_budget} spent; it comes back after a night's "
                            "sleep).\n" + self.status_line())
                self.zoom_left -= 1
                self.perception_spent += 1
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
        self.visit_log.append(rid)
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
        elif verb not in ("sleep", "screen"):  # a quick screen takes no game time
            # with a team in town (worldseeds.town.team) the clock moves one tick per round of moves
            self._clock_acc += 1
            if self._clock_acc >= self.clock_divisor:
                self._clock_acc = 0
                msg += self._advance(1)
        if self.done:
            msg += (" TOWN BOARD COMPLETE: every request is done!" if self.requests
                    else f" GOAL COMPLETE: you hold {self.goal}.")
        elif self.out_of_time:
            msg += f" The season's board closes: day {self.seed.days} is over."
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
        if verb == "read" and o.kind == "board":
            return self.board_text(), True, True
        if verb in ("read", "write"):
            return self._library_action(verb, o, instrument, ev)
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
            if self.requests:
                return self._board_talk(o)
            ok, why = self.requirements_met(o)
            trophy = next((x for x in O.values() if x.kind == "trophy" and x.location == o.id), None)
            if ok and trophy is not None:
                trophy.location = "inv"
                self.inventory.append(trophy.id)
                return f"{o.name} beams and hands you the trophy {trophy.id}!", True, True
            if trophy is None:
                return f"{o.name} chats about the weather.", True, True
            return f"{o.name}: {why}", False, True
        if verb == "ask":
            return self._ask(o, ev)
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
        if verb == "screen":
            if self.screen_error is None:
                return "You have no test kit.", False, False
            if o.kind != "plot" or tool is None or tool.kind != "seeds":
                return "Screen what? Use screen <plot> with <seeds>.", False, False
            crop = tool.fine["crop"]
            good = o.fine["soil"] == self.laws.soil_for[crop] and self.laws.season_for[crop] == self.season
            self.screens += 1
            r = random.Random(_h(self.seed.surface_seed, "screen", self.screens, o.id, crop)).random()
            says = good if r >= self.screen_error else not good
            ev.effects = [{"screen": says, "crop": crop, "season": self.season}]
            return (f"The quick test suggests {crop} would {'do well' if says else 'not grow'} in {o.id} now. "
                    "(Quick tests are sometimes wrong.)"), True, True
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

    # ================================================================ testimony
    def _ask(self, v: Obj, ev) -> tuple[str, bool, bool]:
        from .sources import describe, maybe_corrupt, testimony

        if v.kind != "villager":
            return f"{v.id} cannot answer questions.", False, False
        if self.testimony is None:
            return f"{v.name} shrugs: 'Ask me something else.'", False, True
        k = self.asked.get(v.id, 0)
        self.asked[v.id] = k + 1
        claims, wrong = [], 0
        for sp, val in testimony(self, v, k):
            said, bad = maybe_corrupt(sp, val, 1.0 if v.id in self.liars else 0.0, "villager", self.seed.surface_seed, v.id)
            if sp.startswith("likes.") and claims and claims[0] == ("gift_attr", "color"):
                continue  # someone who thinks taste goes by shirt colour names no favourite category
            claims.append((sp, said))
            wrong += bad
        ev.effects = [{"source": f"villager:{v.id}", "claims": [list(c) for c in claims], "wrong": wrong}]
        job = v.fine["job"]
        said = "; ".join(describe(sp, val, job) for sp, val in claims)
        return f"{v.name} the {job}: '{said[0].upper() + said[1:]}.'", True, True

    # ================================================================ library
    def _library_action(self, verb, shelf, text, ev) -> tuple[str, bool, bool]:
        if shelf.kind != "shelf" or self.library is None:
            return f"You cannot {verb} {shelf.id}.", False, False
        lib, cat = self.library, shelf.fine["category"]
        if verb == "write":
            if not text:
                return "Write what? Use write <shelf> with <note text>.", False, False
            e = lib.add_note("general" if cat == "pile" else cat, text, author="agent", episode=self.seed.surface_seed)
            ev.effects = [{"wrote": e.text, "category": e.category}]
            return f"You add a note to the {shelf.name}: \"{e.text}\"", True, True
        lib.reads += 1
        if cat == "pile":
            n = lib.pages()
            k = self.pile_page % n
            self.pile_page += 1
            entries = lib.page(k)
            head = f"You leaf through the unsorted notes (page {k + 1} of {n}):"
        else:
            entries = lib.shelf(cat)
            head = f"You read the {cat} shelf ({len(entries)} notes):"
        ev.effects = [{"category": e.category, "claims": [list(c) for c in e.claims], "text": e.text,
                       "source": f"note:{e.author}"} for e in entries]
        if not entries:
            return f"The {shelf.name} is empty.", True, True
        return head + "\n" + "\n".join(entry_line(e) for e in entries), True, True

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
            if o.kind == "shelf":
                d["category"] = o.fine["category"]
                d["entries"] = (len(self.library.entries) if o.fine["category"] == "pile"
                                else len(self.library.shelf(o.fine["category"]))) if self.library else 0
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
                         got_request=o.state["got_request"],
                         needs=(self.request_met(self.request_of(o.id))[1] if self.request_of(o.id) else "")
                         if self.requests else self.requirements_met(o)[1])
            if o.state.get("for_sale"):
                d.update(for_sale=True, price=o.state["price"])
            if o.kind == "decor":
                d["condition"] = o.fine["condition"]
            objs.append(d)
        g = self.goals[self.goal_index] if self.goal_index < len(self.goals) else None
        if self.requests:
            nxt = next((r for r in self.requests if not r["done"]), None)
            g = {"villager": nxt["villager"]} if nxt else None
        return {
            "day": self.day, "tick": self.tick, "ticks_per_day": TICKS_PER_DAY, "phase": self.phase,
            "season": self.season, "coins": self.coins, "agent_room": self.agent_room,
            "goal": self.goal, "goal_villager": g["villager"] if g else None, "done": self.done,
            "actions": self.actions, "max_actions": self.max_actions, "blocks": list(self.seed.blocks),
            "rooms": [{"id": r.id, "name": r.name, "visited": r.visited} for r in self.rooms.values()],
            "objects": objs, "inventory": list(self.inventory),
            **({"requests": [dict(r, text=self.request_text(r)) for r in self.requests], "days": self.seed.days}
               if self.requests else {}),
            **({"testimony": True, "liars": sorted(self.liars)} if self.testimony is not None else {}),
        }

    def clone(self) -> "TownWorld":
        return copy.deepcopy(self)


def grow_town(seed: TownSeed, **kw) -> TownWorld:
    return TownWorld(seed, **kw)
