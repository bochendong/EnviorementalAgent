"""CodeWorld: hidden laws, projects, notebooks of limited capacity, and how developers are organised."""
import json
import random

import pytest

from worldseeds.codeworld import Law, Notebook, Org, P, Universe, fit
from worldseeds.codeworld.knowledge import study_inputs


def test_laws_and_learning_them():
    aff, br = Law("affine", 5, 7), Law("branch", 5, 7, 3, 11, 2)
    assert aff(2) == 17 and br(2) == 17 and br(3) == (11 * 3 + 2) % P and br(0) == 2
    for law in (aff, br, Law("branch", 9, 1, 2, 4, 0), Law("branch", 3, 3, 5, 8, 8)):
        assert fit({x: law(x) for x in study_inputs()}).table == law.table  # the study design pins every law
    # points that never touch the edge case look affine: a law that passes what was seen, wrong elsewhere
    seen = {x: br(x) for x in (1, 2, 4, 5)}
    wrong = fit(seen)
    assert wrong is not None and wrong.kind == "affine" and wrong.table != br.table
    assert fit({1: 3, 2: 5}) is None  # too few points


def test_universe_and_projects():
    u = Universe(1, n_modules=8, fns_per_module=4)
    assert u.n_functions == 32 and len(set(u.functions)) == 32
    assert Universe(1, n_modules=8).signatures_text() == u.signatures_text()  # deterministic
    rng = random.Random(0)
    for _ in range(20):
        p = u.project(rng)
        assert u.type_checks(p.target, p.in_type, p.out_type)
        assert len({u.functions[n].module for n in p.target}) >= 2  # projects cross modules
        cands = u.candidates(p.in_type, p.out_type)
        fitting = [c for c in cands if all(u.run(c, x) == y for x, y in p.examples)]
        assert fitting and all(u.table(c) == u.table(p.target) for c in fitting)  # examples single it out
        assert p.n_candidates == len(cands) and p.text().startswith(f"Project {p.id}")


def test_notebook_capacity_and_specialists():
    nb = Notebook(2)
    for k in range(3):
        nb.put(f"m.f{k}", Law("affine", 2, k))
    assert list(nb.laws) == ["m.f1", "m.f2"] and nb.evictions == 1
    nb.put("m.f0", Law("affine", 2, 0))
    assert nb.relearned == 1
    keep = Notebook(2, keep=lambda n: n.startswith("mine."))
    keep.put("mine.a", Law("affine", 2, 1))
    keep.put("other.b", Law("affine", 2, 2))
    keep.put("other.c", Law("affine", 2, 3))
    assert "mine.a" in keep and "other.b" not in keep  # a specialist forgets foreign laws first


def test_organisations():
    u = Universe(1, n_modules=8, fns_per_module=4)
    rng = random.Random(1)
    projects = [u.project(rng) for _ in range(8)]
    solo = Org(u, 1, None, "solo")
    m = solo.sprint(projects, 10_000)
    assert m["done"] == 8 and m["spent_ask"] == 0 and m["wrong_laws"] == 0
    owners = Org(u, 4, 8, "owners")
    m = owners.sprint(projects, 10_000)
    assert m["done"] == 8 and m["spent_ask"] > 0 and m["spent_answer"] == m["spent_ask"]
    for d in owners.devs:  # owners only ever studied their own modules
        assert all(n.split(".")[0] in d.owns for n in d.notebook.ever)
    pooled = Org(u, 4, 8, "pooled")
    assert pooled.devs[0].notebook is pooled.devs[3].notebook
    poor = Org(u, 1, 4, "solo")
    m = poor.sprint(projects, 30)
    assert m["out_of_budget"] > 0 and m["done"] < 8
    with pytest.raises(ValueError):
        Org(u, 2, 8, "telepathy")


def test_core_experiment_network_beats_equal_compute_solo(tmp_path):
    from worldseeds.codeworld.experiment import CWConfig, run

    run(CWConfig(universes=[1], modules=[8], capacities=[8], team_sizes=[4], sprints=6,
                 variants=["solo", "solo_unbounded", "owners", "random"], out_dir=str(tmp_path)))
    rows = [json.loads(x) for x in open(tmp_path / "codeworld.jsonl")]
    late = {v: sum(r["done"] for r in rows if r["variant"] == v and r["sprint"] > 3) for v in
            ("solo", "solo_unbounded", "owners", "random")}
    # 32 functions, 8 laws per head: one head is too small, four heads with owners hold the world
    assert late["owners"] > late["solo"] and late["owners"] >= late["random"]
    assert late["solo_unbounded"] >= late["owners"]
    assert all(r["budget_total"] == 4 * 120 for r in rows)  # every organisation spends the same compute
