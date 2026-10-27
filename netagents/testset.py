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
    focus       the paper's main 2x2: decomposable vs sequential math, tools shared vs split across roles
    load        when does splitting the work pay? CodeWorld of 4, 8, 12 modules, the same work, tools shared
                or split among four owners
    org         a hierarchy of managers above the workers, 0-2 levels (cf. El Agente Q, Zou et al. 2025)
    faults      tool results that are silently wrong, or fail loudly; a check operation
    report      a final report with every answer, scored field by field; and a provenance rule
    guidance    the same tasks with and without procedural hints
    memory      ten episodes in a row sharing a memory in the store ("memory/" keys)
    netscale    agent-network scaling: DAG problems of known work and span (hidden functions, grain 1 and 4
                applies per task), teams of 1 to 32 identical agents, one problem for every size (fixed) or one
                as wide as the team (scaled); time in lockstep rounds, against the lower bound and the scripted
                reference (netagents/scaling.py). netscale-pilot: fixed, 1-8 agents, both grains
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
LOAD_SIZES = (4, 8, 12)
LOAD_DESIGNS = ("sas", "centralized", "decentralized")
FOCUS = [f"focus/math-{s}-{t}" for s in ("decomposable", "sequential") for t in ("shared", "split")]
FOCUS_DESIGNS = ("sas", "centralized", "decentralized")
NETSCALE_SIZES = (1, 2, 4, 8, 16, 32)
NETSCALE_PILOT = (1, 2, 4, 8)
NETSCALE_FIXED = (16, 4)  # width, depth of the fixed family
NETSCALE_DEPTH = 4  # depth of the scaled family (width = team size)
NETSCALE_GRAINS = (1, 4)  # applies per task: how much computation a task holds against sharing its answer
NETSCALE_CALLS = 3  # tool calls for the team: this many times the actions a team needs
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
    memory: bool = False  # the seeds run in order, sharing a memory file (NetConfig.memory_file)
    solo_too: bool = True  # False: single-agent designs skip this case (their solo variant is another case's)
    lockstep: bool = False  # time in synchronous rounds (netagents/lockstep.py), against the scripted reference
    calls: int = 0  # the team's tool calls (0: CALLS_PER_MEMBER per member)

    @property
    def route(self) -> str:
        """How the designs' messages travel on this case (netagents/designs.py Channel)."""
        return "framework" if self.track == "compat" else "network"

    def build(self, variant: str, **net):
        return presets.build(self.preset, variant, opt=self.opt, net_change={**self.net, **net})

    def team_size(self) -> int:
        prov, opt, _ = presets.resolve(self.preset, "team", self.opt, self.net)
        return presets.team_size(prov, opt)


def _heldout_seeds(name: str) -> list[int]:
    return presets.seeds(name, 5) if "seeds" in presets.PRESETS[name] else [0, 1, 2]  # fixed tasks: repeats


def netscale_case(family: str, n: int, seeds: list[int], grain: int = 1, width: int = 0) -> Case:
    """A team of ``n`` identical agents on a DAG problem: the fixed one, one ``n`` wide, or (family "w<width>")
    one of the given width."""
    if family == "fixed":
        width, depth = NETSCALE_FIXED
    elif family == "scaled":
        width, depth = n, NETSCALE_DEPTH
    else:
        depth = NETSCALE_DEPTH
    tasks = width * depth + 1
    # a task's actions for a team: at most one read, the applies, the submission, passing the answer on
    # and enough for every agent to keep acting through a slow run: its share of the work plus every layer's
    # applies and sharing (never binding in the pilots, which used at most 42% of their calls)
    per_agent = -(-tasks * (grain + 1) // n) + (depth + 1) * (grain + 3)
    calls = max(NETSCALE_CALLS * tasks * (grain + 3), CALLS_PER_MEMBER * n, NETSCALE_CALLS * n * per_agent)
    return Case(f"dag/{family}-g{grain}/n{n}", f"dag/{'fixed' if family == 'fixed' else 'scaled'}", seeds,
                opt={"agents": n, "width": width, "depth": depth, "grain": grain}, lockstep=True, calls=calls)


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
    # the paper's main experiment (FOCUS_DESIGNS on it): messages through the framework, as in the papers,
    # so that what changes between the columns is only who holds which tools
    "focus": [Case(p, p, TEST_SEEDS, track="compat") for p in FOCUS],
    # when is splitting the work worth it? the same work in a world of 4, 8 or 12 modules, with tools shared
    # or split among four; a single agent's runs are the same for both, so they run once (on "shared")
    "load": [Case(f"load/codeworld-m{m}-{t}", f"load/codeworld-m{m}-{t}", TEST_SEEDS, track="compat",
                  solo_too=(t == "shared")) for m in LOAD_SIZES for t in ("shared", "split")],
    "org": [Case(f"{p}/org{d}", p, TEST_SEEDS[:5], net={"org": d}) for p in ("math/medium", "codeworld/medium")
            for d in (0, 1, 2)],
    "faults": [Case(f"{p}/{name}", p, TEST_SEEDS[:5], net=net) for p in ("math/medium", "codeworld/medium")
               for name, net in (("silent", {"faults": 0.15}), ("loud", {"loud_faults": 0.15}))],
    "report": [Case("math/medium/report", "math/medium", TEST_SEEDS[:5], net={"report": True}),
               Case("math/medium/report-provenance", "math/medium", TEST_SEEDS[:5],
                    net={"report": True, "provenance": True}),
               Case("codeworld/medium/report", "codeworld/medium", TEST_SEEDS[:5], net={"report": True})],
    "guidance": [Case(f"{p}/guidance{g}", p, TEST_SEEDS[:5], net={"guidance": g})
                 for p in ("math/easy", "math/medium", "codeworld/medium") for g in (0, 1)],
    "memory": [Case(f"{p}/memory", p, TEST_SEEDS, memory=True) for p in ("math/medium", "codeworld/medium")],
    # before a GPU pilot: one single agent and one team of 8, one seed (slurm/run_all.sh STAGE=netscale-smoke)
    "netscale-smoke": [netscale_case("fixed", n, TEST_SEEDS[:1], 1) for n in (1, 8)],
    "netscale-pilot": [netscale_case("fixed", n, TEST_SEEDS[:3], g) for g in NETSCALE_GRAINS for n in NETSCALE_PILOT],
    # which open model can run the protocol at all? one agent on the fixed grain-4 problem (65 tasks), 3 seeds at
    # once (slurm/run_all.sh STAGE=netscale-screen); a model passes when it solves all 65 with b >= 0.9
    "netscale-screen": [netscale_case("fixed", 1, TEST_SEEDS[:3], 4)],
    # do agents beyond one per task help? an 8-wide problem with one agent per task (8) and two (16), and 4 and
    # 12 around them (docs/netscale-predictions.md, third prediction)
    # the interventions (designs peers-columns on 32 agents, peers-msgjoin on 16): the same cases as netscale's,
    # so that each pairs with the plain peers runs seed by seed
    "netscale-intervene": [netscale_case("fixed", n, TEST_SEEDS[:3], 4) for n in (16, 32)],
    "netscale-slack": [netscale_case("w8", n, TEST_SEEDS[:3], 4, width=8) for n in (4, 8, 12, 16)],
    "netscale": [netscale_case(f, n, TEST_SEEDS[:5], g) for g in NETSCALE_GRAINS for f in ("fixed", "scaled")
                 for n in NETSCALE_SIZES],
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
