"""Ready-made experiment settings: three difficulties per provider, held-out tasks, and the variants
every comparison needs.

    from worldseeds.net.presets import build
    env = build("math/hard", variant="solo")      # -> a NetworkEnv, not reset yet

A preset is a provider, its options and a NetConfig. Difficulty grows along the same axes everywhere:
more work than one agent's budget can cover, information split across roles, a slower and less
reliable network, a world that changes, and costlier mistakes.

Variants (same total compute and the same deadline in every one):

    team    the preset as written
    solo    one agent with every tool and the whole team's budget (but, where there is a deadline, only
            the same time: a round is one action for one agent, n actions for a team of n)
    nonet   the team, with no messages, board or shared store (each works alone, in parallel)

Held-out presets (``*/heldout-*``) load tasks from ``tasks/heldout/``: problems no scripted solver was
written for, for testing whether what agents learned carries over.
"""

from __future__ import annotations

import copy
import os
from dataclasses import fields

from . import providers
from .env import NetConfig, NetworkEnv

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "tasks", "heldout")
HARD_NET = {"topology": "random", "degree": 2, "latency": 2, "outage": 0.05, "market": "claim"}

PRESETS: dict[str, dict] = {
    # ---------------------------------------------------------------- codeworld: knowledge that must travel
    "codeworld/easy": {
        "provider": "codeworld", "opt": {"n_modules": 4, "n_projects": 6, "devs": 3},
        "net": {"budget": 150},
        "note": "16 functions, 6 projects, 3 developers who can study anything."},
    "codeworld/medium": {
        "provider": "codeworld", "opt": {"n_modules": 8, "n_projects": 12, "devs": 4},
        "net": {"budget": 150, "latency": 1},
        "note": "32 functions, 12 projects: studying everything alone costs more than one budget."},
    "codeworld/hard": {
        "provider": "codeworld", "opt": {"n_modules": 8, "n_projects": 16, "owners": True, "drift": 0.005},
        "net": {"budget": 100, **HARD_NET},
        "note": "8 module owners, only owners can study their module, laws drift, sparse slow network."},
    # ---------------------------------------------------------------- math: a problem cut into lemmas
    "math/easy": {
        "provider": "math", "opt": {"problems": ["recurrence", "sum"], "explorers": 2, "algebraists": 1},
        "net": {"budget": 60},
        "note": "2 problems (6 lemmas) and a final sum."},
    "math/medium": {
        "provider": "math", "opt": {"problems": ["recurrence", "sum"] * 2, "explorers": 3, "algebraists": 2},
        "net": {"budget": 40, "latency": 1},
        "note": "4 problems (12 lemmas), a deadline; tools split between explorers and algebraists."},
    "math/hard": {
        "provider": "math", "opt": {"problems": ["recurrence", "sum"] * 4, "explorers": 4, "algebraists": 2},
        "net": {"budget": 30, "wrong_penalty": 0.2, "exclusive": True, **HARD_NET},
        "note": "8 problems (24 lemmas), tight budgets, exclusive claims, wrong answers cost reward."},
    # ---------------------------------------------------------------- website: requirements held by one person
    "website/easy": {
        "provider": "website", "opt": {}, "net": {"budget": 60},
        "note": "The shop site; the PM asks the client, frontend and backend write."},
    "website/medium": {
        "provider": "website", "opt": {"change": 0.02, "counts": {"pm": 1, "frontend": 2, "backend": 2}},
        "net": {"budget": 40, "latency": 1, "verify_cost": 2},
        "note": "Two of each developer sharing files; the client may change a price."},
    "website/hard": {
        "provider": "website", "opt": {"change": 0.05, "counts": {"pm": 1, "frontend": 2, "backend": 2}},
        "net": {"budget": 30, "verify_cost": 3, "wrong_penalty": 0.2, **HARD_NET},
        "note": "Changing client, costly submissions, sparse slow network with outages."},
    # ---------------------------------------------------------------- molecule: expensive noisy experiments
    "molecule/easy": {
        "provider": "molecule", "opt": {"noise": 0.2, "assay_cost": 3},
        "net": {"budget": 300},
        "note": "Low assay noise, cheap assays."},
    "molecule/medium": {
        "provider": "molecule", "opt": {"noise": 0.4, "assay_cost": 5, "chemists": 2, "biologists": 2},
        "net": {"budget": 200, "verify_cost": 3, "latency": 1},
        "note": "Noisier assays, two biologists to coordinate, costly submissions."},
    "molecule/hard": {
        "provider": "molecule", "opt": {"noise": 0.6, "assay_cost": 8, "tox_cost": 5, "chemists": 2,
                                        "biologists": 3},
        "net": {"budget": 160, "verify_cost": 5, "wrong_penalty": 0.5, **HARD_NET},
        "note": "Very noisy, expensive assays; every wrong submission costs."},
    # ---------------------------------------------------------------- held out: tasks no script was written for
    "math/heldout-number-theory": {
        "provider": "math", "opt": {"problem_file": os.path.join(ROOT, "math_number_theory.json"),
                                    "explorers": 2, "algebraists": 2},
        "net": {"budget": 50, "latency": 1},
        "note": "Divisor sums, a Diophantine count and modular powers."},
    "math/heldout-combinatorics": {
        "provider": "math", "opt": {"problem_file": os.path.join(ROOT, "math_combinatorics.json"),
                                    "explorers": 2, "algebraists": 2},
        "net": {"budget": 50, "latency": 1},
        "note": "Lattice paths, Catalan numbers, a tiling recurrence."},
    "website/heldout-todo": {
        "provider": "website", "opt": {"task_dir": os.path.join(ROOT, "website_todo")},
        "net": {"budget": 50, "latency": 1},
        "note": "A to-do list JSON API with rules only the client knows."},
    "molecule/heldout-kinase": {
        "provider": "molecule", "opt": {"target_file": os.path.join(ROOT, "molecule_kinase.json"), "noise": 0.4,
                                        "chemists": 2, "biologists": 1},
        "net": {"budget": 250, "verify_cost": 3},
        "seeds": list(range(1, 29)),  # every target reachable by a search over the edit space (0 and 29 are not)
        "note": "A different start (an aminopyrimidine) and a property-driven target profile."},
}

