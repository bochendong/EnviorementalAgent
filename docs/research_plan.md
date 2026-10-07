# World Seeds — review of the idea, and the concrete plan this repo implements

This reviews `world_seeds_program_seed.md` and explains how the prototype in this repo
turns it into experiments you can run on Nibi.

## 1. Verdict in one paragraph

The core loop (**Seed → Grow → Zoom → Act → Consolidate → Seed′**) holds together, and
three parts of it are strong and testable: **interventional similarity** (compare
environments by how they respond to `do(a)`, not by how they look), **laws vs.
accidents across environments**, and **uncertainty-triggered zoom**. The main risk is
scope. The document proposes 10 RQs, 5 hypotheses and 7 papers, and the word *seed*
carries three different meanings. A reviewer will ask what the falsifiable claim is,
and the answer should fit in one experiment table. Section 4 below proposes that first
paper. The code implements it, plus small versions of the other protocols so that
later papers start from working infrastructure.

## 2. Strengths worth keeping

* **Interventional similarity (§3).** This is the most precise idea in the document and easy
  to show. `scripts/similarity_demo.py` shows that worlds from the same universe get
  interventional similarity 1.00 (0.60 across universes), while appearance-based
  similarity cannot tell them apart (0.35 vs 0.33).
* **Variation reveals invariance (§3, §13).** This gives a clean experimental design:
  hold the laws fixed within a *universe*, vary the surface across worlds, and
  include decoys so that only the law explains the outcomes.
* **Zoom = switching causal models, not adding pixels (§6).** In the prototype, details
  such as a key's shape, a jar's material or a machine's faulty part only exist at
  deeper levels. Zooming has a purpose: it is how the agent gathers the variables the
  laws depend on.
* **Lazy growth (§11).** This is cheap to implement and to measure (`nodes_grown`).

## 3. Weaknesses and how the prototype addresses them

| # | Issue in the seed document | What can go wrong | What this repo does |
|---|---|---|---|
| 1 | "Seed" means three things: the environment's generator, the agent's world model, and memory | Reviewers cannot tell what is learned and what is given | Two objects. `WorldSeed` is the *true* generator (hidden laws, blocks, size, surface seed). `SeedMemory` is the *learned* seed the agent carries. The learned seed never reads the true one. |
| 2 | "The world remembers for the agent" (§2) is close to trivially true | A persistent world means doors stay open, so of course it saves work | `persistence` compares a persistent world with **no** memory against a reset world **with** memory. It also trims context (`--history-items`) while the world keeps the state. |
| 3 | Compositional generalisation can be solved by the LLM's priors | "Keys match by colour" is what an LLM already guesses | Universes with counter-intuitive laws (keys match by **shape** or **material**, odd tool maps), and **decoys that match on every non-law attribute**. Universe 0 follows the prior and serves as a control. |
| 4 | Consolidation can leak ground truth | The learned seed looks good because it saw hidden attributes | Events record only attributes the agent has **perceived** (zoomed into). Consolidation uses only those. |
| 5 | Uncertainty for zoom (§7) is undefined for LLMs | Self-reported LLM confidence is poorly calibrated | Uncertainty is structural: either no confident hypothesis exists, or the attribute it needs has not been perceived. `predict()` then names exactly what to zoom into. |
| 6 | "Discover blocks automatically" (§4) is open-ended | Hard to evaluate | Two consolidators. **Symbolic** (fixed hypothesis spaces per block, so law recovery can be scored exactly) and **LLM** (`seed_llm`, free-text rules, open-ended). Next step: a program-synthesis consolidator that writes transition code. |
| 7 | Multi-agent shared seed (§15) | Bad evidence from one agent can poison the shared seed | Evidence counts are merged, so contradictions accumulate visibly. Agents specialise in different blocks, so a shared seed can transfer laws an agent never saw. |
| 8 | No continual-learning stressor | Consolidation "without interference" goes untested | `law_shift`: laws change mid-stream. Compares recency-decayed with non-decayed evidence. |
| 9 | Related work is missing | Novelty will be challenged | See §6. Position the work as *the same learned causal seed both grows worlds and conditions the agent*. |

## 4. Proposed first paper (Paper 0)

**Title idea:** *World Seeds: Consolidating Causal Laws Across Environments Lets Small Open
LLM Agents Generalise to Unseen Compositions*

**Claim (falsifiable):** An LLM agent that carries a consolidated causal seed, and uses
it to decide where to zoom, beats agents that carry raw trajectories or retrieved
episodic memories on *unseen block compositions*. It also uses fewer actions and fewer
tokens. The gap is largest in universes whose laws contradict the LLM's priors.

**Main table** (`compgen` protocol): rows are conditions
`none | trajectory | retrieval | seed | seed_llm | oracle`. Columns are success,
actions/oracle-actions, tokens and zoom operations. Report the test phase only, split
by prior-friendly universe (u0) vs. counter-intuitive universes (u1–u4).

**Secondary results:**
* H3: `zoom` vs `flat` views at equal success, comparing tokens and nodes grown.
* H1: `persistence` protocol.
* H5: `law_shift` protocol.
* Law recovery: the learned seed's confident laws vs. the truth (`seed_laws_correct/confident`).

**Models:** Qwen3-8B as the main model. Qwen3-30B-A3B or Qwen3-32B (FP8) for scaling.
All are free, open-weight, and served locally by vLLM on Nibi H100s.

## 4b. SeedVille as the main environment

A small town is the most natural home for the idea, because the doc's own zoom example
(city → building → room → object) *is* a town. SeedVille (`worldseeds/town/`) adds three
things the dungeon lacks:

