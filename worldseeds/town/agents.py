"""SeedVille: privileged oracle, learned seed (TownSeedMemory) and a non-LLM heuristic agent."""

from __future__ import annotations

import random

from ..memory import Hyp, LawSeed
from .seed import CATEGORIES, CROPS, FARMING, GIFTING, JOBS, MIDDAY_PLACES, SCHEDULE, SEASONS, SHOP, SOILS, TownLaws
from .world import TownWorld

# ====================================================================== oracle


class TownOracleError(RuntimeError):
    pass


class TownOracle:
    """Solves the current goal with full knowledge of laws and requirements."""

    def __init__(self, world: TownWorld):
        self.w = world

    def _do(self, verb, target=None, instrument=None, expect=True):
        msg, ok = self.w.act(verb, target, instrument)
        if expect and not ok:
            raise TownOracleError(f"{verb} {target} {instrument}: {msg}")
        return msg

    def goto(self, loc: str) -> None:
        # a move at the last tick of the day ends at home after the night; just go again
        for _ in range(3):
            if self.w.agent_room == loc:
                return
            if self.w.tick == 11 and loc != "farm":
                self._do("wait")
                continue
            self._do("go", loc)

    def obtain(self, oid: str) -> None:
        w = self.w
        if oid in w.inventory:
            return
        o = w.objs[oid]
        self.goto(o.location)
        self._do("buy" if o.state.get("for_sale") else "take", oid)

    def meet(self, vid: str) -> None:
        w = self.w
        for _ in range(30):
            if w.objs[vid].location == w.agent_room:
                return
            nxt = w.villager_location(vid, w.tick + 1) if w.tick + 1 < 12 else w.home_of[vid]
            if nxt == w.agent_room or w.tick + 1 >= 12:
                self._do("wait")
            else:
                self._do("go", nxt)
        raise TownOracleError("could not meet villager")

    def grow_crop(self) -> str:
        w = self.w
        good = next(c for c in w.town_crops if w.laws.season_for[c] == w.season)
        plot = next(o for o in w.objs.values() if o.kind == "plot" and o.fine["soil"] == w.laws.soil_for[good])
        seeds = next(o for o in w.objs.values() if o.kind == "seeds" and o.fine["crop"] == good)
        can = next(o for o in w.objs.values() if o.kind == "tool" and o.name == "watering can")
        if plot.state["status"] not in ("planted", "growing", "ripe"):
            self.obtain(can.id)
            self.obtain(seeds.id)
            self.goto("farm")
            if plot.state["status"] != "empty":
                self._do("harvest", plot.id, expect=False)
            self._do("plant", plot.id, seeds.id)
        for _ in range(4):
            if plot.state["status"] == "ripe":
                break
            self.obtain(can.id)
            self.goto("farm")
            if not plot.state["watered"]:
                self._do("water", plot.id)
            self._do("sleep")
        self.goto("farm")
        self._do("harvest", plot.id)
        return next(i for i in w.inventory if w.objs[i].kind == "crop")

    def _liked_for(self, vid: str, n: int) -> list[str]:
        w = self.w
        cands = [r[2] for r in w.requirements if r[0] == "gift" and r[1] == vid]
        return [c for c in cands if w.objs[c].location in w.rooms or c in w.inventory][:max(0, n)]

    def _hand_in(self, vid: str, items: list[str]) -> None:
        for item in items:
            self.meet(vid)
            self._do("give", vid, item, expect=False)
        self.meet(vid)
        self._do("talk", vid)

    def solve_board(self) -> int:
        """Town board: crops first (they need nights), then friends and fetches, buys last (paid by rewards)."""
        w = self.w
        start = w.actions
        rank = {"harvest": 0, "friends": 1, "fetch": 2, "buy": 3}
        for r in sorted(w.requests, key=lambda r: rank[r["kind"]]):
            if r["done"]:
                continue
            v = w.objs[r["villager"]]
            if r["kind"] == "harvest":
                crops = [i for i in w.inventory if w.objs[i].kind == "crop"]
                self._hand_in(v.id, [crops[0] if crops else self.grow_crop()])
            elif r["kind"] == "friends":
                items = self._liked_for(v.id, 2 - v.state["friendship"])
                for c in items:
                    self.obtain(c)
                self._hand_in(v.id, items)
            elif r["kind"] == "fetch":
                h = w.objs[r["holder"]]
                if r["item"] not in w.inventory:
                    if GIFTING in w.seed.blocks and h.state["friendship"] < 1:
                        items = self._liked_for(h.id, 1)
                        for c in items:
                            self.obtain(c)
                        for c in items:
                            self.meet(h.id)
                            self._do("give", h.id, c)
                    self.meet(h.id)
                    self._do("talk", h.id)
                self._hand_in(v.id, [r["item"]])
            else:
                self.obtain(r["item"])
                self._hand_in(v.id, [r["item"]])
            if not r["done"]:
                raise TownOracleError(f"request {r['id']} not done")
        return w.actions - start

    def solve(self) -> int:
        w = self.w
        if w.requests:
            return self.solve_board()
        start = w.actions
        g = w.goals[w.goal_index]
        v = w.objs[g["villager"]]
        blocks = w.seed.blocks
        to_give = []
        if FARMING in blocks and not v.state["got_crop"]:
            crops = [i for i in w.inventory if w.objs[i].kind == "crop"]
            to_give.append(crops[0] if crops else self.grow_crop())
        if GIFTING in blocks:
            need = 2 - v.state["friendship"]
            if to_give and w.liked(v, w.objs[to_give[0]]):
                need -= 1
            cands = [r[2] for r in w.requirements if r[0] == "gift" and r[1] == v.id]
            cands = [c for c in cands if w.objs[c].location in w.rooms or c in w.inventory][:max(0, need)]
            for c in cands:
                self.obtain(c)
            to_give += cands
        req = v.state.get("request")
        if req and not v.state["got_request"]:
            self.obtain(req)
            to_give.append(req)
        for item in to_give:
            self.meet(v.id)
            self._do("give", v.id, item, expect=False)
        self.meet(v.id)
        self._do("talk", v.id)
        if not w.done:
            raise TownOracleError("goal not reached")
        return w.actions - start


