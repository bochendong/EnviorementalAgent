# World Seeds

[English](README.md) | [中文](README.zh-CN.md)

World Seeds is a research environment for agents that **learn how a world works and remember
it**. A world is grown from a compact *seed* that holds hidden laws. The agent explores it,
zooms in on details, acts, and afterwards consolidates what it saw into a learned seed (its own
world model). That seed then helps it in the next world.

```
WorldSeed --grow--> lazy, zoomable, persistent world --zoom / act--> events
    ^                                                                  |
    |              (hidden laws: the agent never reads them)           v
learned seed (world model)  <------------  consolidate (only what the agent perceived)
```

Everything runs on a laptop CPU. LLM agents use the
[OpenAI Agents SDK](https://github.com/openai/openai-agents-python) against any
OpenAI-compatible server; the default is the free model **Qwen3-8B on vLLM**, and ready-made
SLURM scripts run the full study on the Nibi cluster (Compute Canada / Alliance).

## The environments

**SeedVille** is a small Stardew-style town: your farm, a plaza, a general store, eight
villagers with jobs, homes and workplaces, the forest, the mountain and the beach. A clock runs
(12 ticks a day), crops grow overnight, and villagers move around. Each *universe* has its own
hidden laws:

| block | what it adds | hidden law |
|---|---|---|
| farming | plant, water and harvest crops | which soil and which season each crop needs |
| gifting | make friends with liked gifts | gifts are liked by shirt colour, or by the category each job prefers |
| shop | buy what you need with limited coins | (none) |
| schedule | villagers move at midday | where everyone goes at midday |

Universe 0 follows common sense (bakers like food); universes 1 and up are shuffled, so a
language model cannot rely on what it already knows and has to find out.

| env | goal of an episode |
|---|---|
| `town` | get one villager's trophy (they hand it over once their needs are met) |
| `board` | finish a **town board** of four villager requests within a week: bring a fresh crop, become friends, fetch an item another villager keeps, buy something with earned coins |
| `dungeon` | a tighter control world: rooms, doors, keys, jars, switches, machines and boulders |

Memory can also live *in* the town: a **library** with shelves by topic, **notes** written by
other agents, **villagers** who tell you what their trade taught them (some of them wrongly),
**teammates** in the same town, and a **hive** of many agents in many towns sharing one memory.

## Quick start (CPU, no GPU needed)

```bash
git clone https://github.com/bochendong/EnviorementalAgent.git && cd EnviorementalAgent
pip install -r requirements.txt
pytest -q                                   # all tests, about 10 s
```

**Play it yourself** (text). Commands: `look`, `in <id>` (zoom in), `out`, any verb such as
`go plaza`, `take s1`, `plant p1 s1`, `give v3 i2`, `talk v3`, `ask v3`, `sleep`, `quit`.

```bash
python scripts/play.py --env board --mode human --blocks farming gifting schedule --universe 2
python scripts/play.py --env board --mode oracle --blocks farming gifting shop schedule   # watch the solver
```

**Play it in the browser** (pixel-art client built with Phaser 3). It shows recorded replays and
lets you play live against the real engine; press `M` for the town map.

```bash
python scripts/serve_ui.py                  # then open http://localhost:8765
```

**Run an experiment with the built-in heuristic agent** (no LLM; checks the pipeline):

```bash
python scripts/run_experiment.py --env board --policy heuristic --protocol compgen \
       --conditions none seed oracle library --universes 1 --max-actions 200 --out results/smoke
python scripts/analyze.py results/smoke --by condition phase
```

## Running with an LLM

Any OpenAI-compatible endpoint works, for example a local vLLM server:

```bash
vllm serve Qwen/Qwen3-8B --served-model-name qwen3-8b \
     --enable-auto-tool-choice --tool-call-parser hermes
export WS_BASE_URL=http://localhost:8000/v1 WS_MODEL=qwen3-8b WS_API_KEY=EMPTY
python scripts/play.py --env board --mode llm --condition none --verbose      # one episode
python scripts/run_experiment.py --env board --protocol compgen \
       --conditions none seed oracle --universes 1 --n-train 8 --n-test 4 \
       --max-actions 200 --max-turns 320 --save-traces --out results/qwen_try
```

| variable | default | meaning |
|---|---|---|
| `WS_BASE_URL` | `http://localhost:8000/v1` | OpenAI-compatible server |
| `WS_MODEL` | `qwen3-8b` | served model name |
| `WS_API_KEY` | `EMPTY` | API key (vLLM ignores it) |
| `WS_THINKING` | `0` | `1` keeps Qwen3's thinking mode |
| `WS_TOOL_CHOICE` | `required` | use `auto` if the server does not support `required` |

The agent's tools are `observe`, `zoom_in`, `zoom_out` and `act`, plus, depending on the
condition, `predict` (ask the learned seed before acting), `recall` (episodic memory),
`write_note` (library) and `tell` (teammates).

## Experiments

`scripts/run_experiment.py --protocol <protocol> --conditions <memory conditions> ...`

| protocol | question |
|---|---|
| `compgen` | trained on towns with 1–2 blocks, does memory help in unseen combinations of 3–4? |
| `persistence` | does a persistent world (your fields, your friendships) act as memory? |
| `law_shift` | when the laws change, does a seed with recency decay recover? |
| `multiagent` | do agents that pool their seeds learn faster than alone? |
| `curriculum` | does growing new worlds by mutating seeds beat uniform sampling? |
| `team` | several agents on one board: alone, independent, library, messages, merged seeds |
| `hive` | many agents in parallel towns sharing one memory: groups, consolidation, verification, a director, faulty agents |

| condition | what the agent carries from one world to the next |
|---|---|
| `none` | nothing |
| `trajectory` | logs of its last episodes |
| `retrieval` | an episodic store it can search (`recall`) |
| `seed` | the learned seed, with `predict` |
| `seed_llm` | the seed plus free-text rules written by an LLM consolidator |
| `oracle` | the true laws (upper bound) |
| `library` / `library_flat` | nothing; memory is on library shelves in the town (sorted by topic / one unsorted pile) |
| `testimony` | nothing; villagers can be asked (`--source-errors` makes some of them wrong) |

Useful options: `--source-errors 0 0.25 0.5` (wrong notes and testimony), `--n-crops 64` (a
bigger universe with 138 laws and a long tail of rare crops), `--hive-sizes 1 4 16 64`,
`--hive-faulty 0 0.25`, `--views zoom flat`, `--repeats`, `--save-traces`.

Results are written to `<out>/episodes.jsonl` (one row per episode), `traces.jsonl` (tool
calls, with `--save-traces`), `seeds/` (learned seeds) and, for the hive, `hive.jsonl` (one
row per wave). Summaries:

```bash
python scripts/analyze.py <out> --by condition variant phase --curve
python scripts/analyze_hive.py <out> --curve
python scripts/export_replay.py <out> --list        # turn an LLM episode into a browser replay
```

## Running on Nibi (Compute Canada / Alliance)

1. **Set up once** on a login node. This creates two virtual environments in `$SCRATCH` (vLLM
   server, agent client), downloads Qwen3-8B and runs the tests:
   ```bash
   git clone https://github.com/bochendong/EnviorementalAgent.git ~/EnviorementalAgent
   cd ~/EnviorementalAgent && bash slurm/setup_nibi.sh
   ```
   If the pip-installed vLLM gives trouble, use the official container:
   `SERVER_MODE=apptainer bash slurm/setup_nibi.sh` (and submit with `SERVER_MODE=apptainer`).
2. **Set your allocation**: replace `def-CHANGE_ME` in `slurm/serve_and_run.sh` and
   `slurm/hive_cpu.sh`.
3. **Pilot first** (4 GPU jobs, a few hours): difficulty of the town board, wrong notes and
   testimony, a two-agent team and a small hive.
   ```bash
   bash slurm/pilot_board.sh
   python scripts/analyze.py $SCRATCH/worldseeds/results/qwen3-8b/pilot/* --by protocol condition variant phase
   python scripts/analyze_hive.py $SCRATCH/worldseeds/results/qwen3-8b/pilot/hive
   ```
   If even the true-laws condition stays near 0, make the board easier before the full study
   (fewer requests or more days in `_board()` in `worldseeds/envs.py`).
4. **Full study** (80 GPU jobs over 5 universes; each job starts its own vLLM server on its GPU)
   and the big heuristic hives (CPU only):
   ```bash
   bash slurm/submit_all.sh                     # ENVS=board / UNIVERSES="1 2" / MODEL_ID=... to narrow it
   sbatch slurm/hive_cpu.sh                     # 1..1024 agents, about 5 h
   python scripts/analyze.py $SCRATCH/worldseeds/results/qwen3-8b --curve
   ```
5. **Watch a run in the browser** from a login node: `python scripts/serve_ui.py`, then
   `ssh -L 8765:localhost:8765 nibi` and open http://localhost:8765.

Other models: `MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 bash slurm/setup_nibi.sh`, then submit with the
same `MODEL_ID`. Compute nodes run offline, so weights must be downloaded by the setup script.

## Repository layout

```
worldseeds/
  envs.py         environment registry: dungeon | town | board
  experiment.py   all protocols (compgen ... team, hive) and the result recorder
  agent.py        the LLM agent (Agents SDK): tools, prompts, episode loop, LLM consolidator
  llm.py          OpenAI-compatible model factory (vLLM / Qwen3 settings)
  memory.py       learned seed (evidence, predict), retrieval and trajectory baselines
  hive.py         many agents sharing one memory: groups, consolidator, verification, director
  similarity.py   interventional vs appearance-based similarity between worlds
  laws.py seed.py world.py oracle.py heuristic.py     the dungeon
  town/           SeedVille
    seed.py       universe laws, town seeds, crops (big universes, long tail)
    world.py      the town: clock, crops, villagers, board, library shelves, testimony
    agents.py     oracle solver, learned TownSeedMemory, heuristic agents
    library.py    the library archive (topic shelves, authored notes)
    sources.py    second-hand claims with controlled error rates
    team.py       several agents in one town
    replay.py     replays for the browser client
scripts/          run_experiment, analyze, analyze_hive, play, serve_ui, build_web, export_replay
slurm/            env, setup_nibi, serve_and_run, pilot_board, submit_all, hive_cpu
web/              Phaser 3 client (game.js, index.html), pixel art and maps, art tools (web/tools)
tests/            all tests (no GPU needed)
docs/             research program, research plan, detailed experiment reference
```

## More

* [docs/experiments.md](docs/experiments.md): every environment, protocol and condition in
  detail, with the heuristic-agent results so far.
* [docs/research_plan.md](docs/research_plan.md): review of the idea and the proposed first paper.
* [docs/world_seeds_program_seed.md](docs/world_seeds_program_seed.md): the research program.