* **Exogenous dynamics (§9's ξ_t).** A clock runs, crops grow overnight, and villagers follow
  schedules. The world changes even when the agent does nothing.
* **Hidden laws with a believable cover story:** soil and season needs of crops, gift
  preferences, villager routines. Universe 0 follows common sense; shuffled universes test
  whether the seed beats the model's prior (Stardew-style knowledge from pretraining).
* **Long-lived persistence:** planted fields and friendships carry over between goals.

**A purpose in the town (the board).** `--env board` replaces the single trophy with a week-long
town board of four villager requests (harvest, friendship, fetch from another villager, buy with
earned coins). This adds planning over days and gives every villager a role, and it is the
setting for the memory steps below and for multi-agent cooperation (agents splitting a board).

**Memory in the world (the library).** Many questions are about memory that is *not* inside the
agent: using what another agent learned, deciding whether to trust it, and sharing it among
several agents. SeedVille's library makes that memory a place: consolidated laws and agents'
notes sit on topic shelves, and reading costs actions and game time. The planned sequence:

1. Sorted shelves vs one unsorted pile vs seed in the head vs nothing (implemented:
   conditions `library`, `library_flat`).
2. + 3. (implemented together, `--source-errors`): notes by other agents and villager testimony,
   each wrong at a controlled rate with consistent errors. Does the agent verify a claim by
   intervention before relying on it, and does it learn whom to trust?
4. Several agents in one town: no sharing vs a shared library (stigmergy) vs direct messages.

Suggested paper framing: run the main table on SeedVille, use the dungeon as the fully
controlled replication, and (optionally) add one external benchmark (ScienceWorld/ALFWorld,
or a Crafter/TextCraft Minecraft-style task with shuffled recipes) for outside validity.

Closest existing town or life-sim environments, to cite and contrast (verify before citing):
Generative Agents' "Smallville" (social behaviour, not causal laws), Concordia (LLM game
master, so its rules are not exact), and a recent Stardew Valley benchmark (StarDojo; real
game, hard to run on a cluster, and the rules are known to models).

## 5. Mapping from the seed document to code

| Seed doc | Code |
|---|---|
| §2 environment as causal memory, `E_t=(x_t,m_t)` | `world.py`, `town/world.py` (persistent state, `next_goal`), `persistence` protocol |
| §9 exogenous events ξ_t | SeedVille clock: overnight crop growth, villager schedules |
| §3 interventional similarity | `similarity.py`, `scripts/similarity_demo.py` |
| §4 reusable causal blocks | `seed.py` blocks: lockable, container, powered, pushable, fragile, machine |
| §5–6 God view, object at L = environment at L+1 | `world.py` levels: world → room → object → component; `zoom_in`/`zoom_out` |
| §7 adaptive zoom | `SeedMemory.predict` returns UNCERTAIN plus a zoom target; agent tool `predict` |
| §8 zoom out = consolidation | `SeedMemory.consolidate_events`, `llm_consolidate` |
| §9–11 seeds, causal DNA, lazy growth | `WorldSeed`, `grow()`, lazy `_grow_room`/`_grow_components`, `nodes_grown` |
| §12 seeds mature | the learned `SeedMemory` across episodes; `decay` |
| §13 episodic → invariance → block | hypothesis spaces with support/against evidence; `recovery()` |
| §15 multi-agent shared seed | `multiagent` protocol (shared vs independent) |
| §16–17 mutation, crossover, curriculum | `WorldSeed.mutate`/`crossover`; `curriculum` protocol |
| §18 architecture (Seed, Grower, Agent, Consolidator) | `memory.py`, `world.py`, `agent.py`, `experiment.py` |
| §23 baselines | conditions `none`, `trajectory`, `retrieval`, `seed`, `seed_llm`, `oracle`; views `zoom`/`flat` |
| §24 metrics | `episodes.jsonl`: success, actions, oracle_steps, invalid, zoom_ops, nodes_grown, tokens, law recovery |

## 6. Related work to position against (verify each before citing)

* Open-ended or generated environments: POET; PAIRED and unsupervised environment design; Genie (generative interactive environments).
* World models: Dreamer family; hierarchical and abstract world models.
* Theory and program induction of world dynamics: theory-based RL (EMPA); AutumnSynth; WorldCoder.
* LLM agent memory: Reflexion; Generative Agents' memory stream; Voyager's skill library; ExpeL; Agent Workflow Memory.
* Text-world benchmarks: TextWorld; ALFWorld.
* Stigmergy and shared-memory multi-agent coordination.

The differentiator to argue: in these lines of work, the generator, the world model and
the memory are separate objects. Here one consolidated causal seed is all three. It is
learned only from perceived interventions, and it decides where to zoom.

## 7. Known limitations of the prototype (be upfront in the paper)

* The symbolic consolidator's hypothesis spaces are hand-designed per block. That tests
  *recovery*, not open-ended *discovery*. `seed_llm` is the open-ended variant.
* The learned seed does not yet drive *generation* (Grow uses the true seed). Next step:
  grow imagined worlds from the learned seed and use them for planning or self-curriculum
  (Paper D/G).
* SeedVille's hypothesis spaces are also hand-designed (soil, season, gift, schedule).
* Worlds are small (2–5 rooms, 7–9 town locations). Scale with `n_rooms`, `n_distractors` and multi-goal worlds.
* The heuristic agent explores by brute force, so on its own it gains little from the
  seed. Its role is to test the pipeline and to show that laws can be recovered. The real
  test is the LLM agent.
* **No LLM results yet.** The code was tested offline (scripted model and a mock
  OpenAI-compatible server). The first Nibi run will be the first real measurement.
