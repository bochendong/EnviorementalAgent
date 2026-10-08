"""A hive: many agents exploring many worlds of one universe at once, sharing what they learn.

Modelled on how large agent swarms are organised (e.g. ~10k agents split into groups that talk
inside the group, with a separate consolidator that merges the groups' intermediate results and
sends them back out, people steering agents toward open questions, and a final verifier):

    agents      each plays its own world per *wave* (all agents play in parallel)
    groups      agents in a group share evidence right away: a group seed, read at the next wave
    consolidator  every ``sync_every`` waves the group seeds are merged into one global seed that
                every agent then sees (0 = never: groups stay on their own)
    verify      the consolidator only accepts a law once ``verify`` different agents, each from its own
                world, found the same value (replication); otherwise raw evidence is merged as it comes
    director    the next worlds are chosen to cover what the global seed is least sure about
    faulty      a share of agents report consistently wrong evidence (bad intermediate results)

An agent's view = global seed + its group's evidence that has not been consolidated yet. The
module only handles memory flow; worlds, agents and scoring come from the caller.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class HiveMode:
    name: str
    group_size: int = 1  # 0 = one group with everyone
    sync_every: int = 0  # waves between consolidations (0 = never)
    verify: int = 0  # agents that must agree before a law enters the global seed (0 = no check)
    directed: bool = False
    serial: bool = False  # one agent plays all the worlds one after another (same total experience)


HIVE_MODES = {
    "isolated": HiveMode("isolated", group_size=1, sync_every=0),
    "serial": HiveMode("serial", group_size=1, sync_every=0, serial=True),
    "groups": HiveMode("groups", group_size=4, sync_every=0),
    "hive": HiveMode("hive", group_size=4, sync_every=2),
    "sync": HiveMode("sync", group_size=0, sync_every=1),
    "hive_verified": HiveMode("hive_verified", group_size=4, sync_every=2, verify=2),
    "hive_directed": HiveMode("hive_directed", group_size=4, sync_every=2, directed=True),
    "hive_full": HiveMode("hive_full", group_size=4, sync_every=2, verify=2, directed=True),
}


class Hive:
    def __init__(self, seed_cls, mode: HiveMode, n_agents: int, faulty: float = 0.0, rng_seed: int = 0):
        self.seed_cls, self.mode, self.n = seed_cls, mode, n_agents
        gs = n_agents if mode.group_size <= 0 else max(1, mode.group_size)
        self.n_groups = math.ceil(n_agents / gs)
        self.group_of = [i // gs for i in range(n_agents)]
        self.glob = seed_cls()
        self.local = [seed_cls() for _ in range(self.n_groups)]  # evidence not yet consolidated
        rng = random.Random(rng_seed)
        self.faulty = set(rng.sample(range(n_agents), round(faulty * n_agents)))
        self.claims: dict[str, dict[str, set[int]]] = {}  # verify: space -> value -> agents who found it
        self.accepted: set[tuple[str, str]] = set()
        self.wave = 0
        # redundancy: which laws some report has already found (any value), and per-wave tallies
        self.found: set[str] = set()
        self.novel_reports = 0  # reports this wave that found at least one law nobody had found before
        self.novel_laws = 0
        self.reports = 0
        self.messages = 0  # agent->group reports + group<->consolidator exchanges
        self.syncs = 0

    # ------------------------------------------------------------ reading
    def view(self, i: int):
        """What agent ``i`` knows at the start of a wave."""
        v = self.seed_cls.from_dict(self.glob.to_dict())
        v.merge(self.local[self.group_of[i]])
        return v

    def collective(self):
        """Everything the hive has gathered, as if merged right now (an upper bound on sharing)."""
        c = self.seed_cls.from_dict(self.glob.to_dict())
        for loc in self.local:
            c.merge(loc)
        return c

    # ------------------------------------------------------------ writing
    def report(self, i: int, events) -> None:
        """Agent ``i`` finished a world: its evidence goes to its group (corrupted if it is faulty)."""
        ep = self.seed_cls()
        ep.consolidate_events(events)
        if i in self.faulty:
            ep = self._corrupt(ep, i)
        new = {sp for sp in ep.hyps if ep.confident(sp) is not None} - self.found
        self.found |= new
        self.reports += 1
        self.novel_laws += len(new)
        self.novel_reports += bool(new)
        self.local[self.group_of[i]].merge(ep)
        self.messages += 1
        if self.mode.verify:
            for sp in list(ep.hyps):
                val = ep.confident(sp)
                if val is not None:
                    self.claims.setdefault(sp, {}).setdefault(val, set()).add(i)

    def _corrupt(self, ep, i: int):
        from .town.sources import wrong_value

        bad = self.seed_cls()
        for sp, hs in ep.hyps.items():
            val = ep.confident(sp)
            if val is None:
                continue
            w = sum(h.support + h.against for h in hs.values()) / max(1, len(hs) - 1)
            try:
                bad._vote_exclusive(sp, wrong_value(sp, val, "faulty", i), max(1.0, w))
            except KeyError:
                continue
        return bad

    def take_wave_stats(self) -> dict:
        """Redundancy this wave: share of reports that added nothing new to what the hive had found."""
        out = {"reports": self.reports, "novel_laws": self.novel_laws,
               "redundant_share": 1 - self.novel_reports / self.reports if self.reports else 0.0}
        self.novel_reports = self.novel_laws = self.reports = 0
        return out

    def end_wave(self) -> None:
        self.wave += 1
        if self.mode.sync_every and self.wave % self.mode.sync_every == 0:
            self.sync()

    def sync(self) -> None:
        self.syncs += 1
        self.messages += 2 * self.n_groups
        if not self.mode.verify:
            for g, loc in enumerate(self.local):
                self.glob.merge(loc)
                self.local[g] = self.seed_cls()
            return
        # replication: a law is in the global seed while at least ``verify`` agents independently found
        # the same value AND it has a clear majority (twice the support of any other value). Rebuilt at
        # every sync, so a law accepted early is withdrawn when contrary findings outnumber it.
        self.glob = self.seed_cls()
        self.accepted = set()
        for sp, vals in self.claims.items():
            ranked = sorted(vals.items(), key=lambda kv: -len(kv[1]))
            val, agents = ranked[0]
            runner_up = len(ranked[1][1]) if len(ranked) > 1 else 0
            if len(agents) >= self.mode.verify and len(agents) >= 2 * runner_up:
                self.accepted.add((sp, val))
                self.glob._vote_exclusive(sp, val, 5.0)

    # ------------------------------------------------------------ director
    def least_known(self, candidates: list[str], k: int, rng: random.Random) -> list[str]:
        """The ``k`` crops the global seed has the least evidence about (ties broken at random)."""
        def evidence(c):
            tot = 0.0
            for sp in (f"soil.{c}", f"season.{c}"):
                if sp in self.glob.hyps:
                    tot += sum(h.support + h.against for h in self.glob.hyps[sp].values())
            return tot
        order = sorted(candidates, key=lambda c: (evidence(c), rng.random()))
        return order[:k]

    # ------------------------------------------------------------ scoring
    @staticmethod
    def score(seed, laws) -> tuple[int, int]:
        rec = seed.recovery(laws)
        return sum(v is True for v in rec.values()), sum(v is False for v in rec.values())
