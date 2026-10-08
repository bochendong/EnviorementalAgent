"""Several agents on one town board (``--protocol team``), with the festival and roles switches."""

from __future__ import annotations

import asyncio
import random
import time

from .runner import _seed


class TeamProtocol:
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
        from ..town.team import TEAM_NAMES

        laws = self._laws(u)
        rng = random.Random(_seed(("team", c.rng_seed, u, r)))
        train, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        n = max(2, min(c.team.n_agents, len(TEAM_NAMES)))
        rounds = max(1, c.n_train // n)
        mems = [self._mem(cond, laws) for _ in range(n)]
        chain = f"{self.env.name}-team-u{u}-{cond}-{view}-r{r}"
        ep = 0
        for rd in range(rounds):
            seeds = []
            for a in range(n):
                home = self.env.blocks[a % len(self.env.blocks)]
                combo = rng.choice([cb for cb in train if home in cb])
                seeds += self.env.seeds_for([combo], laws, 1, rng, n_distractors=c.world.n_distractors)
            worlds = [self._grow(s, view) for s in seeds]
            if c.team.roles:  # each specialist only perceives its own kind of detail, in its own towns too
                from ..town.team import PERCEIVES, ROLES

                for a, w in enumerate(worlds):
                    w.perceives = PERCEIVES[ROLES[a % len(ROLES)]]
            await asyncio.gather(*[
                self.play(w, mems[a], chain, ep + a, "train", variant=f"agent{a}",
                          extra={"agent": a, "round": rd, **({"role": ROLES[a % len(ROLES)]} if c.team.roles else {})})
                for a, w in enumerate(worlds)])
            ep += n
        for a, m in enumerate(mems):
            self.rec.save_seed(f"{chain}-agent{a}", m.seed)
        merged = self.env.seed_cls.from_dict(mems[0].seed.to_dict())
        for m in mems[1:]:
            merged.merge(m.seed)
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(c.rng_seed * 7 + u * 31 + r),
                                n_distractors=c.world.n_distractors)
        for s in te:
            await asyncio.gather(*[self.play_team(s, view, [m.seed for m in mems], merged, mode, chain, ep, laws)
                                   for mode in c.team.modes])
            ep += 1

    async def play_team(self, s, view, seeds, merged, mode, chain, ep, laws) -> dict:
        from ..town.library import LibraryArchive
        from ..town.team import TEAM_NAMES, Team, Teammate, run_heuristic_team

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
        team = Team(world, n, messages=(mode == "messages"), speed=matched if matched > 1 else 0, roles=c.team.roles)
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
                from ..agent import run_episode

                outs = await asyncio.gather(*[
                    run_episode(Teammate(team, i), "seed", self.model, self.settings, seed=carried[i],
                                max_turns=c.llm.max_turns * matched, history_items=c.llm.history_items,
                                context=c.llm.context, canvas_chars=c.llm.canvas_chars, skin=c.llm.skin)
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
            "library_reads": lib.reads if lib is not None else None, "festival": c.world.festival, "roles_on": c.team.roles,
            **metrics,
        }
        await self.rec.write(row, traces)
        return row
