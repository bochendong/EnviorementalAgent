"""SeedVille: a Stardew-flavoured mini town grown from a World Seed.

town -> locations (farm, plaza, shop, forest, villagers' homes) -> objects
(plots, villagers, items, seed packets) -> components. Hidden universe laws decide
which soil and season each crop needs, which gifts villagers like, and where
villagers spend their middays. Time passes with every action (day/night), crops
grow overnight and villagers follow schedules: the world changes on its own.
"""

from .seed import TOWN_BLOCKS, TownLaws, TownSeed
from .world import TownWorld, grow_town

__all__ = ["TownLaws", "TownSeed", "TownWorld", "grow_town", "TOWN_BLOCKS"]
