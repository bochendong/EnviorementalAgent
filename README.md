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
   Do a short pilot first (e.g. `--n-train 4 --n-test 4 --universes 1`) to check
   tool-calling quality and timing before submitting everything.
4. **Full study** (2 environments × 5 protocols × 5 universes = 50 GPU jobs, one each):
   ```bash
   bash slurm/submit_all.sh
   ENVS=town bash slurm/submit_all.sh                           # SeedVille only (25 jobs)
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

### Pixel UI

`ui/seedville.html` draws SeedVille in a Stardew-style pixel art. It only renders state
produced by the Python engine, so what you see is exactly what the agent played.

* **Replays:** `ui/seedville_demo.html` is a standalone page with three recorded runs on the
  same town: an explorer with no memory, the same explorer with a learned seed, and the
  oracle. Open it in any browser. Rebuild it with `python scripts/build_ui.py`.
* **Play it yourself:** `python scripts/serve_ui.py`, then open http://localhost:8765 and
  switch to Play. Click a place to walk there, click things to take, buy, plant, water,
  harvest, give or talk. On Nibi, run it on a login node and use `ssh -L 8765:localhost:8765`.
* **Watch Qwen:** for a run made with `--save-traces`, list its episodes with
  `python scripts/export_replay.py <run_dir> --list`, export one with `--chain ... --episode N -o ep.json`,
  then load `ep.json` with the page's "Load replay file" button (or bake it in with
  `python scripts/build_ui.py --replay ep.json`).

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
