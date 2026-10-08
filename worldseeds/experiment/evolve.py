"""Generations of learners that inherit how to learn (``--protocol evolve``; worldseeds/evolve.py)."""

from __future__ import annotations

import random

from .runner import _seed


class EvolveProtocol:
    def evolve_chains(self):
        """One evolution per evaluator over all universes (a generation lives in one of them)."""
        c = self.cfg
        for view in c.views:
            for r in range(c.repeats):
                for ev in c.evolve.evaluators:
                    yield (ev, "seed", view, r)

    def _score(self, row: dict) -> float:
        return row["board_done"] / row["board_total"] if row.get("board_total") else float(bool(row["success"]))

    async def _life(self, genome, u: int, towns, view: str, chain: str, ep0: int, tag: dict) -> tuple[dict, int]:
        """One life from an empty head: train towns, then test towns. Returns (summary, next episode id)."""
        from ..evolve import apply_genome, life_summary, mentor

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
            from ..skin import make_skin

            m = await mentor(genome, life_summary(rows, traces), mem.seed.SPACES if mem.seed else {},
                             self.model, self.cons_settings, skin=make_skin(self.cfg.llm.skin))
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
                                n_distractors=c.world.n_distractors)
        te = self.env.seeds_for(test, laws, n_test, random.Random(_seed(("evo-test", c.rng_seed, u, salt))),
                                n_distractors=c.world.n_distractors)
        return tr, te

    async def evolve_chain(self, evaluator, cond, view, r):
        """Generations of learners. Generation g lives in universe universes[g % n]; all lives of a generation
        meet the same towns (common random numbers), so their fitness is comparable."""
        from ..evolve import DEFAULT_PLAYBOOK, Archive, Life, default_genome, next_genomes, random_genome

        c = self.cfg
        llm = c.policy == "llm"
        rng = random.Random(_seed(("evolve", c.rng_seed, evaluator, r)))
        chain = f"{self.env.name}-evolve-{evaluator}-{view}-r{r}"
        archive = Archive(c.evolve.archive, evaluator)
        first = DEFAULT_PLAYBOOK if llm else default_genome()
        pop = [(first, [])] + [((DEFAULT_PLAYBOOK if llm else random_genome(rng)), []) for _ in range(c.evolve.pop - 1)]
        ep, idx = 0, 0
        for g in range(c.evolve.generations):
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
            if c.evolve.benchmark:
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
                while len(pop) < c.evolve.pop:
                    p = archive.pick(rng)
                    pop.append((p.info.get("child") or p.genome, [p.index]))
            else:
                pop = next_genomes(archive, c.evolve.pop, rng, c.evolve.sigma)
        # transfer: fresh lives in universes never seen during evolution, after k training towns
        evolved = archive.best().genome
        for u in c.evolve.transfer_universes:
            for k in c.evolve.transfer_curve:
                towns = self._towns(u, k, c.n_test, ("transfer", k, r))
                for label, genome in (("initial", first), ("evolved", evolved)):
                    tag = {"variant": f"{evaluator}-transfer-{label}", "evaluator": evaluator, "learner": label,
                           "universe": u, "k_train": k}
                    out, ep = await self._life(genome, u, towns, view, chain, ep, tag)
                    await self.rec.write({"protocol": "evolve", "phase": "transfer", "env": self.env.name,
                                          "policy": c.policy, "llm": self.llm_name, "chain": chain, "repeat": r,
                                          **tag, "genome": genome, **{k2: v for k2, v in out.items() if k2 != "child"}})