# medium and hard run against the clock: the deadline (in rounds) equals one member's budget, so each
# member has time to spend its budget, while one agent with the team's budget can only spend 1/n of it
for _name, _p in PRESETS.items():
    if _name.endswith(("/medium", "/hard")):
        _p["net"].setdefault("deadline", _p["net"]["budget"])

VARIANTS = ("team", "solo", "nonet")


def resolve(name: str, variant: str = "team") -> tuple[str, dict, dict]:
    """(provider name, provider options, NetConfig fields) for a preset and variant."""
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; known: {sorted(PRESETS)}")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; known: {VARIANTS}")
    p = copy.deepcopy(PRESETS[name])
    opt, net = p["opt"], p["net"]
    if variant == "nonet":
        net.update(messaging=False, board=False, store=False)
    elif variant == "solo":
        n = team_size(p["provider"], opt)
        net["budget"] = net.get("budget", NetConfig.budget) * n
        net["market"] = "open"
        net["exclusive"] = False
        if p["provider"] == "codeworld":
            opt.update(owners=False, devs=1)
        else:
            opt["free_roles"] = True
            opt.pop("counts", None)
            if p["provider"] == "math":
                opt.update(explorers=1, algebraists=0)
            elif p["provider"] == "molecule":
                opt.update(chemists=1, biologists=0)
            else:
                opt["counts"] = {"developer": 1}
    return p["provider"], opt, net


def seeds(name: str, n: int = 10) -> list[int]:
    """The seeds to run a preset on (a preset may list the seeds known to be solvable)."""
    return list(PRESETS[name].get("seeds", range(n)))[:n]


def team_size(provider: str, opt: dict) -> int:
    pr = providers.make(provider, **opt)
    pr.reset(0)
    return sum(r.count for r in pr.roles())


def build(name: str, variant: str = "team", **net_overrides) -> NetworkEnv:
    prov, opt, net = resolve(name, variant)
    known = {f.name for f in fields(NetConfig)}
    return NetworkEnv(providers.make(prov, **opt), NetConfig(**{k: v for k, v in {**net, **net_overrides}.items()
                                                                 if k in known}))
