"""Many agents in parallel worlds sharing one memory (``--protocol hive``)."""

from __future__ import annotations

import asyncio
import random

from .runner import _seed


class HiveProtocol:
    async def hive_chain(self, u, cond, view, r):
        """Many agents, many worlds, one memory: every (mode, size, faulty share) is one hive run."""
        c = self.cfg
        if cond not in ("seed", "seed_llm") or self.env.name not in ("town", "board"):
            return
        laws = self._laws(u)
        _, test = self.env.split(random.Random(c.rng_seed * 1000 + u))
        te = self.env.seeds_for(test, laws, c.n_test, random.Random(_seed(("hive-test", c.rng_seed, u, r))),
                                n_distractors=c.world.n_distractors)
        runs = [(m, n, f) for m in c.hive.modes for n in c.hive.sizes for f in c.hive.faulty
                if (n > 1 or m == "isolated") and not (m == "serial" and (n == 1 or f))]
        await asyncio.gather(*[self.hive_run(u, view, r, laws, m, n, f, te) for m, n, f in runs])

    async def hive_run(self, u, view, r, laws, mode, n, faulty, te) -> None:
        import itertools
        from dataclasses import replace

        from ..hive import HIVE_MODES, Hive

        c = self.cfg
        truth_a = self.env.seed_cls.truth(laws)
        laws_b = laws.mutate(random.Random(_seed(("hive-shift", c.rng_seed, u))), n=c.hive.shift_laws) \
            if c.hive.shift_wave else laws
        truth_b = self.env.seed_cls.truth(laws_b)
        hv = Hive(self.env.seed_cls, HIVE_MODES[mode], n, faulty, rng_seed=_seed(("hive", c.rng_seed, u, r, n, faulty)),
                  faulty_mode=c.hive.faulty_mode, truth=truth_a)
        # regional shift: the first ``share`` of the agents (whole groups, as groups are consecutive) live under
        # the new laws
        moved_agents = set(range(round(c.hive.shift_share * n))) if c.hive.shift_wave else set()

        def region_laws(i: int, wv: int):
            shifted = c.hive.shift_wave and wv + 1 >= c.hive.shift_wave and i in moved_agents
            return laws_b if shifted else laws
        combos = [cb for k in range(1, len(self.env.blocks) + 1) for cb in itertools.combinations(self.env.blocks, k)]
        variant = f"{mode}-n{n}" + (f"-f{faulty:g}" if faulty else "") + (
            f"-{c.hive.faulty_mode}" if faulty and c.hive.faulty_mode != "scattered" else "") + (
            f"-shift{c.hive.shift_wave}x{c.hive.shift_share:g}" if c.hive.shift_wave else "")
        chain = f"{self.env.name}-hive-u{u}-{variant}-{view}-r{r}"
        total = len(self.env.seed_cls.truth(laws))
        ep = 0
        tag = {"hive_mode": mode, "hive_n": n, "faulty": faulty, "faulty_mode": c.hive.faulty_mode,
               "shift_wave": c.hive.shift_wave, "shift_share": c.hive.shift_share if c.hive.shift_wave else 0}
        for wv in range(c.hive.waves):
            if c.hive.shift_wave and wv + 1 == c.hive.shift_wave and c.hive.shift_share >= 1:
                hv.truth, hv.checked = truth_b, set()  # audits now replicate under the new laws
            seeds = []
            for i in range(n):  # the same worlds for every mode (unless a director picks them)
                rng = random.Random(_seed(("hive-world", c.rng_seed, u, r, wv, i)))
                s = self.env.seeds_for([rng.choice(combos)], region_laws(i, wv), 1, rng,
                                       n_distractors=c.world.n_distractors)[0]
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
            if c.hive.shift_wave and wv + 1 >= c.hive.shift_wave:
                moved = [i for i in agents if region_laws(i, wv) is laws_b and laws_b is not laws]
                cur = truth_b if c.hive.shift_share >= 1 and wv + 1 >= c.hive.shift_wave else truth_a
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
        test_laws = laws_b if c.hive.shift_wave else laws
        m = self._mem("seed", test_laws)
        m.seed = shared
        if c.hive.shift_wave:  # the newcomer arrives in the changed land
            te = self.env.seeds_for(self.env.split(random.Random(c.rng_seed * 1000 + u))[1], laws_b, c.n_test,
                                    random.Random(_seed(("hive-test", c.rng_seed, u, r))),
                                    n_distractors=c.world.n_distractors)
        for s in te:
            await self.play(self._grow(s, view), m, chain, ep, "test", variant=variant, learn=False,
                            extra={**tag, "shared_known": Hive.score(shared, test_laws)[0],
                                   "shared_wrong": Hive.score(shared, test_laws)[1], "total_laws": total})
            ep += 1
