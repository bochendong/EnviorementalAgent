"""Hive robustness: correlated faulty groups (minority truth), provenance and audits, law shifts."""
import json

from worldseeds.hive import HIVE_MODES, Hive
from worldseeds.town import TownLaws
from worldseeds.town.agents import TownSeedMemory
from worldseeds.world import Event


def _night(crop, soil, season, outcome="ripe"):
    return Event(1, "night", "p1", None, outcome in ("growing", "ripe"), True, "",
                 target_attrs={"crop": crop, "soil": soil, "season": season}, effects=[{"outcome": outcome}])


def _evidence(crop, soil, season, k=3):
    return [_night(crop, soil, season) for _ in range(k)]


def test_faulty_modes():
    scattered = Hive(TownSeedMemory, HIVE_MODES["hive_verified"], 16, faulty=0.5, rng_seed=3)
    groups = Hive(TownSeedMemory, HIVE_MODES["hive_verified"], 16, faulty=0.5, rng_seed=3, faulty_mode="groups")
    assert len(scattered.faulty) == len(groups.faulty) == 8
    by_group = {}
    for i in groups.faulty:
        by_group.setdefault(groups.group_of[i], set()).add(i)
    assert all(len(v) == 4 for v in by_group.values())  # whole groups
    # correlated: every faulty agent tells the same lie
    corr = Hive(TownSeedMemory, HIVE_MODES["hive_verified"], 8, faulty=1.0, faulty_mode="correlated")
    for i in range(8):
        corr.report(i, _evidence("melon", "clay", "fall"))
    assert len(corr.claims["soil.melon"]) == 1 and "clay" not in corr.claims["soil.melon"]
    scat = Hive(TownSeedMemory, HIVE_MODES["hive_verified"], 8, faulty=1.0)
    for i in range(8):
        scat.report(i, _evidence("melon", "clay", "fall"))
    assert len(scat.claims["soil.melon"]) > 1


def _minority_truth(mode):
    """7 of 10 agents tell the same lies about three soils; 3 honest agents report the truth."""
    truth = {"soil.melon": "clay", "soil.berry": "sand", "soil.pumpkin": "loam"}
    lies = {"soil.melon": "peat", "soil.berry": "clay", "soil.pumpkin": "sand"}
    hv = Hive(TownSeedMemory, HIVE_MODES[mode], 10, faulty=0.0, truth=truth)
    for i in range(10):
        said = lies if i < 7 else truth
        hv.report(i, [e for sp, v in said.items() for e in _evidence(sp[5:], v, "fall")])
    hv.end_wave()
    hv.end_wave()  # sync
    return hv


def test_minority_truth_needs_provenance():
    v = _minority_truth("hive_verified")
    assert v.glob.confident("soil.melon") == "peat"  # the majority lie wins a plain vote
    # two audits, claim by claim: one lie is caught, the second audit confirms the truth that replaced it,
    # and the other two lies survive
    a = _minority_truth("hive_audit")
    assert a.audits == 2 and len(a.rejected) == 1
    assert sum(a.glob.confident(sp) == v for sp, v in {"soil.melon": "peat", "soil.berry": "clay",
                                                        "soil.pumpkin": "sand"}.items()) == 2
    p = _minority_truth("hive_provenance")  # one failed audit discredits everything its makers said
    assert p.distrusted == set(range(7))
    assert all(p.glob.confident(sp) == v for sp, v in p.truth.items())


def test_newer_evidence_supersedes_with_a_window():
    for mode, expect in (("hive_verified", "clay"), ("hive_recent", "sand")):
        hv = Hive(TownSeedMemory, HIVE_MODES[mode], 6)
        for i in range(4):
            hv.report(i, _evidence("melon", "clay", "fall"))
        for _ in range(4):
            hv.end_wave()
        for i in range(4, 6):  # the laws changed: two agents now see melon thrive in sand
            hv.report(i, _evidence("melon", "sand", "fall"))
        hv.end_wave()
        hv.end_wave()
        assert hv.glob.confident("soil.melon") == expect, mode


def test_shift_and_faulty_runs(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="board", protocol="hive", policy="heuristic", conditions=["seed"], universes=[1], n_test=1,
                    max_actions=150, n_crops=8, hive_modes=["sync", "hive_recent", "hive_provenance"],
                    hive_sizes=[8], hive_waves=4, hive_faulty=[0.5], hive_faulty_mode="groups",
                    hive_shift_wave=3, hive_shift_share=0.5, out_dir=str(tmp_path))
    run_experiment(cfg)
    waves = [json.loads(x) for x in open(tmp_path / "hive.jsonl")]
    assert {r["hive_mode"] for r in waves} == {"sync", "hive_recent", "hive_provenance"}
    after = [r for r in waves if r["wave"] >= 3]
    assert after and all("stale_global" in r and r["changed_laws"] > 0 for r in after)
    assert all("stale_global" not in r for r in waves if r["wave"] < 3)
    assert all(r["faulty_mode"] == "groups" for r in waves)
    assert any(r["audits"] > 0 for r in waves if r["hive_mode"] == "hive_provenance")
    assert TownLaws.from_index(1) != TownLaws.from_index(1).mutate(__import__("random").Random(0), n=2)


def test_replication_audits_play_real_worlds(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="board", protocol="hive", policy="heuristic", conditions=["seed"], universes=[1], n_test=1,
                    max_actions=150, n_crops=8, hive_modes=["hive_provenance"], hive_sizes=[8], hive_waves=4,
                    hive_faulty=[0.6], hive_faulty_mode="groups", hive_audit="replicate", out_dir=str(tmp_path))
    run_experiment(cfg)
    waves = [json.loads(x) for x in open(tmp_path / "hive.jsonl")]
    eps = [json.loads(x) for x in open(tmp_path / "episodes.jsonl")]
    audits = [r for r in eps if r["phase"] == "audit"]
    last = max(waves, key=lambda r: r["wave"])
    assert last["audit_mode"] == "replicate" and last["audits"] > 0
    assert len(audits) == last["audits"] * cfg.hive.audit_worlds  # every audit costs real episodes
    assert all("=" in r["claim"] for r in audits)
    assert last["rejected"] + last["audits_inconclusive"] <= last["audits"]


def test_fixed_season_keeps_ids():
    from worldseeds.town import TownSeed

    s = TownSeed(laws=TownLaws.from_index(1), surface_seed=5)
    assert "fixed_season" not in s.to_dict()
    from dataclasses import replace

    t = replace(s, fixed_season="winter")
    assert t.season == "winter" and t.id != s.id and TownSeed.from_dict(t.to_dict()).season == "winter"