def town_oracle_steps(world: TownWorld) -> int:
    w = world.clone()
    w.max_actions = 10_000
    return TownOracle(w).solve()


# ====================================================================== learned seed

TOWN_SPACES = {
    **{f"soil.{c}": SOILS for c in CROPS},
    **{f"season.{c}": SEASONS for c in CROPS},
    "gift_attr": ["color", "category"],
    **{f"likes.{j}": CATEGORIES for j in JOBS},
    "midday_place": MIDDAY_PLACES,
}


def _crop_space(sp: str):
    if sp.startswith("soil."):
        return SOILS
    if sp.startswith("season."):
        return SEASONS
    return None


class TownSeedMemory(LawSeed):
    """Learned seed for SeedVille, consolidated only from perceived evidence.

    The four standard crops have spaces from the start; a universe with more crops gets a soil and
    a season space for each further crop the first time evidence (or a claim) about it arrives."""

    SPACES = TOWN_SPACES

    def __init__(self, decay: float = 1.0):
        self.SPACES = dict(TOWN_SPACES)  # per instance: grows with the crops this seed has met
        super().__init__(decay)

    def ensure(self, sp: str) -> bool:
        """Make sure hypothesis space ``sp`` exists (creating crop spaces on demand)."""
        if sp in self.hyps:
            return True
        vals = _crop_space(sp)
        if vals is None:
            return False
        self.SPACES[sp] = vals
        self.hyps[sp] = {h: Hyp() for h in vals}
        return True

    def _vote(self, space, hyp, ok, w=1.0):
        if self.ensure(space):
            super()._vote(space, hyp, ok, w)

    def _vote_exclusive(self, space, hyp, w=1.0):
        if self.ensure(space):
            super()._vote_exclusive(space, hyp, w)

    def confident(self, space, thresh=0.75, min_evidence=1.0):
        if space not in self.hyps:
            return None
        return super().confident(space, thresh, min_evidence)

    def recovery(self, laws) -> dict:
        """Per law of ``laws`` (all crops included): recovered? (None = no confident belief)."""
        truth = self.truth(laws)
        return {sp: (None if self.confident(sp) is None else self.confident(sp) == truth[sp]) for sp in truth}

    @classmethod
    def from_dict(cls, d: dict):
        m = cls(decay=d.get("decay", 1.0))
        for sp in d["hyps"]:
            m.ensure(sp)
        for sp, hs in d["hyps"].items():
            for h, (sup, ag) in hs.items():
                m.hyps[sp][h] = Hyp(sup, ag)
        m.rules = list(d.get("rules", []))
        m.worlds_seen = d.get("worlds_seen", 0)
        m.events_seen = d.get("events_seen", 0)
        return m

    def merge(self, other: "LawSeed") -> None:
        for sp in other.hyps:
            self.ensure(sp)
        super().merge(other)

    @classmethod
    def certain_of(cls, laws, strength: float = 50.0):
        m = cls()
        for sp, val in cls.truth(laws).items():
            m.ensure(sp)
            for h in m.hyps[sp]:
                m.hyps[sp][h] = Hyp(strength, 0.0) if h == val else Hyp(0.0, strength)
        return m

    def crops(self) -> list[str]:
        return [sp[5:] for sp in self.SPACES if sp.startswith("soil.")]

    @staticmethod
    def truth(laws: TownLaws) -> dict[str, str]:
        return {
            **{f"soil.{c}": s for c, s in laws.crop_soil},
            **{f"season.{c}": s for c, s in laws.crop_season},
            "gift_attr": laws.gift_attr,
            **{f"likes.{j}": c for j, c in laws.job_likes},
            "midday_place": laws.midday_place,
        }

    def consolidate_events(self, events) -> int:
        self._apply_decay()
        used = 0
        for ev in events:
            if not ev.valid:
                continue
            t, i = ev.target_attrs, ev.instr_attrs
            if ev.verb == "night":
                crop, soil, season = t.get("crop"), t.get("soil"), t.get("season")
                outcome = ev.effects[0]["outcome"] if ev.effects else None
                if crop is None or outcome == "dry":
                    continue
                if outcome == "withered":
                    if soil:
                        self._vote(f"soil.{crop}", soil, False)
                        used += 1
                    continue
                if soil:
                    self._vote_exclusive(f"soil.{crop}", soil)
                if outcome == "dormant":
                    self._vote(f"season.{crop}", season, False)
                else:
                    self._vote_exclusive(f"season.{crop}", season)
                used += 1
            elif ev.verb == "give" and ev.effects and t.get("kind") == "villager" and "color" in i:
                liked = ev.effects[0]["liked"]
                color_pred = i.get("color") == t.get("color")
                self._vote("gift_attr", "color", color_pred == liked)
                if color_pred != liked:
                    # colour cannot explain this reaction, so the job's category must
                    self._vote("gift_attr", "category", True)
                    job, cat = t.get("job"), i.get("category")
                    if job and cat:
                        if liked:
                            self._vote_exclusive(f"likes.{job}", cat)
                        else:
                            self._vote(f"likes.{job}", cat, False)
                used += 1
            elif ev.verb == "see":
                for e in ev.effects:
                    if e["present"] and e["place"] in MIDDAY_PLACES:
                        self._vote_exclusive("midday_place", e["place"])
                    elif not e["present"] and e["place"] in ("home", "work"):
                        self._vote("midday_place", e["place"], False)
                used += 1
        self.events_seen += len(events)
        return used

    def render_laws(self) -> list[str]:
        lines = []
        soil = [f"{c}->{self.confident(f'soil.{c}')}" for c in self.crops() if self.confident(f"soil.{c}")]
        if soil:
            lines.append("- [farming] Crops only survive in their soil: " + ", ".join(soil) + ".")
        season = [f"{c}->{self.confident(f'season.{c}')}" for c in self.crops() if self.confident(f"season.{c}")]
        if season:
            lines.append("- [farming] Crops only grow in their season: " + ", ".join(season) + ".")
        ga = self.confident("gift_attr")
        if ga == "color":
            lines.append("- [gifting] Villagers love gifts whose COLOR matches their shirt.")
        elif ga == "category":
            likes = [f"{j}->{self.confident(f'likes.{j}')}" for j in JOBS if self.confident(f"likes.{j}")]
            lines.append("- [gifting] Villagers love gifts of the CATEGORY their job prefers"
                         + (": " + ", ".join(likes) if likes else " (which category per job: unknown yet)") + ".")
        mp = self.confident("midday_place")
        if mp:
            where = {"home": "their own HOME", "work": "their WORKPLACE"}.get(mp, f"the {mp.upper()}")
            lines.append(f"- [schedule] At midday villagers are at {where}; mornings and evenings at home.")
        return lines

    def predict(self, world, verb: str, target: str, instrument: str | None = None) -> str:
        t, i = world.visible_attrs(target), world.visible_attrs(instrument)
        if not t:
            return f"Unknown target '{target}'."
        verb = verb.lower()
        if verb == "plant":
            crop = i.get("crop")
            if crop is None:
                return "Name the seeds as instrument: predict(plant, <plot>, <seeds>)."
            season_ok = self.confident(f"season.{crop}")
            if season_ok is None:
                return f"UNCERTAIN: unknown which season {crop} needs. Zoom into {target} to note its soil, then try."
            if season_ok != world.season:
                return f"PREDICT FAIL: {crop} grows in {season_ok}, it is {world.season} (it will lie dormant)."
            soil_ok = self.confident(f"soil.{crop}")
            if soil_ok is None:
                return f"UNCERTAIN: unknown which soil {crop} needs. Zoom into {target} to note its soil, then try."
            if "soil" not in t:
                return f"UNCERTAIN: zoom into {target} to see its soil ({crop} needs {soil_ok})."
            return (f"PREDICT SUCCESS: {crop} in {t['soil']} during {world.season} will grow (water it daily)."
                    if t["soil"] == soil_ok else f"PREDICT FAIL: {crop} needs {soil_ok} soil, not {t['soil']} (it will wither).")
        if verb == "give":
            ga = self.confident("gift_attr")
            if ga is None:
                return f"UNCERTAIN: unknown what villagers like. Zoom into {target} first so the reaction teaches you."
            if not i:
                return "Name the gift as instrument: predict(give, <villager>, <item>)."
            if ga == "color":
                ok = i.get("color") == t.get("color")
                return f"PREDICT {'SUCCESS' if ok else 'FAIL'} (villagers love gifts matching their shirt colour)."
            if "job" not in t:
                return f"UNCERTAIN: zoom into {target} to see their job."
            cat = self.confident(f"likes.{t['job']}")
            if cat is None:
                return f"UNCERTAIN: unknown which category a {t['job']} likes."
            ok = i.get("category") == cat
            return f"PREDICT {'SUCCESS' if ok else 'FAIL'} (a {t['job']} loves {cat})."
        if verb in ("find", "talk", "meet"):
            mp = self.confident("midday_place")
            if mp is None:
                return "UNCERTAIN: unknown where villagers spend middays; mornings/evenings they are home."
            if mp == "work" and t.get("kind") == "villager" and target in getattr(world, "work_of", {}):
                return f"PREDICT: at midday {t['name']} is at their workplace ({world.work_of[target]}); otherwise at home."
            return f"PREDICT: at midday villagers are at {'their workplace' if mp == 'work' else 'the ' + mp}; otherwise at home."
        return "No learned law covers this action."


