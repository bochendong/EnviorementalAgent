"""Experiment configuration: a few top-level settings plus one group of options per topic.

    ExpConfig            protocol, env, policy, conditions, universes, sizes, output
      .llm   LLMOptions      how an LLM agent runs (turns, context, canvas, skin)
      .world WorldOptions    switches of the town family (law space, perception, realism, festival, sources)
      .learner LearnerOptions how learned memories consolidate (decay, deconfounding, publication bias, trust)
      .team  TeamOptions     team protocol
      .hive  HiveOptions     hive protocol
      .evolve EvolveOptions  evolve protocol

Every option carries its help text, and the command line is generated from these classes
(``add_arguments`` / ``from_args``), so an option is declared once. ``ExpConfig(**kw)`` also takes the
flat names used on the command line (``hive_modes=...``, ``noise=...``), so short scripts and tests can
stay flat.
"""

from __future__ import annotations

import argparse
from dataclasses import MISSING, asdict, dataclass, field, fields


def opt(default, help: str, flag: str | None = None, **kw):
    """A config field with its command-line help (and optional explicit flag, choices, nargs)."""
    meta = {"help": help, "flag": flag, **kw}
    if isinstance(default, list):
        return field(default_factory=lambda d=default: list(d), metadata=meta)
    return field(default=default, metadata=meta)


@dataclass
class LLMOptions:
    max_turns: int = opt(120, "LLM: model turns per episode")
    history_items: int = opt(40, "LLM: keep only the last N items of the transcript (0 = all)")
    context: str = opt("transcript", "LLM context: trimmed transcript, a multi-resolution memory canvas, or the "
                       "canvas as images (vision-language models)", choices=["transcript", "canvas", "image"])
    canvas_chars: int = opt(3000, "LLM: size budget of the memory canvas")
    skin: str = opt("none", "LLM: the same hidden laws told as another story (drug: compounds, targets, "
                    "protocols)", choices=["none", "drug"])


@dataclass
class WorldOptions:
    n_crops: int = opt(4, "town/board: crops per universe (law space size)")
    n_distractors: int = opt(2, "distractor objects per world")
    zoom_budget: int | None = opt(None, "town/board: close looks at new objects per day (default: free)", type=int)
    noise: float = opt(0.0, "town/board: chance a crop's night outcome flips")
    screen_error: float | None = opt(None, "town/board: enable the quick 'screen' test, wrong with this "
                                     "probability", type=float)
    confounder: bool = opt(False, "town/board: rainy nights water every plot but flood one hidden soil")
    festival: bool = opt(False, "board/team: festival requests (a cooked dish, a visit for two) and 'drop'")
    source_errors: list = opt([], "town/board: error rates of library notes and villager testimony "
                              "(one variant each)", type=float, nargs="*")


@dataclass
class LearnerOptions:
    decay: float = opt(1.0, "learned seeds: evidence decay per world (< 1 forgets; law_shift)")
    deconfound: bool = opt(False, "learned seeds set rainy nights aside (the weather confounder)")
    publication_bias: bool = opt(False, "the library hears only from towns that finished, and only successes")
    trusts: list = opt(["blind", "calibrated"], "heuristic policy only: how the agent weighs second-hand claims",
                       nargs="+", choices=["blind", "calibrated"])


TEAM_MODES = ["solo", "solo_matched", "independent", "library", "messages", "merged"]


@dataclass
class TeamOptions:
    n_agents: int = opt(4, "agents (multiagent, team)", flag="--n-agents")
    modes: list = opt(TEAM_MODES, "team protocol (board env): how teammates share what they learned",
                      flag="--team-modes", nargs="+", choices=TEAM_MODES)
    roles: bool = opt(False, "team: private perception, each teammate sees only soils, people or goods",
                      flag="--roles")


@dataclass
class HiveOptions:
    modes: list = opt(["isolated", "serial", "groups", "hive", "sync", "hive_verified", "hive_directed", "hive_full"],
                      "hive: how the agents share memory (worldseeds/hive.py)", nargs="+",
                      choices=lambda: __import__("worldseeds.hive", fromlist=["HIVE_MODES"]).HIVE_MODES)
    sizes: list = opt([1, 4, 16], "hive: numbers of agents", type=int, nargs="+")
    faulty: list = opt([0.0], "hive: shares of faulty agents", type=float, nargs="+")
    faulty_mode: str = opt("scattered", "hive: faulty agents each tell their own lie, all the same lie, or sit "
                           "in whole groups", choices=["scattered", "correlated", "groups"])
    waves: int = opt(8, "hive: worlds each agent plays")
    shift_wave: int = opt(0, "hive: wave from which laws change (0 = never)")
    shift_share: float = opt(1.0, "hive: share of the agents whose laws change (a region)")
    shift_laws: int = opt(2, "hive: law families that change")
    audit: str = opt("oracle", "hive audits: 'oracle' checks a claim against the true laws (a gold standard), "
                     "'replicate' sends an agent to test it in a world of its own (costs real episodes)",
                     choices=["oracle", "replicate"])


