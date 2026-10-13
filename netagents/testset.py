"""The test set: which settings every agent design is run on, with which seeds.

Each suite is a list of cases; a case is a preset (worldseeds/net/presets.py), optional changes to it,
and seeds. Seeds 0-2 are for development; seeds 100-109 are the test seeds and must not be used to tune a
design. Held-out cases use tasks no scripted solver was written for (tasks/heldout/).

    dev         the four providers at medium difficulty, dev seeds
    test        the same on the test seeds                         (the main table)
    hard        hard difficulty, test seeds
    heldout     the held-out tasks
    scaling     CodeWorld with 2, 4, 8, 16 developers (cf. AgentsNet, ICML 2025; MacNet, ICLR 2025)
    topology    math with full, chain, star, tree, ring and random networks (cf. MultiAgentBench, ACL 2025;
                AgentsNet)
    robustness  changing worlds and an unreliable network (cf. MAST, NeurIPS 2025 D&B)

Compute is matched (Kim et al. 2025; Tran & Kiela 2026): every design on a case gets the same total LLM
tool calls (``CALLS_PER_MEMBER`` times the team's size) and the same total environment budget (the
preset's variant); tokens are recorded for each run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from worldseeds.net import presets

DEV_SEEDS = [0, 1, 2]
TEST_SEEDS = list(range(100, 110))
CALLS_PER_MEMBER = 40
MEDIUM = ["codeworld/medium", "math/medium", "website/medium", "molecule/medium"]
HARD = ["codeworld/hard", "math/hard", "website/hard", "molecule/hard"]
HELDOUT = ["math/heldout-number-theory", "math/heldout-combinatorics", "website/heldout-todo",
           "molecule/heldout-kinase"]


@dataclass
class Case:
    id: str
    preset: str
    seeds: list[int]
    opt: dict = field(default_factory=dict)
    net: dict = field(default_factory=dict)

    def build(self, variant: str):
        return presets.build(self.preset, variant, opt=self.opt, net_change=self.net)

    def team_size(self) -> int:
        prov, opt, _ = presets.resolve(self.preset, "team", self.opt, self.net)
        return presets.team_size(prov, opt)


def _heldout_seeds(name: str) -> list[int]:
    return presets.seeds(name, 5) if "seeds" in presets.PRESETS[name] else [0, 1, 2]  # fixed tasks: repeats


SUITES: dict[str, list[Case]] = {
    "dev": [Case(p, p, DEV_SEEDS) for p in MEDIUM],
    "test": [Case(p, p, TEST_SEEDS) for p in MEDIUM],
    "hard": [Case(p, p, TEST_SEEDS) for p in HARD],
    "heldout": [Case(p, p, _heldout_seeds(p)) for p in HELDOUT],
    "scaling": [Case(f"codeworld/medium/devs{n}", "codeworld/medium", TEST_SEEDS[:5], opt={"devs": n})
                for n in (2, 4, 8, 16)],
    "topology": [Case(f"math/medium/{t}", "math/medium", TEST_SEEDS[:5], net={"topology": t})
                 for t in ("full", "chain", "star", "tree", "ring", "random")],
    "robustness": [
        Case("codeworld/medium/drift", "codeworld/medium", TEST_SEEDS[:5], opt={"drift": 0.005}),
        Case("website/medium/client-changes", "website/medium", TEST_SEEDS[:5], opt={"change": 0.05}),
        Case("math/medium/unreliable-network", "math/medium", TEST_SEEDS[:5], net={"outage": 0.1, "latency": 2}),
    ],
}
