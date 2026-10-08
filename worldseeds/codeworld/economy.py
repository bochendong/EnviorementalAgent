"""Money in the town: personal purses, the town treasury, and what money buys.

Money comes from
    orders      the customer pays ``price`` for a delivered order: ``deliverer`` share to whoever delivered it,
                ``royalty`` share to the masters (owners) of the workshops whose machines were used, split per
                machine, and the rest to the treasury as tax
    bounties    the treasury pays ``bounty`` for each part of a grand goal (while it has the money)
    answers     with ``answer_price`` > 0, explaining a machine is paid for by whoever asks

and buys
    overtime    extra actions at ``overtime_price`` coins each (at most ``overtime_cap`` a sprint), only for goal
                work (it has a bounty to pay for it)
    hiring      when one's own time is up, an idle teammate takes an order for a wage of ``wage`` coins per
                action it spends; the order's pay still goes to the one who hired
    answers     (see above)
    upkeep      with ``upkeep`` > 0, food and lodging every sprint (paid to the masters of the bakery, inn,
                farm and shop); who cannot pay is tired: a quarter fewer actions that sprint

Everyone starts with ``start`` coins and the treasury with ``treasury``. Each apprentice has its own
``generosity`` (seeded): the share of its coins above ``reserve`` it gives to the treasury at the end of a
sprint when the town is raising money for a goal (the clock tower).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

FOOD = ("bakery", "inn", "farm", "shop")


@dataclass
class EconConfig:
    start: int = 50
    treasury: int = 100
    base_price: int = 6  # per order
    machine_price: int = 4  # per machine of the recipe
    deliverer: float = 0.5
    royalty: float = 0.3  # the rest is tax
    bounty: int = 25
    answer_price: int = 0
    overtime_price: int = 2
    overtime_cap: int = 30
    hiring: bool = True
    wage: int = 1
    upkeep: int = 0
    reserve: int = 30
    seed: int = 0

    def price(self, n_machines: int, demand: float = 1.0) -> int:
        return round((self.base_price + self.machine_price * n_machines) * demand)

    def generosity(self, names: list[str]) -> dict[str, float]:
        rng = random.Random(f"generosity/{self.seed}")
        return {n: round(rng.choice([0.0, 0.1, 0.3, 0.5, 0.8]), 2) for n in names}


def gini(xs) -> float:
    xs = sorted(max(0, x) for x in xs)
    n, s = len(xs), sum(xs)
    if n == 0 or s == 0:
        return 0.0
    return sum((2 * i - n + 1) * x for i, x in enumerate(xs)) / (n * s)
