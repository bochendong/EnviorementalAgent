"""The runner: plays episodes (heuristic or LLM), consolidates memories and records rows. The protocols
are mixed in from their own modules (classic, team, hive, evolve)."""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from pathlib import Path

from ..envs import get_env
from .config import ExpConfig
from .memories import SOURCE_CONDITIONS, Memories
from .recorder import Recorder

PROTOCOLS = ["compgen", "persistence", "law_shift", "multiagent", "curriculum", "team", "hive", "evolve"]


def _seed(parts) -> int:
    """Deterministic across processes (built-in hash() of str is salted per process)."""
    return int(hashlib.sha1(repr(parts).encode()).hexdigest()[:8], 16)


class CoreRunner:
    def __init__(self, cfg: ExpConfig):
        self.cfg = cfg
        self.env = get_env(cfg.env)
        self.rec = Recorder(cfg)
        self.sem = asyncio.Semaphore(cfg.concurrency)
        self.model = self.settings = None
        if cfg.policy == "llm":
            from ..llm import LLMConfig, make_model, make_settings

            lc = LLMConfig()
            self.model = make_model(lc)
            self.settings = make_settings(lc)
            self.cons_settings = make_settings(lc, tool_choice=None)  # consolidator has no tools
            self.llm_name = lc.model
        else:
            self.llm_name = "heuristic"

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
        if getattr(world, "screen_error", None) is not None:
            hkw["screen_policy"] = self.cfg.learner.screen_policy
        async with self.sem:
            if self.cfg.policy == "heuristic":
                sd = mem.seed if cond in ("seed", "seed_llm") else (
                    self.env.seed_cls.certain_of(mem.laws) if cond == "oracle" else None)
                metrics, trace = self.env.heuristic(world, sd, random.Random(episode), **hkw).run(), None
                # (library conditions: sd is None and the agent fills its head by reading the shelves)
            else:
                from ..agent import run_episode

                metrics, ctx = await run_episode(
                    world, cond, self.model, self.settings, seed=mem.seed, retrieval=mem.retrieval,
                    traj=mem.traj, oracle=mem.oracle, library=mem.library, max_turns=self.cfg.llm.max_turns,
                    history_items=self.cfg.llm.history_items, context=self.cfg.llm.context,
                    canvas_chars=self.cfg.llm.canvas_chars, skin=self.cfg.llm.skin, strategy=mem.strategy,
                )
                trace = ctx.trace
        if learn:
            await self.consolidate(world, mem, chain, episode)
        row = {
            "protocol": self.cfg.protocol, "env": self.env.name, "policy": self.cfg.policy, "llm": self.llm_name,
            "context": self.cfg.llm.context, "skin": self.cfg.llm.skin,
            "chain": chain, "condition": cond, "view": "flat" if world.eager else "zoom",
            "variant": variant, "phase": phase, "episode": episode,
            "seed_id": world.seed.id, "seed": world.seed.to_dict(), "composition": world.seed.composition,
            "n_blocks": len(world.seed.blocks), "n_rooms": world.seed.n_rooms,
            "goal_index": world.goal_index, "oracle_steps": opt, **metrics,
            # the world's switches, so an episode can be re-simulated exactly (scripts/export_replay.py)
            **({"world_opts": {**self._env_kw(), **({"testimony": world.testimony}
                                                     if getattr(world, "testimony", None) is not None else {})}}
               if self.env.name != "dungeon" else {}),
            **({"perception_spent": world.perception_spent, "zoom_budget": world.zoom_budget}
               if getattr(world, "zoom_budget", None) is not None else {}),
            **({"screens": world.screens, "screen_policy": self.cfg.learner.screen_policy,
                "plantings": sum(1 for e in world.events if e.verb == "plant" and e.success),
                "outcomes": sum(1 for e in world.events if e.verb == "night" and e.valid)}
               if getattr(world, "screen_error", None) is not None else {}),
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
                from ..agent import llm_consolidate

                lines = "\n".join(ev.line() for ev in world.events if ev.valid)[-6000:]
                from ..skin import make_skin

                await llm_consolidate(mem.seed, lines, self.model, self.cons_settings, skin=make_skin(self.cfg.llm.skin))
        if mem.library is not None:
            if self.cfg.learner.publication_bias:  # only successful projects publish, and only their positive results
                if world.done:
                    mem.lib_seed.consolidate_events([e for e in world.events if e.success])
            else:
                mem.lib_seed.consolidate_events(world.events)
            mem.lib_seed.worlds_seen += 1
            if mem.source_error is None:
                mem.library.update_from_seed(mem.lib_seed, episode, author="librarian")
            else:
                from ..town.sources import NOTE_AUTHORS

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
        kw = {"zoom_budget": c.world.zoom_budget} if c.world.zoom_budget is not None else {}
        if c.world.noise:
            kw["noise"] = c.world.noise
        if c.world.festival and self.env.name == "board":
            kw["festival"] = True
        if c.world.screen_error is not None:
            kw["screen_error"] = c.world.screen_error
        if c.world.confounder:
            kw["confounder"] = True
        return kw

    def _grow(self, s, view: str, mem: Memories | None = None):
        kw = {"library": mem.library} if mem is not None and mem.library is not None else {}
        kw.update(self._env_kw())
        if mem is not None and mem.condition == "testimony":
            kw["testimony"] = mem.source_error or 0.0
        return self.env.grow(s, eager=(view == "flat"), max_actions=self.cfg.max_actions, **kw)

    def _laws(self, u: int):
        if self.cfg.world.n_crops != 4:
            return self.env.laws(u, n_crops=self.cfg.world.n_crops)
        return self.env.laws(u)

    def _mem(self, cond, laws, decay=None, src=None) -> Memories:
        err, trust = src if src else (None, None)
        m = Memories(cond, laws, self.env, self.cfg.learner.decay if decay is None else decay, err, trust)
        for sd in (m.seed, m.lib_seed):
            if sd is not None and hasattr(sd, "deconfound"):
                sd.deconfound = self.cfg.learner.deconfound
            if sd is not None and self.cfg.learner.screen_weight is not None and "w_screen" in sd.tuning:
                sd.tuning["w_screen"] = self.cfg.learner.screen_weight
        return m

    def _chains(self):
        c = self.cfg
        conds = c.conditions
        if c.policy == "heuristic":
            conds = [x for x in conds if x in ("none", "seed", "oracle", *SOURCE_CONDITIONS)]
        if c.env not in ("town", "board"):
            conds = [x for x in conds if x not in SOURCE_CONDITIONS]
        if not c.world.source_errors:
            conds = [x for x in conds if x != "testimony"]
        own = getattr(self, f"{c.protocol}_chains", None)
        if own is not None:  # a protocol with its own chains (evolve)
            yield from own()
            return
        for u in c.universes:
            for cond in conds:
                srcs = [None]
                if cond in SOURCE_CONDITIONS and c.world.source_errors:
                    trusts = c.learner.trusts if c.policy == "heuristic" else [None]
                    srcs = [(e, t) for e in c.world.source_errors for t in trusts]
                for src in srcs:
                    for view in c.views:
                        for r in range(c.repeats):
                            yield (u, cond, view, r, src) if c.protocol == "compgen" else (u, cond, view, r)

    async def run(self) -> Path:
        if self.cfg.protocol not in PROTOCOLS:
            raise ValueError(f"unknown protocol {self.cfg.protocol!r}; one of {PROTOCOLS}")
        fn = getattr(self, f"{self.cfg.protocol}_chain")
        await asyncio.gather(*[fn(*ch) for ch in self._chains()])
        return self.rec.dir
