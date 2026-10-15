"""The test set: which settings every agent design is run on, with which seeds.

Two tracks:

    compat   the published designs' own assumptions (identical agents, no deadline, answer-checked tasks,
             messages handed over by the framework), to reproduce published findings first (HYPOTHESES)
    network  what this environment adds: tools split across roles, a shared world, topologies, latency,
             deadlines and costs; the designs' messages travel through the environment's network

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
    compat      the compatibility track: decomposable vs sequential math, CodeWorld, test seeds
    calibration easy and medium presets on dev seeds, for a few designs: is the difficulty in the range where
                designs can differ (CALIBRATION_BAND of tasks done) for the model at hand? The presets were
                tuned on scripted teams; this checks them against LLM agents before the real runs

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
EASY = ["codeworld/easy", "math/easy", "website/easy", "molecule/easy"]
CALIBRATION_BAND = (0.2, 0.8)  # mean share of tasks done in which designs can still be told apart
COMPAT = ["compat/math-decomposable", "compat/math-sequential", "compat/codeworld"]
HELDOUT = ["math/heldout-number-theory", "math/heldout-combinatorics", "website/heldout-todo",
           "molecule/heldout-kinase"]


@dataclass
class Case:
    id: str
    preset: str
    seeds: list[int]
    opt: dict = field(default_factory=dict)
    net: dict = field(default_factory=dict)
    track: str = "network"

    @property
    def route(self) -> str:
        """How the designs' messages travel on this case (netagents/designs.py Channel)."""
        return "framework" if self.track == "compat" else "network"

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
    "compat": [Case(p, p, TEST_SEEDS, track="compat") for p in COMPAT],
    "calibration": [Case(p, p, DEV_SEEDS) for p in EASY + MEDIUM]
    + [Case(p, p, DEV_SEEDS, track="compat") for p in COMPAT],
}


@dataclass(frozen=True)
class Hypothesis:
    """A published finding, as a claim about two designs on one case: ``design`` minus ``baseline`` (in
    ``metric``, paired over seeds) has the sign ``expect`` (+1 or -1)."""

    design: str
    baseline: str
    case: str
    expect: int
    source: str
    metric: str = "completion"


KIM = ("Kim et al. 2026, Towards a Science of Scaling Agent Systems, Sec. 4: on decomposable tasks (Finance-Agent) "
       "every multi-agent architecture beats the single agent (+57% to +81%); on sequential ones (PlanCraft) every "
       "one is worse (-39% to -70%)")
HYPOTHESES: list[Hypothesis] = [
    *(Hypothesis(d, "sas", "compat/math-decomposable", +1, KIM)
      for d in ("independent", "centralized", "decentralized", "hybrid")),
    *(Hypothesis(d, "sas", "compat/math-sequential", -1, KIM)
      for d in ("independent", "centralized", "decentralized", "hybrid")),
]
"""Du et al.'s finding (debate beats a single agent on GSM8K) is checked on GSM8K itself, by
netagents/fidelity.py, against the authors' own code."""
