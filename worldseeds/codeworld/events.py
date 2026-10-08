"""Random events in the town, drawn from a seed (so every organisation meets exactly the same ones).

At the start of every sprint ``Schedule.next`` draws the sprint's events and applies them to the world:

    breakdown   a machine stops working for 1-2 sprints; its master knows at once, others find out when they
                walk to it or deliver an order that needs it
    drift       a machine is re-tuned: its law changes for good; whoever learned the old law now holds a wrong
                one (its master notices; others when an order built on it comes out wrong)
    festival    one finished good is in demand: orders for it are four times as likely this sprint
    storm       walking across one outdoor map (farm, beach, mountain) costs double this sprint
    rumor       a post on the notice board about a machine, true or false (for the market)

Rates are per machine (breakdown, drift), per sprint (festival), per outdoor map (storm) and the expected
number per sprint (rumor). All zero by default: no events.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from .world import Universe


@dataclass
class EventRates:
    breakdown: float = 0.0
    drift: float = 0.0
    festival: float = 0.0
    storm: float = 0.0
    rumor: float = 0.0
    rumor_truth: float = 0.5  # share of rumours that are true

    @property
    def any(self) -> bool:
        return any((self.breakdown, self.drift, self.festival, self.storm, self.rumor))


class Schedule:
    def __init__(self, rates: EventRates, seed: int | str = 0):
        self.rates = rates
        self.seed = seed
        self.rng: random.Random | None = None

    def next(self, u: Universe, sprint: int) -> list[dict]:
        """Draw and apply this sprint's events to ``u``; returns them."""
        if self.rng is None:
            self.rng = random.Random(f"events/{self.seed}/{u.index}/{u.n_functions}")
        rng, r, out = self.rng, self.rates, []
        # repairs first, then new breakdowns
        for fn in sorted(u.broken):
            u.broken[fn] -= 1
            if u.broken[fn] <= 0:
                del u.broken[fn]
                out.append({"kind": "repaired", "fn": fn, "sprint": sprint})
        u.demand, u.storm = {}, set()
        for fn in sorted(u.functions):
            if fn not in u.broken and rng.random() < r.breakdown:
                u.broken[fn] = rng.randint(1, 2)
                out.append({"kind": "breakdown", "fn": fn, "sprints": u.broken[fn], "sprint": sprint})
            if rng.random() < r.drift:
                f = u.functions[fn]
                law = u._law(rng, .3)
                while law.table == f.law.table:
                    law = u._law(rng, .3)
                u.functions[fn] = replace(f, law=law)
                out.append({"kind": "drift", "fn": fn, "old": f.law.describe(), "new": law.describe(), "sprint": sprint})
        if r.festival and rng.random() < r.festival:
            good = rng.choice(u.types_at[u.levels - 1])
            u.demand = {good: 4.0}
            out.append({"kind": "festival", "good": good, "sprint": sprint})
        if u.map is not None:
            for a in u.map.areas:
                if a.theme != "town" and rng.random() < r.storm:
                    u.storm.add(a.name)
                    out.append({"kind": "storm", "area": a.name, "sprint": sprint})
        n = int(r.rumor) + (1 if rng.random() < r.rumor - int(r.rumor) else 0)
        for _ in range(n):
            true = rng.random() < r.rumor_truth
            pool = sorted(u.broken) if true and u.broken else sorted(set(u.functions) - set(u.broken))
            fn = rng.choice(pool)
            claim = "broken" if (true and fn in u.broken) or not true else "fine"
            out.append({"kind": "rumor", "fn": fn, "claim": claim, "true": (fn in u.broken) == (claim == "broken"),
                        "text": f"I hear the {fn.replace('.', ' ').replace('_', ' ')} is {claim}.", "sprint": sprint})
        return out