@dataclass
class EvolveOptions:
    generations: int = opt(8, "evolve: generations")
    pop: int = opt(8, "evolve: lives per generation")
    archive: int = opt(6, "evolve: best lives kept as parents")
    sigma: float = opt(0.15, "evolve: mutation size (share of each gene's range)")
    evaluators: list = opt(["true", "proxy"], "evolve: select on test success (true) or on claims / "
                           "self-grade (proxy, the weak evaluator)", nargs="+", choices=["true", "proxy"])
    benchmark: bool = opt(True, "evolve: after each generation, the best learner on fixed towns in every universe")
    transfer_universes: list = opt([], "evolve: unseen universes for the initial-vs-evolved comparison",
                                   flag="--transfer-universes", type=int, nargs="*")
    transfer_curve: list = opt([1, 2, 4, 8], "evolve: training towns before the transfer test",
                               flag="--transfer-curve", type=int, nargs="+")


GROUPS = {"llm": (LLMOptions, ""), "world": (WorldOptions, ""), "learner": (LearnerOptions, ""),
          "team": (TeamOptions, "team-"), "hive": (HiveOptions, "hive-"), "evolve": (EvolveOptions, "evolve-")}


@dataclass(init=False)
class ExpConfig:
    protocol: str = opt("compgen", "experiment protocol (see worldseeds/experiment)",
                        choices=lambda: __import__("worldseeds.experiment", fromlist=["x"]).PROTOCOLS)
    env: str = opt("dungeon", "environment", choices=lambda: __import__("worldseeds.envs", fromlist=["x"]).ENV_NAMES)
    policy: str = opt("llm", "who plays: an LLM agent or the heuristic agent", choices=["llm", "heuristic"])
    conditions: list = opt(["none", "retrieval", "seed", "oracle"], "memory conditions", nargs="+",
                           choices=lambda: __import__("worldseeds.agent", fromlist=["x"]).CONDITIONS)
    universes: list = opt([0, 1, 2], "universes (sets of hidden laws)", type=int, nargs="+")
    repeats: int = opt(1, "repeats per chain")
    views: list = opt(["zoom"], "zoomable or flat (everything expanded) observations", nargs="+",
                      choices=["zoom", "flat"])
    n_train: int = opt(24, "training worlds per chain")
    n_test: int = opt(16, "test worlds per chain")
    max_actions: int = opt(50, "action budget per episode")
    concurrency: int = opt(16, "episodes in flight at once")
    save_traces: bool = opt(False, "write every tool call to traces.jsonl")
    out_dir: str = opt("results/run", "output directory", flag="--out")
    rng_seed: int = opt(0, "random seed")
    llm: LLMOptions = field(default_factory=LLMOptions)
    world: WorldOptions = field(default_factory=WorldOptions)
    learner: LearnerOptions = field(default_factory=LearnerOptions)
    team: TeamOptions = field(default_factory=TeamOptions)
    hive: HiveOptions = field(default_factory=HiveOptions)
    evolve: EvolveOptions = field(default_factory=EvolveOptions)

    def __init__(self, **kw):
        for f in fields(self):
            if f.name in GROUPS:
                val = kw.pop(f.name, None)
                setattr(self, f.name, val if val is not None else GROUPS[f.name][0]())
            elif f.name in kw:
                setattr(self, f.name, kw.pop(f.name))
            else:
                setattr(self, f.name, f.default_factory() if f.default is MISSING else f.default)
        flat = flat_names()
        for k, v in kw.items():  # flat names: hive_modes=..., noise=...
            if k not in flat:
                raise TypeError(f"unknown experiment option {k!r}")
            group, name = flat[k]
            setattr(getattr(self, group), name, v)

    def to_dict(self) -> dict:
        return asdict(self)


def _flag(f, prefix: str) -> str:
    return f.metadata.get("flag") or "--" + prefix + f.name.replace("_", "-")


def flat_names() -> dict[str, tuple[str, str]]:
    """Flat option name (as on the command line, with underscores) -> (group, field)."""
    out = {}
    for group, (cls, prefix) in GROUPS.items():
        for f in fields(cls):
            out[_flag(f, prefix)[2:].replace("-", "_")] = (group, f.name)
    return out


def _add(p: argparse.ArgumentParser, f, prefix: str, dest: str) -> None:
    m = f.metadata
    flag = _flag(f, prefix)
    default = f.default_factory() if f.default is MISSING else f.default
    kw = {"dest": dest, "help": m["help"], "default": default}
    choices = m.get("choices")
    if callable(choices):
        choices = list(choices())
    if choices:
        kw["choices"] = choices
    if isinstance(default, bool):
        if default:  # a switch that is on by default is turned off with --no-...
            p.add_argument("--no-" + flag[2:], action="store_false", **kw)
        else:
            p.add_argument(flag, action="store_true", **kw)
        return
    if "nargs" in m:
        kw["nargs"] = m["nargs"]
    if not choices:
        kw["metavar"] = flag[2:].upper().replace("-", "_")
    kw["type"] = m.get("type") or (type(default) if default is not None and not isinstance(default, list) else str)
    p.add_argument(flag, **kw)


def add_arguments(p: argparse.ArgumentParser) -> None:
    for f in fields(ExpConfig):
        if f.name not in GROUPS:
            _add(p, f, "", f.name)
    for group, (cls, prefix) in GROUPS.items():
        g = p.add_argument_group(group)
        for f in fields(cls):
            _add(g, f, prefix, f"{group}.{f.name}")


def from_args(a: argparse.Namespace) -> ExpConfig:
    d = vars(a)
    groups = {g: cls(**{f.name: d[f"{g}.{f.name}"] for f in fields(cls)}) for g, (cls, _) in GROUPS.items()}
    return ExpConfig(**{f.name: d[f.name] for f in fields(ExpConfig) if f.name not in GROUPS}, **groups)
