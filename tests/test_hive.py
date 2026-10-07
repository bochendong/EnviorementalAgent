"""Big law spaces (many crops, long tail) and the hive: many agents in many worlds sharing memory."""
import itertools
import json
import random

from worldseeds.hive import HIVE_MODES, Hive
from worldseeds.town import TOWN_BLOCKS, TownLaws, TownSeed, grow_town
from worldseeds.town.agents import BoardHeuristicAgent, TownOracle, TownSeedMemory
from worldseeds.town.seed import town_seeds_for


def test_default_universes_unchanged():
    assert TownLaws.from_index(3) == TownLaws.from_index(3, n_crops=4)
    assert len(TownLaws.from_index(3).crops) == 4
    s = TownSeed(laws=TownLaws.from_index(3), blocks=("farming",), surface_seed=9)
    assert s.town_crops() == ["turnip", "melon", "pumpkin", "berry"]
    assert "crops" not in s.to_dict()


def test_big_universe_long_tail_and_solvable():
    laws = TownLaws.from_index(2, n_crops=40)
    assert len(laws.crops) == 40 and len(TownSeedMemory.truth(laws)) == 2 * 40 + 10
    seen = {}
    combos = [c for k in (1, 2, 3, 4) for c in itertools.combinations(TOWN_BLOCKS, k)]
    for ss in range(80):
        s = TownSeed(laws=laws, blocks=random.Random(ss).choice(combos), board=4, surface_seed=ss)
        w = grow_town(s, max_actions=10_000)
        for c in w.town_crops:
            seen[c] = seen.get(c, 0) + 1
        TownOracle(w).solve()
        assert w.done and w.day <= s.days
    assert seen.get("turnip", 0) > seen.get(laws.crops[-1], 0)  # common vs rare crops
    s = TownSeed(laws=laws, blocks=("farming",), surface_seed=1, crops=("carrot", "onion", "beet", "kale"))
    assert TownSeed.from_dict(s.to_dict()) == s


def test_seed_grows_crop_spaces():
    laws = TownLaws.from_index(1, n_crops=12)
    m = TownSeedMemory()
    m._vote_exclusive("soil.carrot", "clay", 3.0)
    assert m.confident("soil.carrot") == "clay" and m.confident("soil.onion") is None
    rt = TownSeedMemory.from_dict(m.to_dict())
    assert rt.confident("soil.carrot") == "clay"
    oracle = TownSeedMemory.certain_of(laws)
    assert all(oracle.recovery(laws).values())


def _run(mode, n, waves=4, faulty=0.0):
    laws = TownLaws.from_index(1, n_crops=32)
    combos = [c for k in (1, 2, 3, 4) for c in itertools.combinations(TOWN_BLOCKS, k)]
    hv = Hive(TownSeedMemory, HIVE_MODES[mode], n, faulty, rng_seed=1)
    for wv in range(waves):
        views = [hv.view(i) for i in range(n)]
        for i in range(n):
            rng = random.Random(wv * 100 + i)
            s = town_seeds_for([rng.choice(combos)], laws, 1, rng, board=4)[0]
            w = grow_town(s, max_actions=200)
            BoardHeuristicAgent(w, views[i], random.Random(i)).run()
            hv.report(i, w.events)
        hv.end_wave()
    return hv, laws


def test_sharing_beats_isolation():
    iso, laws = _run("isolated", 8)
    syn, _ = _run("sync", 8)
    per_agent_iso = sum(Hive.score(iso.view(i), laws)[0] for i in range(8)) / 8
    assert Hive.score(syn.view(0), laws)[0] > 2 * per_agent_iso
    assert Hive.score(syn.glob, laws)[1] == 0


def test_faulty_agents_and_verification():
    hv, laws = _run("hive", 8, faulty=0.5)
    assert hv.faulty and len(hv.faulty) == 4
    ver, _ = _run("hive_verified", 8, faulty=0.5)
    assert Hive.score(ver.glob, laws)[1] <= Hive.score(hv.glob, laws)[1]


def test_experiment_hive_protocol(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="board", protocol="hive", policy="heuristic", conditions=["seed"], universes=[1],
                    n_test=2, max_actions=200, n_crops=16, hive_modes=["isolated", "hive_full"],
                    hive_sizes=[1, 4], hive_waves=2, out_dir=str(tmp_path))
    run_experiment(cfg)
    waves = [json.loads(x) for x in open(tmp_path / "hive.jsonl")]
    assert {(r["hive_mode"], r["hive_n"]) for r in waves} == {("isolated", 1), ("isolated", 4), ("hive_full", 4)}
    assert all(r["total_laws"] == 2 * 16 + 10 for r in waves)
    eps = [json.loads(x) for x in open(tmp_path / "episodes.jsonl")]
    assert sum(r["phase"] == "test" for r in eps) == 3 * 2
    assert not any(r["phase"] == "wave" for r in eps)
