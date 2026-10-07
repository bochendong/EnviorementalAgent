# World Seeds: a prototype

A runnable prototype of the research program in
[`docs/world_seeds_program_seed.md`](docs/world_seeds_program_seed.md). The review of
the idea and the proposed first paper are in [`docs/research_plan.md`](docs/research_plan.md).

```
WorldSeed --grow--> lazy, zoomable, persistent World --zoom/act--> events
    ^                                                                 |
    |                     (hidden laws; the agent never reads them)   v
SeedMemory (learned causal seed) <------------- consolidate (perceived evidence only)
```

* **Two environments**, both grown from seeds with hidden laws:
  * **SeedVille** (`--env town`): a Stardew-flavoured mini town with a farm, villagers, a
    shop and a day/night clock. See [below](#seedville-the-mini-town).
  * **Dungeon** (`--env dungeon`, the default): rooms, doors, keys, jars, switches,
    machines and boulders. This is the most tightly controlled test-bed.
* **Agent:** [OpenAI Agents SDK](https://github.com/openai/openai-agents-python)
  (`Agent`, `Runner`, `function_tool`). Tools: `observe`, `zoom_in`, `zoom_out`, `act`,
  plus `predict` (seed conditions) or `recall` (retrieval baseline).
* **LLM:** any free open-weight model behind an OpenAI-compatible server. The default is
  **Qwen3-8B on vLLM** on one Nibi H100. No OpenAI key is needed, and tracing is disabled.

## Layout

```
worldseeds/
  laws.py        universe laws theta (key_match, fragile_material, link_attr, tool_map, push_tool)
  seed.py        WorldSeed (causal blocks + laws + size), mutate / crossover, compositional splits
  world.py       grown world: hierarchy world>room>object>component, lazy growth, zoom, dynamics, events
  oracle.py      privileged solver (solvability check + optimal-ish step count)
  memory.py      SeedMemory (learned seed: evidence, render, predict), Retrieval, Trajectory baselines
  agent.py       Agents-SDK agent, tools, episode loop, LLM consolidator (structured output)
  llm.py         vLLM / OpenAI-compatible model factory (Qwen3 thinking switch, tool_choice)
  heuristic.py   non-LLM explorer (CPU smoke tests, seed-only baseline)
  similarity.py  interventional vs observational environment similarity
  envs.py        environment registry (dungeon | town) used by the experiment runner
  experiment.py  protocols: compgen, persistence, law_shift, multiagent, curriculum
  town/          SeedVille: seed.py (laws, seeds), world.py (town, clock, crops, villagers),
                 agents.py (oracle, learned TownSeedMemory, heuristic agent)
scripts/  run_experiment.py, analyze.py, play.py, similarity_demo.py
slurm/    env.sh, setup_nibi.sh, serve_and_run.sh, submit_all.sh
tests/    world / memory / scripted-Agents-SDK tests (no GPU needed)
```

## Quick start (laptop, no GPU)

```bash
pip install -r requirements.txt
pytest -q                                              # 21 tests
python scripts/play.py --mode human --blocks lockable fragile machine --universe 1
python scripts/play.py --env town --mode human --blocks farming gifting schedule --universe 2
python scripts/run_experiment.py --env town --policy heuristic --protocol compgen \
       --conditions none seed oracle --universes 0 1 2 --out results/smoke
python scripts/analyze.py results/smoke --by condition phase
python scripts/similarity_demo.py
```

Any OpenAI-compatible endpoint works for the LLM agent:

```bash
export WS_BASE_URL=http://localhost:8000/v1 WS_MODEL=qwen3-8b WS_API_KEY=EMPTY
python scripts/play.py --mode llm --condition oracle --blocks lockable powered --verbose
```

| env var | default | meaning |
|---|---|---|
| `WS_BASE_URL` | `http://localhost:8000/v1` | OpenAI-compatible server |
| `WS_MODEL` | `qwen3-8b` | served model name |
| `WS_API_KEY` | `EMPTY` | key (vLLM ignores it) |
| `WS_THINKING` | `0` | `1` = keep Qwen3 thinking mode |
| `WS_TOOL_CHOICE` | `required` | `auto` if the server lacks `required` support |

## Running on Nibi (Compute Canada / Alliance)

1. **Clone and set up**, once, on a login node:
   ```bash
   cd ~ && git clone <this repo> EnviorementalAgent && cd EnviorementalAgent
   bash slurm/setup_nibi.sh      # two venvs in $SCRATCH (vLLM server, agent client), downloads Qwen3-8B, runs tests
   ```
   This uses the Alliance wheelhouse for vLLM when available (`avail_wheels vllm`) and
   falls back to PyPI. If pip-installed vLLM gives you trouble, use the official
   container instead: `SERVER_MODE=apptainer bash slurm/setup_nibi.sh`, then submit
   jobs with `SERVER_MODE=apptainer`.
2. **Set your allocation:** edit `#SBATCH --account=def-CHANGE_ME` in `slurm/serve_and_run.sh`.
3. **One job** (vLLM starts on the job's GPU; the experiment talks to it on localhost):
   ```bash
   sbatch slurm/serve_and_run.sh --env town --protocol compgen --conditions none retrieval seed oracle \
          --universes 0 1 --views zoom flat --max-actions 60 --out $SCRATCH/worldseeds/results/try1
   tail -f logs/worldseeds-<jobid>.out     # vLLM log: logs/vllm-<jobid>.log
   ```
4. **Pilot on the town board first** (2 jobs, a few hours): checks that Qwen is neither at 0 with
   the true laws nor at 1 without memory, how long a board episode takes, and how it handles
   wrong notes and testimony:
   ```bash
   bash slurm/pilot_board.sh
   python scripts/analyze.py $SCRATCH/worldseeds/results/qwen3-8b/pilot/* --by condition variant phase
   ```
   If the true-laws condition stays near 0, make the board easier before the full study
   (fewer requests or more days: `board` / `days` in `worldseeds/envs.py`, `_board()`).
5. **Full study** (95 GPU jobs, one per environment × protocol × universe; board and town also
   get a library job and a source-reliability job):
   ```bash
   bash slurm/submit_all.sh
   ENVS=board bash slurm/submit_all.sh                          # town board only (35 jobs)
   MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/submit_all.sh    # scaling run (download it first via setup)
   python scripts/analyze.py $SCRATCH/worldseeds/results/qwen3-8b --curve
   ```

Notes:
* Compute nodes run offline (`HF_HUB_OFFLINE=1`), so weights must be downloaded by
  `setup_nibi.sh` first. To use another model, run `MODEL_ID=... bash slurm/setup_nibi.sh`
  and submit with the same `MODEL_ID`.
* Throughput comes from running many episode *chains* concurrently (vLLM batches them).
  Raise `--repeats` or add conditions to fill the GPU; `--concurrency` caps in-flight episodes.
* Episodes run with `tool_choice=required`. History is trimmed to the last
  `--history-items` items, because the world itself keeps the state. If a model replies
  in plain text it gets nudged to continue (`nudges` in the logs).
* Results are written to `episodes.jsonl` (one row per episode), with optional
  `traces.jsonl` (`--save-traces`) and the final learned seeds under `seeds/`.

## SeedVille: the mini town

```
town map -> locations (farm, plaza, shop, forest, homeN) -> objects and people
```

The goal of each episode is to get a trophy from a quest villager. That villager hands it
over (`talk`) once their requirements are met. The four blocks combine freely:

| block | what it adds | hidden law (randomised per universe) |
|---|---|---|
| `farming` | Villager wants a fresh crop. Pick the right seed packet, plant it in the right plot, water it, wait two nights, harvest | which **soil** and which **season** each crop needs |
| `gifting` | Villager needs friendship 2, which takes two *liked* gifts. Decoys match on the other attribute | gifts liked by shirt **colour**, or by the **category** the villager's job prefers (and which category each job likes) |
| `shop` | Needed goods must be bought, with exactly enough coins (buying a decoy can make the task impossible) | none |
| `schedule` | Villagers are home mornings and evenings, and somewhere else at midday | **where** villagers spend middays |

Every valid action takes one tick of a 12-tick day. `sleep` (or running out of ticks) ends the
day: crops grow overnight and you wake at the farm. A plot's soil and a villager's job are
only visible after `zoom_in`. Universe 0 follows common sense (bakers like food); the
others are shuffled, so the model can't rely on Stardew-style prior knowledge.

### The town board: a reason to live in the town (`--env board`)

The classic town goal is a single trophy. With `--env board` the goal is the **town board** in
the plaza instead: four requests posted by different villagers, to finish within one week
(7 days). The episode ends when all four are ticked off or the week runs out; the score is
the share of requests done (`board_done / board_total`), with days and actions used.

| request | what it asks | what it needs to know |
|---|---|---|
| harvest | "bring me something fresh from your farm" | which seed grows this season, in which soil |
| friends | "let's become friends" (friendship 2) | which gifts this villager loves |
| fetch | "bring me the red ruby that Bram keeps" | Bram hands it over only once you are on good terms (friendship 1, with gifting) |
| buy | "bring me the blue bell from the store" | coins come from finished requests (4 each), so order matters |

So the villagers matter: they post the work, hold what others need, and move around on a
schedule. Time matters too: crops need nights, so a good agent plants first and does
other requests while they grow. All 2,160 boards generated in a sweep (6 universes, every block combination, 3–6 requests)
are solvable by the oracle, in about 30 actions and 4 days on average.

Heuristic agent, universe 1, 20 unseen board towns:

| | none | library, unsorted pile | library, sorted shelves | seed in the head | true laws |
|---|---|---|---|---|---|
| share of requests done | 0.57 | 0.97 | 1.00 | 1.00 | 1.00 |
| whole board done | 0.20 | 0.90 | 1.00 | 1.00 | 1.00 |

The heuristic agent saturates once it knows the laws; whether an LLM does is what the Nibi
pilot (`slurm/pilot_board.sh`) checks first.

```bash
python scripts/run_experiment.py --env board --policy heuristic --conditions none seed library \
    --universes 1 --n-train 30 --n-test 20 --max-actions 200 --out results/board_pilot
python scripts/play.py --env board --mode oracle --blocks farming gifting shop schedule
```

### Second-hand knowledge with controlled reliability (`--source-errors`)

Knowledge from other agents is only useful if you can tell when it is wrong. With
`--source-errors 0 0.25 0.5` (town or board env), every rate becomes one variant:

* **Library notes by other agents** (`library`, `library_flat`): three authors (Ada, Ben, Cleo)
  each write down the laws, and each claim is wrong with the given probability. Errors are
  consistent: an author who is wrong about melons is always wrong about melons.
* **Villager testimony** (`testimony`): `ask <villager>` makes a villager say what their trade
  taught them (the baker and doctor know seasons, the florist and librarian soils, the innkeeper
  and fisher where people go at midday, everyone knows what gifts they love). That share of
  villagers is consistently wrong. Nothing is carried between towns.

Rows record `source_error`, `asks`, `heard_claims`, `heard_wrong` and, for the library, how many
claims on the shelves are right. The heuristic baseline has two trust policies (`--trusts`):
`blind` counts every claim as strong evidence; `calibrated` weighs a source by how often its
claims agree with what the agent itself has seen. For the LLM, how much to trust is its own
decision, which is the point of the experiment.

Heuristic agent, board, universes 1 and 3, 40 unseen towns (share of requests done):

| source | trust | 0% wrong | 25% wrong | 50% wrong |
|---|---|---|---|---|
| library notes | blind | 1.00 | 0.77 | 0.37 |
| library notes | calibrated | 1.00 | 0.86 | 0.47 |
| testimony | blind | 0.64 | 0.55 | 0.43 |
| testimony | calibrated | 0.63 | 0.57 | 0.48 |
| (no memory) | | 0.49 | | |

At 50% error a library the agent believes blindly (0.37) is worse than no memory (0.49).

### The library: memory that lives in the world

With `library` / `library_flat` the agent carries **nothing** between towns. Instead, every
town of a universe has a library (location `library`). After each town a librarian
consolidates what happened and rewrites the shelves (`worldseeds/town/library.py`):

* `library`: one shelf per topic (`farming`, `gifting`, `schedule`, `shop`, `general`).
  `read shelf_farming` lists every note on that topic.
* `library_flat`: the same notes as one unsorted pile, read four notes per page.

Reading is an `act` like any other, so it costs an action and a tick of game time, and the
agent has to walk to the library first. That makes the value of *organising* memory
measurable: same content, different retrieval cost. Agents can also leave notes with
`write_note(shelf, text)` (LLM tool) or `act("write", shelf, text)`. Notes are attributed
(`note by <author>`), which is the hook for the next steps: notes with a controlled error
rate (trust), wrong testimony from villagers, and several agents sharing one library.

Each result row records `library_reads`, `library_entries`, `library_notes`,
`library_claims_correct/library_claims` and the shelves as the agent found them (`library`),
so `scripts/export_replay.py` can replay library runs exactly.

Heuristic agent, 30 unseen test towns after 40 training towns:

| condition | universe 1 success | actions | reads | universe 3 success |
|---|---|---|---|---|
| none | 0.27 | 57.0 | 0 | 0.27 |
| seed (in the agent's head) | 0.80 | 44.7 | 0 | 0.57 |
| library, sorted shelves | 0.77 | 45.0 | 2.4 | 0.53 |
| library, unsorted pile | 0.63 | 48.5 | 4.0 | 0.50 |

In Play mode (`serve_ui.py`) choose the library type when you grow a town. The universe's
library persists across towns while the server runs, so notes you write are still there in
the next town.

### SeedVille game client (Phaser 3)

`web/` is a 2D game client built with [Phaser 3](https://phaser.io) (vendored in `web/vendor`, MIT).
It renders the Python engine's state, so what you see is exactly what the agent played.

* **Scenes like Stardew Valley:** the town is split into a farm, the town square, a residential
  lane, the mountain (forest, pond, mine) and the beach (pier), plus interiors for the shop, the
  six workplaces and every home. Travel walks through exits and doors with fade transitions; M
  opens the town map. Maps are Tiled JSON (`web/assets/maps/*.json`, editable in the
  [Tiled](https://www.mapeditor.org) editor).
* **Engine features used:** tilemaps, sprite-sheet walk cycles in 4 directions,
  Y-sorted sprites, BFS pathfinding, a follow camera with map overview (M), day/evening lighting
  with lamp and window glow, seasonal weather particles, and a Stardew-style HUD (clock,
  quest checklist, toolbar, dialogue with portraits, action-energy bar).
* **Art:** original 16 px pixel art generated by `web/tools/make_assets.py` (terrain per season
  with autotiled edges, buildings, trees, crops by growth stage, items, villagers and portraits).
  Sheets use standard layouts (16x16 tiles, 16x32 characters, 4 rows x 4 frames), so a
  downloaded pack can replace them: keep the file names and frame order.
* **Replays:** `python -m http.server -d web` and open it, or use the published page. Three demo
  runs on the same town (explorer without memory, explorer with a learned seed, oracle).
  Rebuild with `python scripts/build_web.py`.
* **Play it yourself:** `python scripts/serve_ui.py`, open http://localhost:8765 and press Play.
  Click places to walk, click things to act; "Let the oracle finish" hands over control. On Nibi
  run it on a login node and use `ssh -L 8765:localhost:8765`.
* **Watch Qwen:** for a run made with `--save-traces`, list episodes with
  `python scripts/export_replay.py <run_dir> --list`, export one with
  `--chain ... --episode N -o ep.json`, then press "Load replay" on the page.

## Protocols

| protocol | tests | variants |
|---|---|---|
| `compgen` | H4/RQ8: train on 1–2-block worlds, test on unseen 3–4-block compositions | conditions × `zoom`/`flat` |
| `persistence` | H1/RQ1: 3 goals per world (gems / trophies), solved one after another | `persistent` vs `reset` world |
| `law_shift` | H5/RQ7: laws change mid-stream | seed with/without recency `decay` |
| `multiagent` | RQ9: 4 specialised agents | `shared` vs `independent` seed |
| `curriculum` | RQ10: seed-mutation curriculum | `curriculum` vs `uniform` sampling |

## Sanity results (heuristic agent, CPU)

These check the pipeline only. They are not LLM results.

SeedVille:
* All 4,508 generated goals (every block combination, 6 universes, multi-goal) are solvable by the oracle.
* After 40 training towns, the learned seed recovers 10–14 laws, all of them correct, in
  both colour-gift and category-gift universes.
* On unseen block combinations, the heuristic agent's success rises from **0.30–0.63 without
  the seed to 0.97–1.00 with it**, and actions drop from ~49 to ~25 (universes 0, 1, 4, 5).
* `multiagent`: a shared seed gives 0.69 test success vs 0.19 for an independent agent.
* `law_shift`: after the laws change, the decayed seed scores 0.56 vs 0.31 without decay.
* `persistence`: later goals succeed 0.62–0.75 in a persistent town vs 0.19–0.25 when it is reset.

Dungeon:

* All 8,476 generated worlds (every block combination, 6 universes, multi-goal) are solvable by the oracle.
* The learned seed recovers the true laws from perceived evidence and is never confidently
  wrong, including counter-intuitive ones such as keys matching by shape or material.
* `persistence`: by the third goal a persistent world needs ~12.6 actions vs ~28.8 when reset.
* `law_shift`: a non-decayed seed drops to 0.92 success after the shift; the decayed seed stays at 1.00.
* `multiagent`: the shared seed knows 5 laws vs 2 for an independent agent.
* Interventional similarity is 1.00 within a universe vs 0.60 across universes; appearance-based similarity is 0.35 vs 0.33.
