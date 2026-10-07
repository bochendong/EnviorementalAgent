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


PROTOCOLS = ["compgen", "persistence", "law_shift", "multiagent", "curriculum"]


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
    decay: float = 1.0
    n_distractors: int = 2
    save_traces: bool = False
    out_dir: str = "results/run"
    rng_seed: int = 0


class Recorder:
    def __init__(self, cfg: ExpConfig):
        self.dir = Path(cfg.out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
        self._f = open(self.dir / "episodes.jsonl", "a")
        self._t = open(self.dir / "traces.jsonl", "a") if cfg.save_traces else None
        self._lock = asyncio.Lock()

    async def write(self, row: dict, trace: list | None = None) -> None:
        async with self._lock:
            self._f.write(json.dumps(row) + "\n")
            self._f.flush()
            if self._t is not None and trace is not None:
                self._t.write(json.dumps({"key": row["chain"], "episode": row["episode"], "trace": trace}) + "\n")
                self._t.flush()

    def save_seed(self, chain: str, seed: LawSeed) -> None:
        d = self.dir / "seeds"
        d.mkdir(exist_ok=True)
        (d / f"{chain}.json").write_text(json.dumps(seed.to_dict(), indent=1))


LIBRARY_CONDITIONS = ("library", "library_flat")


class Memories:
    """All memories a chain carries across episodes."""

    def __init__(self, condition: str, laws, env: EnvSpec, decay: float = 1.0):
        self.condition = condition
        self.seed = env.seed_cls(decay=decay) if condition in ("seed", "seed_llm") else None
        self.retrieval = RetrievalMemory() if condition == "retrieval" else None
        self.traj = TrajectoryMemory() if condition == "trajectory" else None
        self.oracle = OracleSeed(laws) if condition == "oracle" else None
        # library conditions (town only): memory lives in the world, on shelves the agent must go and read.
        # ``lib_seed`` is the librarian: it consolidates each town's events and rewrites the shelves.
        self.library = self.lib_seed = None
        if condition in LIBRARY_CONDITIONS:
            if env.name != "town":
                raise ValueError(f"condition {condition!r} needs env 'town'")
            from .town.library import LibraryArchive

            self.library = LibraryArchive(mode="flat" if condition == "library_flat" else "categorized")
            self.lib_seed = env.seed_cls(decay=decay)
        self.laws = laws

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
                   variant: str = "", learn: bool = True, extra: dict | None = None) -> dict:
        cond = mem.condition
        try:
            opt = self.env.oracle_steps(world)
        except Exception:
            opt = None
        reads0 = mem.library.reads if mem.library is not None else 0
        lib0 = mem.library.to_dict() if mem.library is not None else None  # shelves as the agent found them
        async with self.sem:
            if self.cfg.policy == "heuristic":
                sd = mem.seed if cond in ("seed", "seed_llm") else (
                    self.env.seed_cls.certain_of(mem.laws) if cond == "oracle" else None)
                metrics, trace = self.env.heuristic(world, sd, random.Random(episode)).run(), None
                # (library conditions: sd is None and the agent fills its head by reading the shelves)
            else:
                from .agent import run_episode

                metrics, ctx = await run_episode(
                    world, cond, self.model, self.settings, seed=mem.seed, retrieval=mem.retrieval,
                    traj=mem.traj, oracle=mem.oracle, library=mem.library, max_turns=self.cfg.max_turns,
                    history_items=self.cfg.history_items,
                )
                trace = ctx.trace
        if learn:
            await self.consolidate(world, mem, chain, episode)
        row = {
            "protocol": self.cfg.protocol, "env": self.env.name, "policy": self.cfg.policy, "llm": self.llm_name,
            "chain": chain, "condition": cond, "view": "flat" if world.eager else "zoom",
            "variant": variant, "phase": phase, "episode": episode,
            "seed_id": world.seed.id, "seed": world.seed.to_dict(), "composition": world.seed.composition,
            "n_blocks": len(world.seed.blocks), "n_rooms": world.seed.n_rooms,
            "goal_index": world.goal_index, "oracle_steps": opt, **metrics,
            "time": time.time(), **(extra or {}),
        }
        if mem.seed is not None:
            rec = mem.seed.recovery(mem.laws)
            known = [v for v in rec.values() if v is not None]
            row["seed_laws_confident"] = len(known)
            row["seed_laws_correct"] = sum(1 for v in known if v)
            row["seed_rules"] = len(mem.seed.rules)
        if mem.library is not None:
            correct, scored = mem.library.accuracy(self.env.seed_cls.truth(mem.laws))
            row["library_reads"] = mem.library.reads - reads0
            row["library_entries"] = len(mem.library.entries)
            row["library_notes"] = sum(1 for e in mem.library.entries if e.source == "note")
            row["library_claims_correct"], row["library_claims"] = correct, scored
            row["library"] = lib0
        await self.rec.write(row, trace)
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
            mem.lib_seed.consolidate_events(world.events)
            mem.lib_seed.worlds_seen += 1
            mem.library.update_from_seed(mem.lib_seed, episode, author="librarian")
        if mem.retrieval is not None:
            mem.retrieval.add_events(world.events, tag)
        if mem.traj is not None:
            mem.traj.add_events(world.events, tag)

    def _grow(self, s, view: str, mem: Memories | None = None):
        kw = {"library": mem.library} if mem is not None and mem.library is not None else {}
        return self.env.grow(s, eager=(view == "flat"), max_actions=self.cfg.max_actions, **kw)

    def _mem(self, cond, laws, decay=None) -> Memories:
        return Memories(cond, laws, self.env, self.cfg.decay if decay is None else decay)

    def _chains(self):
        c = self.cfg
        conds = c.conditions
        if c.policy == "heuristic":
            conds = [x for x in conds if x in ("none", "seed", "oracle", *LIBRARY_CONDITIONS)]
        if c.env != "town":
            conds = [x for x in conds if x not in LIBRARY_CONDITIONS]
        for u in c.universes:
            for cond in conds:
                for view in c.views:
                    for r in range(c.repeats):
                        yield u, cond, view, r

    # ------------------------------------------------------------ protocols
    async def compgen_chain(self, u, cond, view, r):
        c = self.cfg
        laws = self.env.laws(u)
        rng = random.Random(_seed((c.rng_seed, u, r)))
        train, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        tr = self.env.seeds_for(train, laws, c.n_train, rng, n_distractors=c.n_distractors)
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(c.rng_seed * 7 + u * 31 + r),
                       n_distractors=c.n_distractors)
        mem = self._mem(cond, laws)
        chain = f"{self.env.name}-compgen-u{u}-{cond}-{view}-r{r}"
        ep = 0
        for s in tr:
            await self.play(self._grow(s, view, mem), mem, chain, ep, "train")
            ep += 1
        for s in te:
            await self.play(self._grow(s, view, mem), mem, chain, ep, "test", learn=False)
            ep += 1
        if mem.seed:
            self.rec.save_seed(chain, mem.seed)

    async def persistence_chain(self, u, cond, view, r):
        c = self.cfg
        laws = self.env.laws(u)
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
        laws_a = self.env.laws(u)
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
        laws = self.env.laws(u)
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
        laws = self.env.laws(u)
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

    async def run(self) -> Path:
        fn = getattr(self, f"{self.cfg.protocol}_chain")
        await asyncio.gather(*[fn(*ch) for ch in self._chains()])
        return self.rec.dir


def run_experiment(cfg: ExpConfig) -> Path:
    os.makedirs(cfg.out_dir, exist_ok=True)
    return asyncio.run(Runner(cfg).run())
