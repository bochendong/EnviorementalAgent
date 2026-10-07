"""Several agents in one SeedVille town, working on the same town board.

Every agent has its own *body*: where it stands, what it carries, what it has inspected, and its
own action budget. The town, the board, the coins and the clock are shared. The clock moves one
tick per round of moves (one tick after as many valid actions as there are agents awake), so
two agents get twice as much done in a day as one.

Night: an agent at the farm can ``sleep``; it then waits in bed until the day ends. The day ends
when everyone still working is in bed, or when the clock runs out. Then crops grow and everybody
wakes at the farm.

Messages: ``tell(teammate, text)`` costs an action; the text (and, from heuristic agents, the
claims behind it) is delivered with the teammate's next observation.

``Teammate`` is a view of the town through one agent's body. It offers the same interface as a
``TownWorld`` (observe, zoom_in, act, objs, inventory, ...), so the LLM tools and the heuristic
agent work unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .world import TownWorld

TEAM_NAMES = ["Ana", "Bo", "Cy", "Di"]
_BODY = ("agent_room", "inventory", "focus", "seen_fine", "actions", "invalid_actions", "zoom_ops", "pile_page")


@dataclass
class Body:
    name: str
    agent_room: str = "farm"
    inventory: list = field(default_factory=list)
    focus: list = field(default_factory=list)
    seen_fine: set = field(default_factory=set)
    actions: int = 0
    invalid_actions: int = 0
    zoom_ops: int = 0
    pile_page: int = 0
    asleep: bool = False
    finished: bool = False
    inbox: list = field(default_factory=list)  # [{"from", "text", "claims"}]
    sent: int = 0


class Team:
    def __init__(self, world: TownWorld, n: int, messages: bool = False):
        self.w = world
        self.messages = messages  # may teammates message each other (tell)?
        self.bodies = [Body(TEAM_NAMES[i], focus=["farm"]) for i in range(n)]
        self.cur: int | None = None
        self._morning: asyncio.Event | None = None
        self.nights = 0
        self.activate(0)
        self._update_clock()

    # ------------------------------------------------------------ bodies
    def activate(self, i: int) -> None:
        if self.cur == i:
            return
        w = self.w
        if self.cur is not None:
            b = self.bodies[self.cur]
            for k in _BODY:
                setattr(b, k, getattr(w, k))
        b = self.bodies[i]
        for k in _BODY:
            setattr(w, k, getattr(b, k))
        self.cur = i

    def save(self) -> None:
        """Write the active body's live state back to its Body record."""
        if self.cur is not None:
            b = self.bodies[self.cur]
            for k in _BODY:
                setattr(b, k, getattr(self.w, k))

    def awake(self) -> list[int]:
        return [i for i, b in enumerate(self.bodies) if not b.asleep and not b.finished and not self._spent(i)]

    def _spent(self, i: int) -> bool:
        b = self.bodies[i]
        acts = self.w.actions if self.cur == i else b.actions
        return acts >= self.w.max_actions

    def _update_clock(self) -> None:
        self.w.clock_divisor = max(1, len(self.awake()))

    @property
    def done(self) -> bool:
        return self.w.done or self.w.out_of_time

    # ------------------------------------------------------------ actions
    def act(self, i: int, verb, target=None, instrument=None) -> tuple[str, bool]:
        w, b = self.w, self.bodies[i]
        self.activate(i)
        if b.asleep:
            return "You are asleep; you will wake up at your farm in the morning.", False
        verb = (verb or "").strip().lower()
        if verb == "sleep" and w.agent_room == "farm" and not w.out_of_budget:
            others = [j for j in self.awake() if j != i]
            if others:
                w.actions += 1
                b.asleep = True
                self._update_clock()
                return "You go to bed. You will wake when the day ends and your teammates come home.", True
        day = w.day
        msg, ok = w.act(verb, target, instrument)
        if w.day != day:
            self._new_day()
        self._update_clock()
        return msg, ok

    def tell(self, i: int, to: str, text: str, claims=None) -> tuple[str, bool]:
        self.activate(i)
        w = self.w
        j = next((k for k, x in enumerate(self.bodies) if x.name.lower() == (to or "").strip().lower()), None)
        if j is None or j == i:
            names = ", ".join(x.name for k, x in enumerate(self.bodies) if k != i)
            return f"No teammate called '{to}'. Your teammates: {names}.", False
        if w.out_of_budget:
            return "Out of action budget.", False
        w.actions += 1
        self.bodies[i].sent += 1
        self.bodies[j].inbox.append({"from": self.bodies[i].name, "text": (text or "")[:400],
                                     "claims": list(claims or [])})
        w._clock_acc += 1
        msg = ""
        if w._clock_acc >= w.clock_divisor:
            w._clock_acc = 0
            day = w.day
            msg = w._advance(1)
            if w.day != day:
                self._new_day()
        self._update_clock()
        return f"You tell {self.bodies[j].name}: \"{text}\"" + msg, True

    def inbox_text(self, i: int) -> str:
        b = self.bodies[i]
        if not b.inbox:
            return ""
        out = "\n".join(f"[Message from {m['from']}: {m['text']}]" for m in b.inbox)
        b.inbox_seen = getattr(b, "inbox_seen", []) + b.inbox
        b.inbox = []
        return out + "\n"

    def finish(self, i: int) -> None:
        """Agent ``i`` stops (goal reached, budget spent or gave up): never wait for it at night."""
        self.bodies[i].finished = True
        self._maybe_night()

    def _maybe_night(self) -> None:
        if self.done:
            self._wake()
            return
        if any(b.asleep for b in self.bodies) and not self.awake():
            sleeper = next(i for i, b in enumerate(self.bodies) if b.asleep)
            self.activate(sleeper)
            self.w._night()
            self._new_day()
        self._update_clock()

    def _new_day(self) -> None:
        self.nights += 1
        cur = self.cur
        for i, b in enumerate(self.bodies):
            self.activate(i)
            self.w._enter("farm")
            b.asleep = False
        self.activate(cur if cur is not None else 0)
        self._wake()

    def _wake(self) -> None:
        for b in self.bodies:
            b.asleep = False
        if self._morning is not None:
            self._morning.set()
            self._morning = None

    async def wait_morning(self, i: int) -> None:
        """Async agents (LLM) in bed wait here until the next day starts."""
        self._maybe_night()
        while self.bodies[i].asleep and not self.done:
            if self._morning is None:
                self._morning = asyncio.Event()
            ev = self._morning
            try:
                await asyncio.wait_for(ev.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._maybe_night()

    # ------------------------------------------------------------ metrics
    def metrics(self) -> dict:
        self.save()
        acts = [b.actions for b in self.bodies]
        return {**self.w.board_metrics(), "success": self.w.done, "team_size": len(self.bodies),
                "team_actions": sum(acts), "agent_actions": acts,
                "messages": sum(b.sent for b in self.bodies),
                "team_invalid_actions": sum(b.invalid_actions for b in self.bodies)}


class Teammate:
    """A TownWorld seen through one teammate's body (same interface as TownWorld)."""

    def __init__(self, team: Team, i: int):
        object.__setattr__(self, "team", team)
        object.__setattr__(self, "i", i)

    @property
    def name(self) -> str:
        return self.team.bodies[self.i].name

    def _w(self) -> TownWorld:
        self.team.activate(self.i)
        return self.team.w

    def __getattr__(self, k):
        return getattr(self._w(), k)

    def __setattr__(self, k, v):
        setattr(self._w(), k, v)

    # actions and views
    def act(self, verb, target=None, instrument=None):
        msg, ok = self.team.act(self.i, verb, target, instrument)
        return self.team.inbox_text(self.i) + msg, ok

    def tell(self, to: str, text: str, claims=None):
        return self.team.tell(self.i, to, text, claims)

    def observe(self) -> str:
        return self.team.inbox_text(self.i) + self._w().observe()

    def zoom_in(self, target: str) -> str:
        return self._w().zoom_in(target)

    def zoom_out(self) -> str:
        return self._w().zoom_out()

    @property
    def asleep(self) -> bool:
        return self.team.bodies[self.i].asleep

    @property
    def done(self) -> bool:
        return self.team.w.done

    @property
    def out_of_budget(self) -> bool:
        w = self._w()
        return w.out_of_budget

    def prompt_spec(self) -> dict:
        p = self._w().prompt_spec()
        mates = ", ".join(b.name for k, b in enumerate(self.team.bodies) if k != self.i)
        p["intro"] = (f"You are {self.name}, one of {len(self.team.bodies)} newcomer farmers working together in "
                      f"SeedVille (your teammates: {mates}). " + p["intro"].split(". ", 1)[-1])
        p["notes"] += (" Your teammates act in the same town at the same time: the farm, the coins and the board "
                       "are shared, each of you carries your own things. The clock moves one tick per round of "
                       "everyone's moves. 'sleep' puts you to bed until the day ends for the whole team.")
        return p


# ====================================================================== heuristic teams
def _heuristic_team_agent():
    from .agents import BoardHeuristicAgent

    class TeamHeuristicAgent(BoardHeuristicAgent):
        """A board heuristic agent in a team: prefers its share of the requests, and with messages on
        first tells each teammate the laws it is confident of (one message each)."""

        def __init__(self, mate: Teammate, seed=None, rng=None, trust="calibrated", prefer=(), message=False):
            super().__init__(mate, seed, rng, trust=trust, prefer=prefer)
            self.message = message
            self.told: set[str] = set()
            if message:
                self.sourced = True
            self._n_inbox = 0

        def _absorb_messages(self) -> None:
            b = self.w.team.bodies[self.w.i]
            seen = getattr(b, "inbox_seen", []) + b.inbox
            new = seen[self._n_inbox:]
            self._n_inbox = len(seen)
            for m in new:
                for sp, val in m["claims"]:
                    self.heard.append((f"agent:{m['from']}", sp, val))
            if new:
                self._cache = None

        def step(self) -> None:
            self._absorb_messages()
            if self.message and self.carried is not None:
                for k, b in enumerate(self.w.team.bodies):
                    if k != self.w.i and b.name not in self.told:
                        self.told.add(b.name)
                        claims = [(sp, self.carried.confident(sp)) for sp in self.carried.SPACES
                                  if self.carried.confident(sp)]
                        self.w.tell(b.name, f"here is what I know ({len(claims)} laws)", claims)
                        return
            super().step()

    return TeamHeuristicAgent


def run_heuristic_team(team: Team, seeds: list, rng_seed: int = 0, trust: str = "calibrated",
                       messages: bool = False) -> dict:
    """Round-robin the team's heuristic agents (one step each per round) until the board is done
    or nobody can act. Requests are split between agents by index."""
    import random

    cls = _heuristic_team_agent()
    n = len(team.bodies)
    ids = [r["id"] for r in team.w.requests]
    agents = [cls(Teammate(team, i), seeds[i], random.Random(rng_seed + i), trust=trust,
                  prefer=ids[i::n], message=messages) for i in range(n)]
    guard = 0
    while not team.done and guard < 5000:
        guard += 1
        awake = team.awake()
        if not awake:
            if any(b.asleep for b in team.bodies):
                team._maybe_night()
                continue
            break
        for i in awake:
            if team.done or team.bodies[i].asleep:
                continue
            team.activate(i)
            if team.w.out_of_budget:
                team.finish(i)
                continue
            agents[i].step()
    return team.metrics()
