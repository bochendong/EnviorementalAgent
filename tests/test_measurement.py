"""Compute-matched baselines, redundancy and reflection scoring."""
import json

from worldseeds.hive import HIVE_MODES, Hive
from worldseeds.memory import SeedMemory
from worldseeds.laws import Laws
from worldseeds.town import TownLaws, TownSeed, grow_town
from worldseeds.town.agents import TownSeedMemory
from worldseeds.town.team import Team, Teammate


def test_reflection_score_against_truth():
    laws = TownLaws.from_index(1)
    m = TownSeedMemory()
    truth = TownSeedMemory.truth(laws)
    m.reflected = [("gift_attr", truth["gift_attr"]), ("soil.melon", "nope"), ("made_up", "x"),
                   ("midday_place", [v for v in ("plaza", "shop", "home", "work") if v != truth["midday_place"]][0])]
    assert m.reflection_score(laws) == (1, 1, 2)
    assert TownSeedMemory.from_dict(m.to_dict()).reflected == m.reflected
    d = SeedMemory()
    d.reflected = [("key_match", Laws.from_index(0).key_match)]
    assert d.reflection_score(Laws.from_index(0)) == (1, 0, 0)


def test_compute_matched_solo_clock():
    s = TownSeed(laws=TownLaws.from_index(1), blocks=("farming",), board=2, surface_seed=1)
    w = grow_town(s, max_actions=600)
    team = Team(w, 1, speed=3)
    me = Teammate(team, 0)
    for _ in range(3):
        me.act("wait")
    assert w.tick == 1  # three actions per tick, like a team of three


def test_hive_serial_and_redundancy(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="board", protocol="hive", policy="heuristic", conditions=["seed"], universes=[1],
                    n_test=1, max_actions=200, n_crops=16, hive_modes=["serial", "sync"], hive_sizes=[1, 4],
                    hive_waves=2, out_dir=str(tmp_path))
    run_experiment(cfg)
    waves = [json.loads(x) for x in open(tmp_path / "hive.jsonl")]
    assert {(r["hive_mode"], r["hive_n"]) for r in waves} == {("serial", 4), ("sync", 4)}
    assert all(r["reports"] == 4 and 0 <= r["redundant_share"] <= 1 for r in waves)
    assert HIVE_MODES["serial"].serial
    assert Hive(TownSeedMemory, HIVE_MODES["serial"], 1).take_wave_stats()["reports"] == 0


def test_team_solo_matched(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="board", protocol="team", policy="heuristic", conditions=["seed"], universes=[1],
                    n_train=2, n_test=1, n_agents=2, max_actions=200, team_modes=["solo", "solo_matched"],
                    out_dir=str(tmp_path))
    run_experiment(cfg)
    rows = [json.loads(x) for x in open(tmp_path / "episodes.jsonl") if '"test"' in x]
    assert {r["variant"] for r in rows} == {"solo", "solo_matched"}
    assert all(r["team_size"] == 1 for r in rows)
