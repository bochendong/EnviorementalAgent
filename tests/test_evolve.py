"""Self-evolving generations: genomes, the archive, the protocol, proxy vs true evaluators, transfer."""
import json
import random

from worldseeds.evolve import (GENES, Archive, Life, apply_genome, crossover, default_genome, mutate, next_genomes,
                               random_genome)
from worldseeds.town.agents import TownSeedMemory


def test_genome_operators_stay_in_range():
    rng = random.Random(0)
    g = default_genome()
    for _ in range(200):
        g = mutate(crossover(g, random_genome(rng), rng), rng, sigma=0.5)
        for k, (lo, hi, _) in GENES.items():
            assert lo <= g[k] <= hi
        assert isinstance(g["deconfound"], bool)


def test_genome_tunes_the_learner_and_survives_copies():
    m = TownSeedMemory()
    g = dict(default_genome(), thresh=0.55, min_evidence=0.25, w_fail=2.0, decay=0.9, deconfound=True)
    apply_genome(m, g)
    assert m.tuning["thresh"] == 0.55 and m.decay == 0.9 and m.deconfound
    c = TownSeedMemory.from_dict(m.to_dict())
    assert c.tuning == m.tuning and c.deconfound and c.decay == 0.9
    assert "tuning" not in TownSeedMemory().to_dict()  # default learners serialise as before
    # a lower threshold acts on weaker beliefs
    m2 = TownSeedMemory()
    m2._vote_exclusive("gift_attr", "color", 0.6)
    assert m2.confident("gift_attr") is None
    m2.tuning.update(thresh=0.55, min_evidence=0.25)
    assert m2.confident("gift_attr") == "color"


def test_archive_keeps_the_best_by_its_evaluator():
    lives = [Life({"x": i}, 0, i, proxy=float(i), true=float(-i)) for i in range(6)]
    a = Archive(3, "proxy")
    a.add(lives)
    assert [x.index for x in a.lives] == [5, 4, 3]
    b = Archive(3, "true")
    b.add(lives)
    assert b.best().index == 0
    a2 = Archive(4, "true")
    a2.add([Life(default_genome(), 0, i, true=i / 10) for i in range(4)])
    kids = next_genomes(a2, 5, random.Random(1))
    assert len(kids) == 5 and kids[0][0] == a2.best().genome and kids[0][1] == [3]


def test_evolve_protocol_heuristic(tmp_path):
    from worldseeds.experiment import ExpConfig, run_experiment

    cfg = ExpConfig(env="board", protocol="evolve", policy="heuristic", universes=[1, 2], n_train=2, n_test=2,
                    max_actions=150, noise=0.2, evolve_generations=3, evolve_pop=4, evolve_archive=3,
                    transfer_universes=[5], transfer_curve=[1, 2], out_dir=str(tmp_path))
    run_experiment(cfg)
    rows = [json.loads(x) for x in open(tmp_path / "evolve.jsonl")]
    lives = [r for r in rows if r["phase"] == "life"]
    gens = [r for r in rows if r["phase"] == "generation"]
    tr = [r for r in rows if r["phase"] == "transfer"]
    assert len(lives) == 2 * 3 * 4 and len(gens) == 2 * 3
    assert {r["universe"] for r in lives} == {1, 2}
    assert all(0 <= r["true"] <= 1 and 0 <= r["proxy"] <= 1 and r["proxy"] == r["claimed"] for r in lives)
    assert lives[0]["genome"] == default_genome()
    assert {(r["evaluator"], r["learner"], r["k_train"]) for r in tr} == {
        (e, lr, k) for e in ("true", "proxy") for lr in ("initial", "evolved") for k in (1, 2)}
    eps = [json.loads(x) for x in open(tmp_path / "episodes.jsonl")]
    assert all("generation" in r or "k_train" in r or r.get("learner") == "best" for r in eps)


def test_playbook_reaches_the_llm_instructions():
    from worldseeds.agent import EpisodeCtx, build_instructions
    from worldseeds.town import TownLaws, TownSeed, grow_town

    w = grow_town(TownSeed(laws=TownLaws.from_index(1), blocks=("farming",), surface_seed=1))
    ctx = EpisodeCtx(world=w, condition="seed", seed=TownSeedMemory(), strategy="Always zoom into plots first.")
    text = build_instructions(ctx, None, None, False)
    assert "PLAYBOOK" in text and "Always zoom into plots first." in text and "WORLD SEED" in text