# ====================================================================== heuristic agent


class TownHeuristicAgent:
    """Explores, collects, farms and gifts by simple rules; uses a seed's predict() if given."""

    def __init__(self, world: TownWorld, seed: TownSeedMemory | None = None, rng: random.Random | None = None,
                 read_library: bool | None = None, trust: str = "blind"):
        self.w = world
        self.seed = seed
        # with a library, the agent's head starts empty and it fills ``seed`` by reading shelves
        self.read_library = (world.library is not None) if read_library is None else read_library
        # second-hand sources (library notes, villager testimony): beliefs are rebuilt from the carried
        # seed + this episode's own evidence + what was read or heard, weighted by ``trust``:
        #   blind       every claim counts as strong evidence
        #   calibrated  a source counts only as much as its claims agree with the agent's own evidence
        self.sourced = self.read_library or getattr(world, "testimony", None) is not None
        self.trust = trust
        self.carried = seed
        self.heard: list[tuple[str, str, str]] = []  # (source, space, value)
        self._cache = None
        if self.sourced and self.seed is None:
            self.seed = TownSeedMemory()
        self.lib_done = not self.read_library
        self.lib_read: set[str] = set()
        self.pages_read = 0
        self.rng = rng or random.Random(0)
        self.failed_plant: set[tuple] = set()  # (crop, plot)
        self.given: set[str] = set()
        self.talked = False
        self.wander = 0
        self.sleep_when_watered = True  # the board agent uses the rest of the day for other requests

    def _act(self, verb, target=None, instrument=None):
        return self.w.act(verb, target, instrument)

    def _zoom(self, oid: str) -> None:
        w = self.w
        w.focus = [w.agent_room]
        w.zoom_in(oid)
        w.zoom_out()

    def _pred(self, verb, target, instrument) -> bool | None:
        if self.seed is None:
            return None
        for _ in range(2):
            p = self.seed.predict(self.w, verb, target, instrument)
            if p.startswith("PREDICT SUCCESS"):
                return True
            if p.startswith("PREDICT FAIL"):
                return False
            if "zoom into" in p and self.w.accessible(target) and target not in self.w.seen_fine:
                self._zoom(target)
                continue
            return None
        return None

    def _goal(self):
        g = self.w.goals[self.w.goal_index]
        return self.w.objs[g["villager"]]

    def _held(self, kind):
        return [i for i in self.w.inventory if self.w.objs[i].kind == kind]

    def _need_crop(self, v) -> bool:
        return FARMING in self.w.seed.blocks and not v.state["got_crop"] and not self._held("crop")

    def _absorb(self) -> None:
        evs = self.w.events
        for ev in evs[getattr(self, "_n_absorbed", 0):]:
            if ev.verb not in ("read", "ask") or not ev.valid:
                continue
            for e in ev.effects:
                src = e.get("source", "note:?")
                for sp, val in e.get("claims", []):
                    if sp in TOWN_SPACES or _crop_space(sp) is not None:
                        self.heard.append((src, sp, val))
        self._n_absorbed = len(evs)
        self._refresh()

    def source_weight(self, src: str, own: TownSeedMemory) -> float:
        if self.trust == "blind":
            return 5.0
        agree = disagree = 0
        for s, sp, val in self.heard:
            if s != src:
                continue
            mine = own.confident(sp)
            if mine is not None:
                agree += mine == val
                disagree += mine != val
        rel = (agree + 2) / (agree + disagree + 3)  # unverified sources start at 2/3
        return max(0.0, 6.0 * (2 * rel - 1))

    def _refresh(self) -> None:
        """Rebuild beliefs: carried seed + own evidence from this episode + weighted hearsay."""
        if not self.sourced:
            return
        key = (len(self.w.events), len(self.heard))
        if self._cache == key:
            return
        self._cache = key
        own = TownSeedMemory.from_dict(self.carried.to_dict()) if self.carried else TownSeedMemory()
        own.consolidate_events(self.w.events)
        eff = TownSeedMemory.from_dict(own.to_dict())
        weights = {}
        for src, sp, val in self.heard:
            if src not in weights:
                weights[src] = self.source_weight(src, own)
            if weights[src] > 0:
                eff._vote_exclusive(sp, val, weights[src])
        self.seed = eff

    def _gathering(self) -> bool:
        """With villagers to ask, ask around (up to day 2) before farming by trial and error."""
        w = self.w
        if getattr(w, "testimony", None) is None or w.day > 2:
            return False
        n = sum(1 for o in w.objs.values() if o.kind == "villager")
        return len(w.asked) < (n + 1) // 2

    def _ask_here(self) -> bool:
        """Ask each villager met once what they know (when the town lets you)."""
        w = self.w
        if getattr(w, "testimony", None) is None:
            return False
        for o in w.room_objects(w.agent_room):
            if o.kind == "villager" and o.id not in w.asked:
                self._act("ask", o.id)
                self._absorb()
                return True
        return False

    def _library_step(self) -> bool:
        """Go to the library and read what the town's mechanics need. Returns True if it acted."""
        w = self.w
        if w.agent_room != "library":
            self._act("go", "library")
            return True
        shelves = {o.fine["category"]: o.id for o in w.objs.values() if o.kind == "shelf"}
        if "pile" in shelves:
            if self.pages_read < w.library.pages():
                self.pages_read += 1
                self._act("read", shelves["pile"])
                self._absorb()
                return True
        else:
            for cat in [b for b in ("farming", "gifting", "schedule") if b in w.seed.blocks]:
                if cat not in self.lib_read and cat in shelves:
                    self.lib_read.add(cat)
                    self._act("read", shelves[cat])
                    self._absorb()
                    return True
        self.lib_done = True
        return False

    def step(self) -> None:
        w, v = self.w, self._goal()
        self._refresh()
        if not self.lib_done and self._library_step():
            return
        if self._ask_here():
            return
        here = w.room_objects(w.agent_room)
        # 1. villager here: give useful things, then talk
        if v.location == w.agent_room:
            if self.seed is not None and v.id not in w.seen_fine:
                self._zoom(v.id)
            for c in self._held("crop"):
                if FARMING in w.seed.blocks and not v.state["got_crop"]:
                    self._act("give", v.id, c)
                    return
            req = v.state.get("request") if self.talked else None
            if req and req in w.inventory:
                self._act("give", v.id, req)
                return
            if GIFTING in w.seed.blocks and v.state["friendship"] < 2:
                for it in self._held("item"):
                    if it in self.given or it == req:
                        continue
                    if self._pred("give", v.id, it) is False:
                        continue
                    self.given.add(it)
                    self._act("give", v.id, it)
                    return
            if not self.talked or w.requirements_met(v)[0]:
                self.talked = True
                self._act("talk", v.id)
                return
        # 2. pick up everything free here
        for o in here:
            if o.kind in ("item", "seeds", "tool") and not o.state.get("for_sale"):
                self._act("take", o.id)
                return
        # 3. shop
        if w.agent_room == "shop":
            for o in here:
                if not o.state.get("for_sale") or o.state["price"] > w.coins:
                    continue
                if o.kind == "seeds" and self._need_crop(v) and not self._viable_seeds():
                    if not self._season_ok(o.fine["crop"]):
                        continue
                    self._act("buy", o.id)
                    return
                if o.kind == "item":
                    if self.talked and v.state.get("request") == o.id:
                        self._act("buy", o.id)
                        return
                    if GIFTING in w.seed.blocks and self._pred("give", v.id, o.id) is not False:
                        self._act("buy", o.id)
                        return
        # 4. farm work
        if w.agent_room == "farm" and FARMING in w.seed.blocks:
            if self._farm():
                return
        # 5. explore unvisited places, then go where needed
        unvisited = [r for r, room in w.rooms.items() if not room.visited]
        if unvisited:
            self._act("go", unvisited[0])
            return
        if self._need_crop(v) and w.agent_room != "farm":
            self._act("go", "farm")
            return
        if self._need_crop(v):
            growing = any(o.kind == "plot" and o.state["status"] in ("planted", "growing")
                          for o in w.objs.values())
            if growing:
                self._act("sleep")
                return
            if not self._viable_seeds() and SHOP in w.seed.blocks and w.agent_room != "shop" and any(
                    o.state.get("for_sale") and o.kind == "seeds" and o.state["price"] <= w.coins
                    for o in w.objs.values()):
                self._act("go", "shop")
                return
        self._seek(v)

    def _season_ok(self, crop: str) -> bool:
        if self.seed is None:
            return True
        known = self.seed.confident(f"season.{crop}")
        return known is None or known == self.w.season

    def _viable_seeds(self) -> list[str]:
        return [s for s in self._held("seeds") if self._season_ok(self.w.objs[s].fine["crop"])]

    def _farm(self) -> bool:
        w = self.w
        plots = [o for o in w.objs.values() if o.kind == "plot"]
        can = any(w.objs[i].name == "watering can" for i in w.inventory)
        for p in plots:
            if p.state["status"] == "ripe":
                self._act("harvest", p.id)
                return True
            if p.state["status"] in ("withered", "dormant"):
                self.failed_plant.add((p.state["crop"], p.id))
                self._act("harvest", p.id)
                return True
        if not self._need_crop(self._goal()):
            return False
        growing = [p for p in plots if p.state["status"] in ("planted", "growing")]
        for p in growing:
            if can and not p.state["watered"]:
                self._act("water", p.id)
                return True
        for s in self._held("seeds"):
            crop = w.objs[s].fine["crop"]
            if any(p.state["crop"] == crop for p in growing):
                continue
            options = [p for p in plots if p.state["status"] == "empty" and (crop, p.id) not in self.failed_plant]
            if self.seed is not None:
                for p in options:
                    if p.id not in w.seen_fine:
                        self._zoom(p.id)
                preds = {p.id: self._pred("plant", p.id, s) for p in options}
                if any(v is True for v in preds.values()):
                    options = [p for p in options if preds[p.id] is True]
                elif options and all(v is False for v in preds.values()):
                    continue
            if options:
                self._act("plant", self.rng.choice(options).id, s)
                return True
        if growing and self.sleep_when_watered and all(p.state["watered"] or not can for p in growing):
            self._act("sleep")
            return True
        return False

    def _seek(self, v) -> None:
        w = self.w
        guess = None
        if self.seed is not None and SCHEDULE in w.seed.blocks and w.phase == "midday":
            mp = self.seed.confident("midday_place")
            if mp:
                guess = {"home": w.home_of[v.id], "work": w.work_of[v.id]}.get(mp, mp)
        if guess is None and (SCHEDULE not in w.seed.blocks or w.phase != "midday"):
            guess = w.home_of[v.id]
        if guess is None:
            spots = ["plaza", "shop", w.work_of[v.id], w.home_of[v.id]]
            guess = spots[self.wander % len(spots)]
            self.wander += 1
        if guess == w.agent_room:
            self._act("wait")
        else:
            self._act("go", guess)

    def run(self) -> dict:
        w = self.w
        while not w.done and not w.out_of_budget:
            self.step()
        return {
            "success": w.done, "status": "finished", "error": None, "actions": w.actions,
            "invalid_actions": w.invalid_actions, "zoom_ops": w.zoom_ops, "nodes_grown": w.nodes_grown,
            "tool_calls": w.actions + w.zoom_ops, "predict_calls": 0, "recall_calls": 0, "llm_requests": 0,
            "input_tokens": 0, "output_tokens": 0, "wall_s": 0.0, **w.board_metrics(),
        }


