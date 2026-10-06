#!/usr/bin/env python
"""Show that interventional similarity recovers universes while appearance does not."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worldseeds import ALL_BLOCKS, Laws, WorldSeed, grow  # noqa: E402
from worldseeds.similarity import interventional_similarity, observational_similarity  # noqa: E402


def main(n_per_universe=4, universes=(0, 1, 2)):
    rng = random.Random(0)
    worlds = []
    for u in universes:
        for _ in range(n_per_universe):
            s = WorldSeed(laws=Laws.from_index(u), blocks=tuple(ALL_BLOCKS), n_rooms=5,
                          surface_seed=rng.randrange(1 << 30))
            worlds.append((u, grow(s, eager=True)))
    same_i, diff_i, same_o, diff_o = [], [], [], []
    for i in range(len(worlds)):
        for j in range(i + 1, len(worlds)):
            (ui, wi), (uj, wj) = worlds[i], worlds[j]
            si, _ = interventional_similarity(wi, wj)
            so = observational_similarity(wi, wj)
            (same_i if ui == uj else diff_i).append(si)
            (same_o if ui == uj else diff_o).append(so)
    avg = lambda x: sum(x) / len(x)
    print(f"interventional similarity: same universe {avg(same_i):.2f} | different universe {avg(diff_i):.2f}")
    print(f"observational  similarity: same universe {avg(same_o):.2f} | different universe {avg(diff_o):.2f}")


if __name__ == "__main__":
    main()
