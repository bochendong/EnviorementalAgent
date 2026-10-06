import itertools
import random

from worldseeds import ALL_BLOCKS, Laws, WorldSeed, grow
from worldseeds.oracle import Oracle, oracle_steps
from worldseeds.seed import compositional_split


def test_every_composition_is_solvable():
    rng = random.Random(0)
    for u in range(3):
        laws = Laws.from_index(u)
        for k in range(1, len(ALL_BLOCKS) + 1):
            for combo in itertools.combinations(ALL_BLOCKS, k):
                s = WorldSeed(laws=laws, blocks=combo, n_rooms=rng.randint(2, 5), n_side_rooms=rng.randint(0, 2),
                              n_goals=rng.randint(1, 3), surface_seed=rng.randrange(1 << 30))
                w = grow(s)
                while True:
                    assert oracle_steps(w) > 0
                    w.max_actions = 10_000
                    Oracle(w).solve()
                    if not w.next_goal():
                        break


def test_growth_is_deterministic_and_lazy():
    s = WorldSeed(blocks=("lockable", "machine", "fragile"), n_rooms=4, n_distractors=4, surface_seed=42)
    a, b = grow(s), grow(s)
    assert a.observe() == b.observe()
    eager = grow(s, eager=True)
    assert a.nodes_grown < eager.nodes_grown


def test_zoom_reveals_fine_attributes():
    s = WorldSeed(blocks=("lockable",), n_rooms=2, surface_seed=3)
    w = grow(s)
    key = next(o for o in w.room_objects(w.agent_room) if o.kind == "key")
    assert "shape" not in w.visible_attrs(key.id)
    w.zoom_in(key.id)
    assert "shape" in w.visible_attrs(key.id)
    w.zoom_out()
    w.zoom_out()
    assert w.focus == []


def test_decoy_key_matches_on_non_law_attributes():
    laws = Laws(key_match="shape")
    s = WorldSeed(laws=laws, blocks=("lockable",), n_rooms=2, surface_seed=5)
    w = grow(s)
    door = next(o for o in w.objs.values() if o.kind == "door" and o.lock)
    keys = [o for o in w.objs.values() if o.kind == "key" and o.critical]
    fits = [k for k in keys if w.would_unlock(k, door.lock)]
    decoys = [k for k in keys if not w.would_unlock(k, door.lock)]
    assert len(fits) == 1 and decoys
    assert decoys[0].color == door.lock["color"]  # the LLM-prior-friendly attribute is a trap


def test_persistence_carries_state():
    s = WorldSeed(blocks=("lockable", "pushable"), n_rooms=4, n_goals=2, surface_seed=9)
    w = grow(s)
    w.max_actions = 1000
    Oracle(w).solve()
    opened = {o.id for o in w.objs.values() if o.kind == "door" and o.state.get("open")}
    w.next_goal()
    assert opened == {o.id for o in w.objs.values() if o.kind == "door" and o.state.get("open")}
    assert oracle_steps(w) > 0


def test_compositional_split_is_disjoint():
    train, test = compositional_split(random.Random(0))
    assert not set(train) & set(test)
    assert set(b for c in train for b in c) == set(ALL_BLOCKS)


def test_seed_operators():
    rng = random.Random(0)
    s = WorldSeed(blocks=("lockable",))
    assert len(s.mutate(rng, "add_block").blocks) == 2
    c = s.crossover(WorldSeed(blocks=("machine",)))
    assert set(c.blocks) == {"lockable", "machine"}
    assert WorldSeed.from_dict(c.to_dict()) == c