class BoardHeuristicAgent(TownHeuristicAgent):
    """Heuristic agent for the town board: works on whichever request it can advance where it is.

    It knows only what the board says (who wants what, who keeps what) plus what it observes;
    a seed (or the library) lets it predict which gifts land and where villagers are at midday."""

    def __init__(self, *a, prefer=(), **kw):
        super().__init__(*a, **kw)
        self.sleep_when_watered = False
        self.prefer = set(prefer)  # request ids this agent takes on first (teams split the board)

    def _goal(self):
        return None

    def _undone(self, kind=None):
        return [r for r in self.w.requests if not r["done"] and (kind is None or r["kind"] == kind)]

    def _need_crop(self, v=None) -> bool:
        w = self.w
        want = sum(1 for r in self._undone("harvest") if not w.objs[r["villager"]].state["got_crop"])
        return want > len(self._held("crop"))

    def _reserved(self) -> set[str]:
        return {r["item"] for r in self._undone() if r["item"]}

    def _gift_for(self, v) -> str | None:
        for it in self._held("item"):
            if it in self._reserved() or (v.id, it) in self.given:
                continue
            if self._pred("give", v.id, it) is False:
                continue
            return it
        return None

    def _act_with(self, v) -> bool:
        """Do something useful with villager ``v`` (who is here). Returns True if it acted."""
        w = self.w
        if self.seed is not None and v.id not in w.seen_fine:
            self._zoom(v.id)
        r = w.request_of(v.id)
        if r is not None:
            if r["kind"] == "harvest" and not v.state["got_crop"] and self._held("crop"):
                self._act("give", v.id, self._held("crop")[0])
                return True
            if r["item"] and r["item"] in w.inventory:
                self._act("give", v.id, r["item"])
                return True
            if r["kind"] == "friends" and v.state["friendship"] < 2:
                it = self._gift_for(v)
                if it is not None:
                    self.given.add((v.id, it))
                    self._act("give", v.id, it)
                    return True
            if w.request_met(r)[0]:
                self._act("talk", v.id)
                return True
        for q in self._undone("fetch"):
            if q["holder"] == v.id and q["item"] not in w.inventory and w.objs[q["item"]].location == v.id:
                if GIFTING in w.seed.blocks and v.state["friendship"] < 1:
                    it = self._gift_for(v)
                    if it is None:
                        return False
                    self.given.add((v.id, it))
                    self._act("give", v.id, it)
                    return True
                self._act("talk", v.id)
                return True
        return False

    def _targets(self) -> list:
        """Villagers worth seeking now, most useful first."""
        w = self.w
        out = []
        for r in self._undone():
            v = w.objs[r["villager"]]
            if w.request_met(r)[0] or (r["item"] and r["item"] in w.inventory) or (
                    r["kind"] == "harvest" and self._held("crop") and not v.state["got_crop"]):
                out.append((0, v))
            elif r["kind"] == "friends" and self._gift_for(v) is not None:
                out.append((1, v))
            elif r["kind"] == "fetch" and w.objs[r["item"]].location == r["holder"]:
                h = w.objs[r["holder"]]
                if GIFTING not in w.seed.blocks or h.state["friendship"] >= 1 or self._gift_for(h) is not None:
                    out.append((1, h))
        return [v for _, v in sorted(out, key=lambda x: (x[0], not self._mine(x[1])))]

    def _mine(self, v) -> bool:
        return any(r["id"] in self.prefer and v.id in (r["villager"], r["holder"]) for r in self.w.requests)

    def step(self) -> None:
        w = self.w
        self._refresh()
        if not self.lib_done and self._library_step():
            return
        if self._ask_here():
            return
        here = w.room_objects(w.agent_room)
        for v in [o for o in here if o.kind == "villager"]:
            if self._act_with(v):
                return
        for o in here:
            if o.kind in ("item", "seeds", "tool") and not o.state.get("for_sale"):
                self._act("take", o.id)
                return
        if w.agent_room == "shop":
            for o in here:
                if not o.state.get("for_sale") or o.state["price"] > w.coins:
                    continue
                if o.kind == "seeds" and self._need_crop() and not self._viable_seeds() and self._season_ok(o.fine["crop"]):
                    self._act("buy", o.id)
                    return
                if o.kind == "item" and o.id in self._reserved():
                    self._act("buy", o.id)
                    return
        gathering = self._gathering()
        if w.agent_room == "farm" and FARMING in w.seed.blocks and not gathering and self._farm():
            return
        unvisited = [r for r, room in w.rooms.items() if not room.visited]
        if gathering:  # ask around first: people are at home in the morning and evening
            unvisited.sort(key=lambda r: not r.startswith("home"))
        if unvisited:
            self._act("go", unvisited[0])
            return
        # buy what the board needs once there is money for it
        if w.agent_room != "shop" and any(o.state.get("for_sale") and o.state["price"] <= w.coins and (
                o.id in self._reserved() or (o.kind == "seeds" and self._need_crop() and not self._viable_seeds()))
                for o in w.objs.values()):
            self._act("go", "shop")
            return
        growing = [o for o in w.objs.values() if o.kind == "plot" and o.state["status"] in ("planted", "growing")]
        if self._need_crop() and (self._viable_seeds() or any(not p.state["watered"] for p in growing)) \
                and w.agent_room != "farm" and w.tick < 10:
            self._act("go", "farm")
            return
        targets = self._targets()
        if targets:
            self._seek(targets[0])
            return
        if growing:
            if w.agent_room == "farm":
                self._act("sleep")
            else:
                self._act("go", "farm")
            return
        self._act("wait")
