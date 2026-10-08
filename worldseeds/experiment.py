"""Experiment protocols. Each maps onto hypotheses/RQs of the program seed.

compgen      H4/RQ8  train on 1-2 block worlds, test on unseen 3-4 block compositions
persistence  H1/RQ1  multi-goal worlds; persistent world state vs world reset per goal
law_shift    H5/RQ7  laws change mid-stream; consolidation with/without recency decay
multiagent   RQ9     N agents explore in parallel; shared seed vs independent seeds
curriculum   RQ10    seed-mutation curriculum vs uniformly sampled training worlds

Each *chain* (universe x condition x variant x repeat) is a sequential stream of
episodes that share one memory; chains run concurrently (vLLM batches requests).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .envs import EnvSpec, get_env
from .memory import LawSeed, OracleSeed, RetrievalMemory, TrajectoryMemory

def _seed(parts) -> int:
    """Deterministic across processes (built-in hash() of str is salted per process)."""
    return int(hashlib.sha1(repr(parts).encode()).hexdigest()[:8], 16)


PROTOCOLS = ["compgen", "persistence", "law_shift", "multiagent", "curriculum", "team", "hive", "evolve"]


@dataclass
class ExpConfig:
    protocol: str = "compgen"
    env: str = "dungeon"  # dungeon | town
    policy: str = "llm"  # llm | heuristic
    conditions: list[str] = field(default_factory=lambda: ["none", "retrieval", "seed", "oracle"])
    universes: list[int] = field(default_factory=lambda: [0, 1, 2])
    repeats: int = 1
    views: list[str] = field(default_factory=lambda: ["zoom"])  # zoom | flat
    n_train: int = 24
    n_test: int = 16
    n_agents: int = 4  # multiagent
    max_actions: int = 50
    max_turns: int = 120
    concurrency: int = 16
    history_items: int = 40  # 0 = keep the full episode history in context
    # LLM context: transcript (trimmed history) | canvas (multi-resolution memory canvas + notes, text) |
    # image (the canvas rendered into pictures, for vision-language models)
    context: str = "transcript"
    canvas_chars: int = 3000
    decay: float = 1.0
    n_distractors: int = 2
    save_traces: bool = False
    # source reliability (town/board): error rates of second-hand sources, one variant per rate.
    # Empty = off (library written by an accurate librarian, no testimony). When set, library notes are
    # written by several authors with this error rate, and the ``testimony`` condition lets the agent
    # ask villagers, this share of whom are consistently wrong.
    source_errors: list[float] = field(default_factory=list)
    trusts: list[str] = field(default_factory=lambda: ["blind", "calibrated"])  # heuristic policy only
    # team protocol (board env): how teammates share what they learned while specialising
    team_modes: list[str] = field(default_factory=lambda: ["solo", "solo_matched", "independent", "library",
                                                           "messages", "merged"])
    # perception (town/board): looking closely at a new object costs attention, this much per day (None = free)
    zoom_budget: int | None = None
    # science realism (town/board): noisy experiments, a cheap noisy screen, a weather confounder, a learner
    # that sets rainy nights aside, and a library that only publishes successes from successful projects
    noise: float = 0.0
    screen_error: float | None = None
    confounder: bool = False
    deconfound: bool = False
    publication_bias: bool = False
    # LLM agents: tell the same world as another story ("drug": compounds, targets, protocols; worldseeds.skin)
    skin: str = "none"
    # festival (board; team protocol): interdependent requests (a dish cooked from a fresh crop, a visit two
    # farmers must make together) and 'drop' to hand things over; ``roles``: each teammate perceives only
    # soils (farmer), people (socialite) or goods (merchant), in training and in the team towns
    festival: bool = False
    roles: bool = False
    # law space (town/board): crops per universe; > 4 adds crops with their own soil and season laws
    n_crops: int = 4
    # hive protocol: many agents in many worlds at once sharing one memory (worldseeds/hive.py)
    hive_modes: list[str] = field(default_factory=lambda: ["isolated", "serial", "groups", "hive", "sync",
                                                           "hive_verified", "hive_directed", "hive_full"])
    hive_sizes: list[int] = field(default_factory=lambda: [1, 4, 16])
    hive_faulty: list[float] = field(default_factory=lambda: [0.0])
    hive_waves: int = 8
    # faulty agents: scattered (each its own lie) | correlated (all the same lie) | groups (same lie, whole groups)
    hive_faulty_mode: str = "scattered"
    # regional law shift: from wave ``hive_shift_wave`` (0 = never) the worlds of this share of the groups
    # follow changed laws (``hive_shift_laws`` law families mutate); the test towns follow the new laws
    hive_shift_wave: int = 0
    hive_shift_share: float = 1.0
    hive_shift_laws: int = 2
    # evolve protocol: generations of agents that inherit how to learn (worldseeds/evolve.py). A life is
    # n_train training towns then n_test test towns, from an empty head. Selection by the true evaluator
    # (test success) or the weak one (proxy: claimed knowledge / self-grade); then fresh lives in
    # ``transfer_universes`` after k training towns, for the initial vs the evolved learner.
    evolve_generations: int = 8
    evolve_pop: int = 8
    evolve_archive: int = 6
    evolve_sigma: float = 0.15
    evolve_evaluators: list[str] = field(default_factory=lambda: ["true", "proxy"])
    evolve_benchmark: bool = True  # after each generation: the best learner on fixed towns in every universe
    transfer_universes: list[int] = field(default_factory=list)
    transfer_curve: list[int] = field(default_factory=lambda: [1, 2, 4, 8])
    out_dir: str = "results/run"
    rng_seed: int = 0


class Recorder:
    def __init__(self, cfg: ExpConfig):
        self.dir = Path(cfg.out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
        self._f = open(self.dir / "episodes.jsonl", "a")
        self._t = open(self.dir / "traces.jsonl", "a") if cfg.save_traces else None
        self._h = open(self.dir / "hive.jsonl", "a") if cfg.protocol == "hive" else None
        self._e = open(self.dir / "evolve.jsonl", "a") if cfg.protocol == "evolve" else None
        self._lock = asyncio.Lock()

    async def write(self, row: dict, trace: list | None = None) -> None:
        async with self._lock:
            if row.get("phase") == "wave":  # hive summaries go to their own file
                self._h.write(json.dumps(row) + "\n")
                self._h.flush()
                return
            if row.get("phase") in ("life", "generation", "transfer"):  # evolve summaries too
                self._e.write(json.dumps(row) + "\n")
                self._e.flush()
                return
            self._f.write(json.dumps(row) + "\n")
            self._f.flush()
            if self._t is not None and trace is not None:
                self._t.write(json.dumps({"key": row["chain"], "episode": row["episode"],
                                          "variant": row.get("variant", ""), "trace": trace}) + "\n")
                self._t.flush()

    def save_seed(self, chain: str, seed: LawSeed) -> None:
        d = self.dir / "seeds"
        d.mkdir(exist_ok=True)
        (d / f"{chain}.json").write_text(json.dumps(seed.to_dict(), indent=1))


LIBRARY_CONDITIONS = ("library", "library_flat")
SOURCE_CONDITIONS = (*LIBRARY_CONDITIONS, "testimony")


class Memories:
    """All memories a chain carries across episodes."""

    def __init__(self, condition: str, laws, env: EnvSpec, decay: float = 1.0,
                 source_error: float | None = None, trust: str | None = None):
        self.condition = condition
        self.source_error, self.trust = source_error, trust
        if condition == "testimony" and env.name not in ("town", "board"):
            raise ValueError("condition 'testimony' needs env 'town' or 'board'")
        self.seed = env.seed_cls(decay=decay) if condition in ("seed", "seed_llm") else None
        self.retrieval = RetrievalMemory() if condition == "retrieval" else None
        self.traj = TrajectoryMemory() if condition == "trajectory" else None
        self.oracle = OracleSeed(laws) if condition == "oracle" else None
        # library conditions (town only): memory lives in the world, on shelves the agent must go and read.
        # ``lib_seed`` is the librarian: it consolidates each town's events and rewrites the shelves.
        self.library = self.lib_seed = None
        if condition in LIBRARY_CONDITIONS:
            if env.name not in ("town", "board"):
                raise ValueError(f"condition {condition!r} needs env 'town' or 'board'")
            from .town.library import LibraryArchive

            self.library = LibraryArchive(mode="flat" if condition == "library_flat" else "categorized")
            self.lib_seed = env.seed_cls(decay=decay)
        self.laws = laws
        self.strategy: str | None = None  # evolve protocol, llm policy: the inherited playbook

    def set_laws(self, laws) -> None:
        self.laws = laws
        if self.oracle is not None:
            self.oracle = OracleSeed(laws)


class Runner:
    def __init__(self, cfg: ExpConfig):
        self.cfg = cfg
        self.env = get_env(cfg.env)
        self.rec = Recorder(cfg)
        self.sem = asyncio.Semaphore(cfg.concurrency)
        self.model = self.settings = None
        if cfg.policy == "llm":
            from .llm import LLMConfig, make_model, make_settings

            lc = LLMConfig()
            self.model = make_model(lc)
            self.settings = make_settings(lc)
            self.cons_settings = make_settings(lc, tool_choice=None)  # consolidator has no tools
            self.llm_name = lc.model
        else:
            self.llm_name = "heuristic"

    # ------------------------------------------------------------ one episode
    async def play(self, world, mem: Memories, chain: str, episode: int, phase: str,
                   variant: str = "", learn: bool = True, extra: dict | None = None, oracle: bool = True,
                   write: bool = True, traces: list | None = None) -> dict:
        cond = mem.condition
        opt = None
        if oracle:
            try:
                opt = self.env.oracle_steps(world)
            except Exception:
                opt = None
        reads0 = mem.library.reads if mem.library is not None else 0
        lib0 = mem.library.to_dict() if mem.library is not None else None  # shelves as the agent found them
        hkw = {"trust": mem.trust} if mem.trust else {}
        async with self.sem:
            if self.cfg.policy == "heuristic":
                sd = mem.seed if cond in ("seed", "seed_llm") else (
                    self.env.seed_cls.certain_of(mem.laws) if cond == "oracle" else None)
                metrics, trace = self.env.heuristic(world, sd, random.Random(episode), **hkw).run(), None
                # (library conditions: sd is None and the agent fills its head by reading the shelves)
            else:
                from .agent import run_episode

                metrics, ctx = await run_episode(
                    world, cond, self.model, self.settings, seed=mem.seed, retrieval=mem.retrieval,
                    traj=mem.traj, oracle=mem.oracle, library=mem.library, max_turns=self.cfg.max_turns,
                    history_items=self.cfg.history_items, context=self.cfg.context,
                    canvas_chars=self.cfg.canvas_chars, skin=self.cfg.skin, strategy=mem.strategy,
                )
                trace = ctx.trace
        if learn:
            await self.consolidate(world, mem, chain, episode)
        row = {
            "protocol": self.cfg.protocol, "env": self.env.name, "policy": self.cfg.policy, "llm": self.llm_name,
            "context": self.cfg.context, "skin": self.cfg.skin,
            "chain": chain, "condition": cond, "view": "flat" if world.eager else "zoom",
            "variant": variant, "phase": phase, "episode": episode,
            "seed_id": world.seed.id, "seed": world.seed.to_dict(), "composition": world.seed.composition,
            "n_blocks": len(world.seed.blocks), "n_rooms": world.seed.n_rooms,
            "goal_index": world.goal_index, "oracle_steps": opt, **metrics,
            **({"perception_spent": world.perception_spent, "zoom_budget": world.zoom_budget}
               if getattr(world, "zoom_budget", None) is not None else {}),
            **({"screens": world.screens} if getattr(world, "screen_error", None) is not None else {}),
            "time": time.time(), **(extra or {}),
        }
        if mem.seed is not None:
            rec = mem.seed.recovery(mem.laws)
            known = [v for v in rec.values() if v is not None]
            row["seed_laws_confident"] = len(known)
            row["seed_laws_correct"] = sum(1 for v in known if v)
            row["seed_rules"] = len(mem.seed.rules)
            if mem.seed.reflected:
                ok, bad, inv = mem.seed.reflection_score(mem.laws)
                row["reflection_correct"], row["reflection_wrong"], row["reflection_invalid"] = ok, bad, inv
        if mem.library is not None:
            correct, scored = mem.library.accuracy(self.env.seed_cls.truth(mem.laws))
            row["library_reads"] = mem.library.reads - reads0
            row["library_entries"] = len(mem.library.entries)
            row["library_notes"] = sum(1 for e in mem.library.entries if e.source == "note")
            row["library_claims_correct"], row["library_claims"] = correct, scored
            row["library"] = lib0
        if mem.source_error is not None:
            row["source_error"], row["trust"] = mem.source_error, mem.trust or "llm"
        if getattr(world, "testimony", None) is not None:
            asks = [e for e in world.events if e.verb == "ask" and e.valid and e.effects]
            row["asks"] = len(asks)
            row["heard_claims"] = sum(len(e.effects[0]["claims"]) for e in asks)
            row["heard_wrong"] = sum(e.effects[0]["wrong"] for e in asks)
        if write:
            await self.rec.write(row, trace)
        if traces is not None:
            traces.append(trace or [])
        return row

    async def consolidate(self, world, mem: Memories, chain: str, episode: int) -> None:
        tag = f"world{episode}"
        if mem.seed is not None:
            mem.seed.consolidate_events(world.events)
            mem.seed.worlds_seen += 1
            if mem.condition == "seed_llm" and self.model is not None:
                from .agent import llm_consolidate

                lines = "\n".join(ev.line() for ev in world.events if ev.valid)[-6000:]
                await llm_consolidate(mem.seed, lines, self.model, self.cons_settings)
        if mem.library is not None:
            if self.cfg.publication_bias:  # only successful projects publish, and only their positive results
                if world.done:
                    mem.lib_seed.consolidate_events([e for e in world.events if e.success])
            else:
                mem.lib_seed.consolidate_events(world.events)
            mem.lib_seed.worlds_seen += 1
            if mem.source_error is None:
                mem.library.update_from_seed(mem.lib_seed, episode, author="librarian")
            else:
                from .town.sources import NOTE_AUTHORS

                mem.library.write_notes(mem.lib_seed, episode, {a: mem.source_error for a in NOTE_AUTHORS})
        if mem.retrieval is not None:
            mem.retrieval.add_events(world.events, tag)
        if mem.traj is not None:
            mem.traj.add_events(world.events, tag)

    def _env_kw(self) -> dict:
        """World options that only the town family understands."""
        c = self.cfg
        if self.env.name == "dungeon":
            return {}
        kw = {"zoom_budget": c.zoom_budget} if c.zoom_budget is not None else {}
        if c.noise:
            kw["noise"] = c.noise
        if c.festival and self.env.name == "board":
            kw["festival"] = True
        if c.screen_error is not None:
            kw["screen_error"] = c.screen_error
        if c.confounder:
            kw["confounder"] = True
        return kw

    def _grow(self, s, view: str, mem: Memories | None = None):
        kw = {"library": mem.library} if mem is not None and mem.library is not None else {}
        kw.update(self._env_kw())
        if mem is not None and mem.condition == "testimony":
            kw["testimony"] = mem.source_error or 0.0
        return self.env.grow(s, eager=(view == "flat"), max_actions=self.cfg.max_actions, **kw)

    def _laws(self, u: int):
        if self.cfg.n_crops != 4:
            return self.env.laws(u, n_crops=self.cfg.n_crops)
        return self.env.laws(u)

    def _mem(self, cond, laws, decay=None, src=None) -> Memories:
        err, trust = src if src else (None, None)
        m = Memories(cond, laws, self.env, self.cfg.decay if decay is None else decay, err, trust)
        for sd in (m.seed, m.lib_seed):
            if sd is not None and hasattr(sd, "deconfound"):
                sd.deconfound = self.cfg.deconfound
        return m

    def _chains(self):
        c = self.cfg
        conds = c.conditions
        if c.policy == "heuristic":
            conds = [x for x in conds if x in ("none", "seed", "oracle", *SOURCE_CONDITIONS)]
        if c.env not in ("town", "board"):
            conds = [x for x in conds if x not in SOURCE_CONDITIONS]
        if not c.source_errors:
            conds = [x for x in conds if x != "testimony"]
        if c.protocol == "evolve":  # one evolution over all universes (a generation lives in one of them)
            for view in c.views:
                for r in range(c.repeats):
                    for ev in c.evolve_evaluators:
                        yield (ev, "seed", view, r)
            return
        for u in c.universes:
            for cond in conds:
                srcs = [None]
                if cond in SOURCE_CONDITIONS and c.source_errors:
                    trusts = c.trusts if c.policy == "heuristic" else [None]
                    srcs = [(e, t) for e in c.source_errors for t in trusts]
                for src in srcs:
                    for view in c.views:
                        for r in range(c.repeats):
                            yield (u, cond, view, r, src) if c.protocol == "compgen" else (u, cond, view, r)

    # ------------------------------------------------------------ protocols
    async def compgen_chain(self, u, cond, view, r, src=None):
        c = self.cfg
        laws = self._laws(u)
        rng = random.Random(_seed((c.rng_seed, u, r)))
        train, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        tr = self.env.seeds_for(train, laws, c.n_train, rng, n_distractors=c.n_distractors)
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(c.rng_seed * 7 + u * 31 + r),
                       n_distractors=c.n_distractors)
        mem = self._mem(cond, laws, src=src)
        variant = "" if src is None else f"err{src[0]:g}" + (f"-{src[1]}" if src[1] else "")
        chain = f"{self.env.name}-compgen-u{u}-{cond}-{view}-r{r}" + (f"-{variant}" if variant else "")
        ep = 0
        # testimony carries nothing between towns: there is nothing to train
        for s in (tr if cond != "testimony" else []):
            await self.play(self._grow(s, view, mem), mem, chain, ep, "train", variant=variant)
            ep += 1
        for s in te:
            await self.play(self._grow(s, view, mem), mem, chain, ep, "test", variant=variant, learn=False)
            ep += 1
        if mem.seed:
            self.rec.save_seed(chain, mem.seed)

    async def persistence_chain(self, u, cond, view, r):
        c = self.cfg
        laws = self._laws(u)
        rng = random.Random(_seed(("persist", c.rng_seed, u, r)))
        combos = [tuple(rng.sample(self.env.blocks, 3)) for _ in range(c.n_test)]
        seeds = [self.env.make_seed(laws, cb, rng, n_goals=3, n_distractors=c.n_distractors, big=True)
                 for cb in combos]
        for variant in ("persistent", "reset"):
            mem = self._mem(cond, laws)
            chain = f"{self.env.name}-persistence-u{u}-{cond}-{view}-{variant}-r{r}"
            ep = 0
            for s in seeds:
                world = self._grow(s, view, mem)
                for g in range(s.n_goals):
                    if variant == "reset":
                        world = self._grow(s, view, mem)
                        world.goal_index = g
                    await self.play(world, mem, chain, ep, f"goal{g}", variant=variant)
                    ep += 1
                    if variant == "persistent":
                        world.next_goal(reset_agent=True)

    async def law_shift_chain(self, u, cond, view, r):
        c = self.cfg
        laws_a = self._laws(u)
        laws_b = laws_a.mutate(random.Random(u * 13 + 7), n=2)
        rng = random.Random(_seed(("shift", c.rng_seed, u, r)))
        train, _ = self.env.split(random.Random(u))
        for variant, decay in (("no_decay", 1.0), ("decay", c.decay if c.decay < 1 else 0.7)):
            if cond not in ("seed", "seed_llm") and variant != "no_decay":
                continue
            mem = self._mem(cond, laws_a, decay)
            chain = f"{self.env.name}-law_shift-u{u}-{cond}-{view}-{variant}-r{r}"
            ep = 0
            for phase, laws, n in (("before", laws_a, c.n_train), ("after", laws_b, c.n_train)):
                mem.set_laws(laws)
                for s in self.env.seeds_for(train, laws, n, rng, n_distractors=c.n_distractors):
                    await self.play(self._grow(s, view, mem), mem, chain, ep, phase, variant=variant)
                    ep += 1

    async def multiagent_chain(self, u, cond, view, r):
        c = self.cfg
        if cond not in ("seed", "seed_llm"):
            return
        laws = self._laws(u)
        rng = random.Random(_seed(("multi", c.rng_seed, u, r)))
        train, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        rounds = max(1, c.n_train // c.n_agents)
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(u * 31 + r), n_distractors=c.n_distractors)
        for variant in ("shared", "independent"):
            shared = self._mem(cond, laws)
            mems = [shared] * c.n_agents if variant == "shared" else [self._mem(cond, laws) for _ in range(c.n_agents)]
            chain = f"{self.env.name}-multiagent-u{u}-{cond}-{view}-{variant}-r{r}"
            ep = 0
            for rd in range(rounds):
                # Agents specialise: agent a explores worlds containing its "home" block, so a
                # shared seed can hand an agent laws it has never experienced itself (section 15).
                seeds = []
                for a in range(c.n_agents):
                    home = self.env.blocks[a % len(self.env.blocks)]
                    combo = rng.choice([cb for cb in train if home in cb])
                    seeds += self.env.seeds_for([combo], laws, 1, rng, n_distractors=c.n_distractors)
                worlds = [self._grow(s, view) for s in seeds]
                # play in parallel *without* learning, then consolidate the round (avoids races)
                await asyncio.gather(*[
                    self.play(w, mems[a], chain, ep + a, "train", variant=variant, learn=False,
                              extra={"agent": a, "round": rd})
                    for a, w in enumerate(worlds)
                ])
                for a, w in enumerate(worlds):
                    await self.consolidate(w, mems[a], chain, ep + a)
                ep += c.n_agents
            # evaluate agent 0's seed (shared: the collective one) on unseen compositions
            for s in te:
                await self.play(self._grow(s, view), mems[0], chain, ep, "test", variant=variant, learn=False,
                                extra={"agent": 0, "train_worlds_total": rounds * c.n_agents})
                ep += 1

    async def curriculum_chain(self, u, cond, view, r):
        c = self.cfg
        laws = self._laws(u)
        rng = random.Random(_seed(("curr", c.rng_seed, u, r)))
        _, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(u * 31 + r), n_distractors=c.n_distractors)
        for variant in ("curriculum", "uniform"):
            mem = self._mem(cond, laws)
            chain = f"{self.env.name}-curriculum-u{u}-{cond}-{view}-{variant}-r{r}"
            seed = self.env.make_seed(laws, (rng.choice(self.env.blocks),), rng, n_distractors=c.n_distractors)
            ep = 0
            for _ in range(c.n_train):
                if variant == "uniform":
                    k = rng.randint(1, min(4, len(self.env.blocks)))
                    blocks = tuple(rng.sample(self.env.blocks, k))
                    seed = self.env.make_seed(laws, blocks, rng, n_distractors=c.n_distractors)
                row = await self.play(self._grow(seed, view, mem), mem, chain, ep, "train", variant=variant,
                                      extra={"curriculum_blocks": len(seed.blocks)})
                ep += 1
                if variant == "curriculum":
                    # z' = Mutate(z): harder after success, new surface/recombination after failure
                    kind = "add_block" if row["success"] else rng.choice(["surface", "drop_block"])
                    seed = seed.mutate(rng, kind)
                    if kind == "add_block":
                        seed = seed.mutate(rng, "surface")
                    seed = self.env.normalize(seed)
            for s in te:
                await self.play(self._grow(s, view, mem), mem, chain, ep, "test", variant=variant, learn=False)
                ep += 1

    async def team_chain(self, u, cond, view, r):
        """Specialise, then work one town board together. Each of ``n_agents`` agents first plays its own
        towns containing its "home" block (agent a: block a), learning its own seed. Then every test town
        is played once per sharing mode:
            solo         agent 0 alone
            solo_matched agent 0 alone with the whole team's compute (the compute-matched baseline)
            independent  the whole team, each with its own seed, no communication
            library      + everyone's seed written to the library as signed notes (go there to read)
            messages     + teammates can message each other (tell)
            merged       everyone carries the merged seed of the team (sharing upper bound)"""
        c = self.cfg
        if cond not in ("seed", "seed_llm") or self.env.name != "board":
            return
        from .town.team import TEAM_NAMES

        laws = self._laws(u)
        rng = random.Random(_seed(("team", c.rng_seed, u, r)))
        train, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        n = max(2, min(c.n_agents, len(TEAM_NAMES)))
        rounds = max(1, c.n_train // n)
        mems = [self._mem(cond, laws) for _ in range(n)]
        chain = f"{self.env.name}-team-u{u}-{cond}-{view}-r{r}"
        ep = 0
        for rd in range(rounds):
            seeds = []
            for a in range(n):
                home = self.env.blocks[a % len(self.env.blocks)]
                combo = rng.choice([cb for cb in train if home in cb])
                seeds += self.env.seeds_for([combo], laws, 1, rng, n_distractors=c.n_distractors)
            worlds = [self._grow(s, view) for s in seeds]
            if c.roles:  # each specialist only perceives its own kind of detail, in its own towns too
                from .town.team import PERCEIVES, ROLES

                for a, w in enumerate(worlds):
                    w.perceives = PERCEIVES[ROLES[a % len(ROLES)]]
            await asyncio.gather(*[
                self.play(w, mems[a], chain, ep + a, "train", variant=f"agent{a}",
                          extra={"agent": a, "round": rd, **({"role": ROLES[a % len(ROLES)]} if c.roles else {})})
                for a, w in enumerate(worlds)])
            ep += n
        for a, m in enumerate(mems):
            self.rec.save_seed(f"{chain}-agent{a}", m.seed)
        merged = self.env.seed_cls.from_dict(mems[0].seed.to_dict())
        for m in mems[1:]:
            merged.merge(m.seed)
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(c.rng_seed * 7 + u * 31 + r),
                                n_distractors=c.n_distractors)
        for s in te:
            await asyncio.gather(*[self.play_team(s, view, [m.seed for m in mems], merged, mode, chain, ep, laws)
                                   for mode in c.team_modes])
            ep += 1

    async def play_team(self, s, view, seeds, merged, mode, chain, ep, laws) -> dict:
        from .town.library import LibraryArchive
        from .town.team import TEAM_NAMES, Team, Teammate, run_heuristic_team

        c = self.cfg
        n = 1 if mode in ("solo", "solo_matched") else len(seeds)
        # solo_matched: one agent with the whole team's compute (team-size actions per tick, team-size budget)
        matched = len(seeds) if mode == "solo_matched" else 1
        lib = None
        if mode == "library":
            lib = LibraryArchive()
            for a in range(n):
                lib.write_notes(seeds[a], ep, {TEAM_NAMES[a]: 0.0})
        world = self.env.grow(s, eager=(view == "flat"), max_actions=c.max_actions * matched, library=lib,
                              **self._env_kw())
        team = Team(world, n, messages=(mode == "messages"), speed=matched if matched > 1 else 0, roles=c.roles)
        carried = [merged] * n if mode == "merged" else seeds[:n]
        try:
            opt = self.env.oracle_steps(world.clone())
        except Exception:
            opt = None
        team.activate(0)
        tokens = [0, 0]
        async with self.sem:
            if c.policy == "heuristic":
                metrics = run_heuristic_team(team, carried, rng_seed=ep, messages=(mode == "messages"))
                traces = None
            else:
                from .agent import run_episode

                outs = await asyncio.gather(*[
                    run_episode(Teammate(team, i), "seed", self.model, self.settings, seed=carried[i],
                                max_turns=c.max_turns * matched, history_items=c.history_items,
                                context=c.context, canvas_chars=c.canvas_chars, skin=c.skin)
                    for i in range(n)])
                metrics = team.metrics()
                for m, _ in outs:
                    tokens[0] += m["input_tokens"]
                    tokens[1] += m["output_tokens"]
                traces = [{"agent": TEAM_NAMES[i], "trace": ctx.trace} for i, (_, ctx) in enumerate(outs)]
                metrics["status"] = ",".join(m["status"] for m, _ in outs)
        row = {
            "protocol": "team", "env": self.env.name, "policy": c.policy, "llm": self.llm_name, "chain": chain,
            "condition": "seed", "view": view, "variant": mode, "phase": "test", "episode": ep,
            "seed_id": s.id, "seed": s.to_dict(), "composition": s.composition, "n_blocks": len(s.blocks),
            "n_rooms": s.n_rooms, "goal_index": 0, "oracle_steps": opt,
            "actions": metrics["team_actions"], "invalid_actions": metrics["team_invalid_actions"],
            "zoom_ops": 0, "nodes_grown": world.nodes_grown, "input_tokens": tokens[0], "output_tokens": tokens[1],
            "status": metrics.get("status", "finished"), "error": None, "time": time.time(),
            "library_reads": lib.reads if lib is not None else None, "festival": c.festival, "roles_on": c.roles,
            **metrics,
        }
        await self.rec.write(row, traces)
        return row

    # ------------------------------------------------------------ hive
    async def hive_chain(self, u, cond, view, r):
        """Many agents, many worlds, one memory: every (mode, size, faulty share) is one hive run."""
        c = self.cfg
        if cond not in ("seed", "seed_llm") or self.env.name not in ("town", "board"):
            return
        laws = self._laws(u)
        _, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(_seed(("hive-test", c.rng_seed, u, r))),
                                n_distractors=c.n_distractors)
        runs = [(m, n, f) for m in c.hive_modes for n in c.hive_sizes for f in c.hive_faulty
                if (n > 1 or m == "isolated") and not (m == "serial" and (n == 1 or f))]
        await asyncio.gather(*[self.hive_run(u, view, r, laws, m, n, f, te) for m, n, f in runs])

    async def hive_run(self, u, view, r, laws, mode, n, faulty, te) -> None:
        import itertools
        from dataclasses import replace

        from .hive import HIVE_MODES, Hive

        c = self.cfg
        truth_a = self.env.seed_cls.truth(laws)
        laws_b = laws.mutate(random.Random(_seed(("hive-shift", c.rng_seed, u))), n=c.hive_shift_laws) \
            if c.hive_shift_wave else laws
        truth_b = self.env.seed_cls.truth(laws_b)
        hv = Hive(self.env.seed_cls, HIVE_MODES[mode], n, faulty, rng_seed=_seed(("hive", c.rng_seed, u, r, n, faulty)),
                  faulty_mode=c.hive_faulty_mode, truth=truth_a)
        # regional shift: the first ``share`` of the agents (whole groups, as groups are consecutive) live under
        # the new laws
        moved_agents = set(range(round(c.hive_shift_share * n))) if c.hive_shift_wave else set()

        def region_laws(i: int, wv: int):
            shifted = c.hive_shift_wave and wv + 1 >= c.hive_shift_wave and i in moved_agents
            return laws_b if shifted else laws
        combos = [cb for k in range(1, len(self.env.blocks) + 1) for cb in itertools.combinations(self.env.blocks, k)]
        variant = f"{mode}-n{n}" + (f"-f{faulty:g}" if faulty else "") + (
            f"-{c.hive_faulty_mode}" if faulty and c.hive_faulty_mode != "scattered" else "") + (
            f"-shift{c.hive_shift_wave}x{c.hive_shift_share:g}" if c.hive_shift_wave else "")
        chain = f"{self.env.name}-hive-u{u}-{variant}-{view}-r{r}"
        total = len(self.env.seed_cls.truth(laws))
        ep = 0
        tag = {"hive_mode": mode, "hive_n": n, "faulty": faulty, "faulty_mode": c.hive_faulty_mode,
               "shift_wave": c.hive_shift_wave, "shift_share": c.hive_shift_share if c.hive_shift_wave else 0}
        for wv in range(c.hive_waves):
            if c.hive_shift_wave and wv + 1 == c.hive_shift_wave and c.hive_shift_share >= 1:
                hv.truth, hv.checked = truth_b, set()  # audits now replicate under the new laws
            seeds = []
            for i in range(n):  # the same worlds for every mode (unless a director picks them)
                rng = random.Random(_seed(("hive-world", c.rng_seed, u, r, wv, i)))
                s = self.env.seeds_for([rng.choice(combos)], region_laws(i, wv), 1, rng,
                                       n_distractors=c.n_distractors)[0]
                if hv.mode.directed and laws.crops:
                    blocks = tuple(b for b in self.env.blocks if b in set(s.blocks) | {"farming"})
                    s = replace(s, blocks=blocks, crops=tuple(hv.least_known(laws.crops, 4, rng)))
                seeds.append(s)
            worlds = [self._grow(s, view) for s in seeds]
            write = c.policy == "llm" or n <= 16  # big heuristic hives: wave summaries only
            if hv.mode.serial:  # one agent plays the wave's n worlds one after another, learning as it goes
                rows = []
                for k, w in enumerate(worlds):
                    m = self._mem("seed", laws)
                    m.seed = hv.view(0)
                    rows.append(await self.play(w, m, chain, ep + k, "train", variant=variant, learn=False,
                                                oracle=False, extra={**tag, "agent": 0, "wave": wv}, write=write))
                    hv.report(0, w.events)
            else:
                mems = []
                for i in range(n):
                    m = self._mem("seed", laws)
                    m.seed = hv.view(i)
                    mems.append(m)
                rows = await asyncio.gather(*[
                    self.play(w, mems[i], chain, ep + i, "train", variant=variant, learn=False, oracle=False,
                              extra={**tag, "agent": i, "wave": wv, "agent_faulty": i in hv.faulty}, write=write)
                    for i, w in enumerate(worlds)])
                for i, w in enumerate(worlds):
                    hv.report(i, w.events)
            stats = hv.take_wave_stats()
            hv.end_wave()
            ep += n
            agents = [0] if hv.mode.serial else range(0, n, max(1, n // 32))  # a sample of agents
            known = [Hive.score(hv.view(i), region_laws(i, wv)) for i in agents]
            shift_stats = {}
            if c.hive_shift_wave and wv + 1 >= c.hive_shift_wave:
                moved = [i for i in agents if region_laws(i, wv) is laws_b and laws_b is not laws]
                cur = truth_b if c.hive_shift_share >= 1 and wv + 1 >= c.hive_shift_wave else truth_a
                shift_stats = {
                    "stale_global": hv.stale(hv.glob, truth_a, truth_b),
                    "stale_agents": (sum(hv.stale(hv.view(i), truth_a, truth_b) for i in moved) / len(moved)
                                     if moved else 0.0),
                    "changed_laws": sum(1 for sp in truth_a if truth_a[sp] != truth_b.get(sp)),
                    "known_global_now": sum(1 for sp, v in cur.items() if sp in hv.glob.hyps
                                            and hv.glob.confident(sp) == v),
                }
            await self.rec.write({
                "protocol": "hive", "phase": "wave", "env": self.env.name, "policy": c.policy, "llm": self.llm_name,
                "chain": chain, "variant": variant, "universe": u, "repeat": r, **tag, "wave": wv + 1,
                "episodes": ep, "total_laws": total,
                "known_agents": sum(k for k, _ in known) / len(known),
                "wrong_agents": sum(x for _, x in known) / len(known),
                "known_global": Hive.score(hv.glob, laws)[0], "wrong_global": Hive.score(hv.glob, laws)[1],
                "known_collective": Hive.score(hv.collective(), laws)[0],
                "wrong_collective": Hive.score(hv.collective(), laws)[1],
                "messages": hv.messages, "syncs": hv.syncs, **stats, **shift_stats,
                "audits": hv.audits, "distrusted": len(hv.distrusted), "rejected": len(hv.rejected),
                "wave_success": sum(bool(x["success"]) for x in rows) / n,
                **({"wave_board": sum(x["board_done"] / x["board_total"] for x in rows) / n}
                   if rows and rows[0].get("board_total") else {}),
            })
        # what the hive hands to a newcomer: the global seed, or (never consolidated) one merge at the end
        shared = hv.glob if hv.mode.sync_every else hv.collective()
        test_laws = laws_b if c.hive_shift_wave else laws
        m = self._mem("seed", test_laws)
        m.seed = shared
        if c.hive_shift_wave:  # the newcomer arrives in the changed land
            te = self.env.seeds_for(self.env.split(random.Random(c.rng_seed * 1000 + u))[1], laws_b, c.n_test,
                                    random.Random(_seed(("hive-test", c.rng_seed, u, r))),
                                    n_distractors=c.n_distractors)
        for s in te:
            await self.play(self._grow(s, view), m, chain, ep, "test", variant=variant, learn=False,
                            extra={**tag, "shared_known": Hive.score(shared, test_laws)[0],
                                   "shared_wrong": Hive.score(shared, test_laws)[1], "total_laws": total})
            ep += 1

    # ------------------------------------------------------------ evolve
    def _score(self, row: dict) -> float:
        return row["board_done"] / row["board_total"] if row.get("board_total") else float(bool(row["success"]))

    async def _life(self, genome, u: int, towns, view: str, chain: str, ep0: int, tag: dict) -> tuple[dict, int]:
        """One life from an empty head: train towns, then test towns. Returns (summary, next episode id)."""
        from .evolve import apply_genome, life_summary, mentor

        laws = self._laws(u)
        mem = self._mem("seed", laws)
        if isinstance(genome, dict):
            apply_genome(mem.seed, genome)
        else:
            mem.strategy = genome
        tr, te = towns
        rows, traces, ep = [], [], ep0
        for s in tr:
            rows.append(await self.play(self._grow(s, view, mem), mem, chain, ep, "train", variant=tag["variant"],
                                        extra=tag, oracle=False, traces=traces))
            ep += 1
        for s in te:
            rows.append(await self.play(self._grow(s, view, mem), mem, chain, ep, "test", variant=tag["variant"],
                                        learn=False, extra=tag, oracle=False, traces=traces))
            ep += 1
        test = [r for r in rows if r["phase"] == "test"]
        total = len(self.env.seed_cls.truth(laws))
        out = {"true": sum(map(self._score, test)) / max(1, len(test)),
               "train_score": sum(self._score(r) for r in rows if r["phase"] == "train") / max(1, len(tr)),
               "claimed": rows[-1].get("seed_laws_confident", 0) / total,
               "claimed_correct": rows[-1].get("seed_laws_correct", 0) / total, "total_laws": total}
        out["claimed_wrong"] = out["claimed"] - out["claimed_correct"]
        if isinstance(genome, dict):
            out["proxy"] = out["claimed"]  # the weak evaluator: how much the agent says it knows
        else:  # the mentor grades the life (self-evaluation) and writes the child's playbook
            m = await mentor(genome, life_summary(rows, traces), mem.seed.SPACES if mem.seed else {},
                             self.model, self.cons_settings)
            truth = self.env.seed_cls.truth(laws)
            ok = sum(1 for sp, v in m["claims"] if truth.get(sp) == v)
            out.update(proxy=m["self_score"] / 10, child=m["playbook"], mentor_claims=len(m["claims"]),
                       mentor_claims_correct=ok, **({"mentor_error": m["error"]} if "error" in m else {}))
        return out, ep

    def _towns(self, u: int, n_train: int, n_test: int, salt) -> tuple[list, list]:
        c = self.cfg
        laws = self._laws(u)
        train, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        tr = self.env.seeds_for(train, laws, n_train, random.Random(_seed(("evo-train", c.rng_seed, u, salt))),
                                n_distractors=c.n_distractors)
        te = self.env.seeds_for(test, laws, n_test, random.Random(_seed(("evo-test", c.rng_seed, u, salt))),
                                n_distractors=c.n_distractors)
        return tr, te

    async def evolve_chain(self, evaluator, cond, view, r):
        """Generations of learners. Generation g lives in universe universes[g % n]; all lives of a generation
        meet the same towns (common random numbers), so their fitness is comparable."""
        from .evolve import DEFAULT_PLAYBOOK, Archive, Life, default_genome, next_genomes, random_genome

        c = self.cfg
        llm = c.policy == "llm"
        rng = random.Random(_seed(("evolve", c.rng_seed, evaluator, r)))
        chain = f"{self.env.name}-evolve-{evaluator}-{view}-r{r}"
        archive = Archive(c.evolve_archive, evaluator)
        first = DEFAULT_PLAYBOOK if llm else default_genome()
        pop = [(first, [])] + [((DEFAULT_PLAYBOOK if llm else random_genome(rng)), []) for _ in range(c.evolve_pop - 1)]
        ep, idx = 0, 0
        for g in range(c.evolve_generations):
            u = c.universes[g % len(c.universes)]
            towns = self._towns(u, c.n_train, c.n_test, ("gen", g, r))
            lives = []
            for genome, parents in pop:
                tag = {"variant": evaluator, "evaluator": evaluator, "generation": g, "life": idx, "universe": u}
                out, ep = await self._life(genome, u, towns, view, chain, ep, tag)
                life = Life(genome, g, idx, parents, out["proxy"], out["true"], out)
                lives.append(life)
                await self.rec.write({"protocol": "evolve", "phase": "life", "env": self.env.name, "policy": c.policy,
                                      "llm": self.llm_name, "chain": chain, "repeat": r, **tag, "parents": parents,
                                      "genome": genome, **{k: v for k, v in out.items() if k != "child"},
                                      **({"child": out["child"]} if "child" in out else {})})
                idx += 1
            archive.add(lives)
            # a fixed benchmark: the archive's best learner, fresh lives in every evolution universe
            if c.evolve_benchmark:
                best = archive.best()
                bench = []
                for ub in c.universes:
                    tag = {"variant": f"{evaluator}-bench", "evaluator": evaluator, "generation": g,
                           "learner": "best", "universe": ub}
                    out, ep = await self._life(best.genome, ub, self._towns(ub, c.n_train, c.n_test, ("bench", r)),
                                               view, chain, ep, tag)
                    bench.append(out)
                await self.rec.write({
                    "protocol": "evolve", "phase": "generation", "env": self.env.name, "policy": c.policy,
                    "llm": self.llm_name, "chain": chain, "repeat": r, "evaluator": evaluator, "generation": g,
                    "best_life": best.index, "genome": best.genome,
                    "pop_true": sum(x.true for x in lives) / len(lives), "pop_proxy": sum(x.proxy for x in lives) / len(lives),
                    **{f"bench_{k}": sum(o[k] for o in bench) / len(bench)
                       for k in ("true", "proxy", "claimed", "claimed_correct", "claimed_wrong")}})
            if llm:  # children: the mentor's rewrite of a selected parent's playbook (the elite keeps its own)
                best = archive.best()
                pop = [(best.genome, [best.index])]
                while len(pop) < c.evolve_pop:
                    p = archive.pick(rng)
                    pop.append((p.info.get("child") or p.genome, [p.index]))
            else:
                pop = next_genomes(archive, c.evolve_pop, rng, c.evolve_sigma)
        # transfer: fresh lives in universes never seen during evolution, after k training towns
        evolved = archive.best().genome
        for u in c.transfer_universes:
            for k in c.transfer_curve:
                towns = self._towns(u, k, c.n_test, ("transfer", k, r))
                for label, genome in (("initial", first), ("evolved", evolved)):
                    tag = {"variant": f"{evaluator}-transfer-{label}", "evaluator": evaluator, "learner": label,
                           "universe": u, "k_train": k}
                    out, ep = await self._life(genome, u, towns, view, chain, ep, tag)
                    await self.rec.write({"protocol": "evolve", "phase": "transfer", "env": self.env.name,
                                          "policy": c.policy, "llm": self.llm_name, "chain": chain, "repeat": r,
                                          **tag, "genome": genome, **{k2: v for k2, v in out.items() if k2 != "child"}})

    async def run(self) -> Path:
        fn = getattr(self, f"{self.cfg.protocol}_chain")
        await asyncio.gather(*[fn(*ch) for ch in self._chains()])
        return self.rec.dir


def run_experiment(cfg: ExpConfig) -> Path:
    os.makedirs(cfg.out_dir, exist_ok=True)
    return asyncio.run(Runner(cfg).run())
