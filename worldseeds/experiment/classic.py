"""The single-agent protocols of the program seed.

compgen      H4/RQ8  train on 1-2 block worlds, test on unseen 3-4 block compositions
persistence  H1/RQ1  multi-goal worlds; persistent world state vs world reset per goal
law_shift    H5/RQ7  laws change mid-stream; consolidation with/without recency decay
multiagent   RQ9     N agents explore in parallel; shared seed vs independent seeds
curriculum   RQ10    seed-mutation curriculum vs uniformly sampled training worlds
"""

from __future__ import annotations

import asyncio
import random

from .runner import _seed


class ClassicProtocols:
    async def compgen_chain(self, u, cond, view, r, src=None):
        c = self.cfg
        laws = self._laws(u)
        rng = random.Random(_seed((c.rng_seed, u, r)))
        train, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        tr = self.env.seeds_for(train, laws, c.n_train, rng, n_distractors=c.world.n_distractors)
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(c.rng_seed * 7 + u * 31 + r),
                       n_distractors=c.world.n_distractors)
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
        seeds = [self.env.make_seed(laws, cb, rng, n_goals=3, n_distractors=c.world.n_distractors, big=True)
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
        for variant, decay in (("no_decay", 1.0), ("decay", c.learner.decay if c.learner.decay < 1 else 0.7)):
            if cond not in ("seed", "seed_llm") and variant != "no_decay":
                continue
            mem = self._mem(cond, laws_a, decay)
            chain = f"{self.env.name}-law_shift-u{u}-{cond}-{view}-{variant}-r{r}"
            ep = 0
            for phase, laws, n in (("before", laws_a, c.n_train), ("after", laws_b, c.n_train)):
                mem.set_laws(laws)
                for s in self.env.seeds_for(train, laws, n, rng, n_distractors=c.world.n_distractors):
                    await self.play(self._grow(s, view, mem), mem, chain, ep, phase, variant=variant)
                    ep += 1

    async def multiagent_chain(self, u, cond, view, r):
        c = self.cfg
        if cond not in ("seed", "seed_llm"):
            return
        laws = self._laws(u)
        rng = random.Random(_seed(("multi", c.rng_seed, u, r)))
        train, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        rounds = max(1, c.n_train // c.team.n_agents)
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(u * 31 + r), n_distractors=c.world.n_distractors)
        for variant in ("shared", "independent"):
            shared = self._mem(cond, laws)
            mems = [shared] * c.team.n_agents if variant == "shared" else [self._mem(cond, laws) for _ in range(c.team.n_agents)]
            chain = f"{self.env.name}-multiagent-u{u}-{cond}-{view}-{variant}-r{r}"
            ep = 0
            for rd in range(rounds):
                # Agents specialise: agent a explores worlds containing its "home" block, so a
                # shared seed can hand an agent laws it has never experienced itself (section 15).
                seeds = []
                for a in range(c.team.n_agents):
                    home = self.env.blocks[a % len(self.env.blocks)]
                    combo = rng.choice([cb for cb in train if home in cb])
                    seeds += self.env.seeds_for([combo], laws, 1, rng, n_distractors=c.world.n_distractors)
                worlds = [self._grow(s, view) for s in seeds]
                # play in parallel *without* learning, then consolidate the round (avoids races)
                await asyncio.gather(*[
                    self.play(w, mems[a], chain, ep + a, "train", variant=variant, learn=False,
                              extra={"agent": a, "round": rd})
                    for a, w in enumerate(worlds)
                ])
                for a, w in enumerate(worlds):
                    await self.consolidate(w, mems[a], chain, ep + a)
                ep += c.team.n_agents
            # evaluate agent 0's seed (shared: the collective one) on unseen compositions
            for s in te:
                await self.play(self._grow(s, view), mems[0], chain, ep, "test", variant=variant, learn=False,
                                extra={"agent": 0, "train_worlds_total": rounds * c.team.n_agents})
                ep += 1

    async def curriculum_chain(self, u, cond, view, r):
        c = self.cfg
        laws = self._laws(u)
        rng = random.Random(_seed(("curr", c.rng_seed, u, r)))
        _, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(u * 31 + r), n_distractors=c.world.n_distractors)
        for variant in ("curriculum", "uniform"):
            mem = self._mem(cond, laws)
            chain = f"{self.env.name}-curriculum-u{u}-{cond}-{view}-{variant}-r{r}"
            seed = self.env.make_seed(laws, (rng.choice(self.env.blocks),), rng, n_distractors=c.world.n_distractors)
            ep = 0
            for _ in range(c.n_train):
                if variant == "uniform":
                    k = rng.randint(1, min(4, len(self.env.blocks)))
                    blocks = tuple(rng.sample(self.env.blocks, k))
                    seed = self.env.make_seed(laws, blocks, rng, n_distractors=c.world.n_distractors)
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
