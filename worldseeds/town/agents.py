"""SeedVille: privileged oracle, learned seed (TownSeedMemory) and a non-LLM heuristic agent."""

from __future__ import annotations

import random

from ..memory import LawSeed
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
        good = next(c for c in CROPS if w.laws.season_for[c] == w.season)
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

    def solve(self) -> int:
        w = self.w
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


class TownSeedMemory(LawSeed):
    """Learned seed for SeedVille, consolidated only from perceived evidence."""

    SPACES = TOWN_SPACES

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
        soil = [f"{c}->{self.confident(f'soil.{c}')}" for c in CROPS if self.confident(f"soil.{c}")]
        if soil:
            lines.append("- [farming] Crops only survive in their soil: " + ", ".join(soil) + ".")
        season = [f"{c}->{self.confident(f'season.{c}')}" for c in CROPS if self.confident(f"season.{c}")]
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

    def __init__(self, world: TownWorld, seed: TownSeedMemory | None = None, rng: random.Random | None = None):
        self.w = world
        self.seed = seed
        self.rng = rng or random.Random(0)
        self.failed_plant: set[tuple] = set()  # (crop, plot)
        self.given: set[str] = set()
        self.talked = False
        self.wander = 0

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

    def step(self) -> None:
        w, v = self.w, self._goal()
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
        if growing and all(p.state["watered"] or not can for p in growing):
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
            "input_tokens": 0, "output_tokens": 0, "wall_s": 0.0,
        }
