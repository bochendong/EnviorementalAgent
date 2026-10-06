import random

from worldseeds import Laws, grow
from worldseeds.heuristic import HeuristicAgent, seed_from_laws
from worldseeds.memory import RetrievalMemory, SeedMemory
from worldseeds.seed import compositional_split, seeds_for


def test_seed_recovers_counter_intuitive_laws():
    laws = Laws(key_match="shape", fragile_material="ice", link_attr="color", push_tool="rope")
    train, _ = compositional_split(random.Random(0))
    seed = SeedMemory()
    for s in seeds_for(train, laws, 40, random.Random(1)):
        w = grow(s)
        HeuristicAgent(w, seed).run()
        seed.consolidate_events(w.events)
    rec = seed.recovery(laws)
    assert rec["key_match"] is True
    assert rec["fragile_material"] is True
    assert all(v in (True, None) for v in rec.values())  # never confidently wrong
    assert "SHAPE" in seed.render()


def test_seed_roundtrip_and_merge():
    seed = seed_from_laws(Laws())
    d = seed.to_dict()
    again = SeedMemory.from_dict(d)
    assert again.render() == seed.render()
    other = SeedMemory()
    other.merge(seed)
    assert other.confident("key_match") == "color"


def test_retrieval():
    m = RetrievalMemory(["unlock(d1, k2) -> FAIL key shape star", "smash(j1) -> OK glass jar"])
    assert "smash" in m.recall("smash jar")[0]
