# World Seeds: experiments and design reference

Detailed reference for every environment, protocol and result in this repository. For a
short introduction and how to run things, see the [README](../README.md)
([中文](../README.zh-CN.md)). The research program is in
[`world_seeds_program_seed.md`](world_seeds_program_seed.md); the review of the idea and the
proposed first paper are in [`research_plan.md`](research_plan.md).

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

See [Repository layout](../README.md#repository-layout) in the README.

## Quick start (laptop, no GPU)

```bash
pip install -r requirements.txt
pytest -q
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
2. **Set your allocation:** edit `#SBATCH --account=def-CHANGE_ME` in `slurm/serve_and_run.sh` (and the CPU scripts `slurm/hive_cpu.sh`, `slurm/frontier_cpu.sh`).
3. **One job** (vLLM starts on the job's GPU; the experiment talks to it on localhost):
   ```bash
   sbatch slurm/serve_and_run.sh --env town --protocol compgen --conditions none retrieval seed oracle \
          --universes 0 1 --views zoom flat --max-actions 60 --out $SCRATCH/worldseeds/results/try1
   tail -f logs/worldseeds-<jobid>.out     # vLLM log: logs/vllm-<jobid>.log
   ```
4. **Pilot on the town board first** (4 jobs, a few hours): checks that Qwen is neither at 0 with
   the true laws nor at 1 without memory, how long a board episode takes, and how it handles
   wrong notes and testimony:
   ```bash
   bash slurm/pilot_board.sh
   python scripts/analyze.py $SCRATCH/worldseeds/results/qwen3-8b/pilot/* --by condition variant phase
   ```
   If the true-laws condition stays near 0, make the board easier before the full study
   (fewer requests or more days: `board` / `days` in `worldseeds/envs.py`, `_board()`).
5. **Frontier studies** (canvas memory, pictures, perception cost, science realism, drug skin,
   festival teams, evolution, robust hives): `bash slurm/submit_frontier.sh`,
   `bash slurm/submit_vision.sh` and `sbatch slurm/frontier_cpu.sh`. See
   [Frontier studies](#frontier-studies).
6. **Full study** (80 GPU jobs over 5 universes; board and hive jobs get 24 h, the others 12 h),
   plus one CPU job for big heuristic hives (`sbatch slurm/hive_cpu.sh`):

   | env | jobs per universe |
   |---|---|
   | board | compgen (memory conditions), library, sources, team |
   | town | compgen, persistence, law_shift, multiagent, curriculum, library, hive |
   | dungeon | compgen, persistence, law_shift, multiagent, curriculum |

   ```bash
   bash slurm/submit_all.sh
   ENVS=board bash slurm/submit_all.sh                          # town board only (20 jobs)
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

### The hive: many agents, many worlds, one memory (`--protocol hive`)

How should thousands of parallel agents share what they learn, so that each of them knows what
all of them found? Large agent swarms (e.g. the ~10,000-agent Navier–Stokes run reported in
September 2026) are organised as groups that talk internally, a consolidator that merges the
groups' intermediate results and sends them back out, people steering agents toward open
questions, and a final verifier. `worldseeds/hive.py` turns each of those into a switch:

| mode | groups share | global consolidation | verify before accepting | director |
|---|---|---|---|---|
| isolated | - | never | - | - |
| serial | one agent plays the wave's worlds in a row | - | - | - |
| groups | within groups of 4 | never | - | - |
| hive | within groups of 4 | every 2 waves | - | - |
| sync | everyone, every wave | every wave | - | - |
| hive_verified | within groups of 4 | every 2 waves | 2 agents agree, 2:1 majority | - |
| hive_directed | within groups of 4 | every 2 waves | - | worlds chosen to cover the least-known laws |
| hive_full | within groups of 4 | every 2 waves | yes | yes |
| hive_audit, hive_provenance, hive_recent | within groups of 4 | every 2 waves | yes, plus audits / provenance / recency | - |

(See [Robust hives](#robust-hives-liars-provenance-law-shifts) for the last three.)

Every agent plays its own world each *wave*. `--hive-faulty 0.25` makes a quarter of the agents
report consistently wrong findings. A new agent is then tested with the hive's shared memory.
Results go to `hive.jsonl` (one row per wave: laws known per agent, in the global seed, wrong
laws, messages); summarise with `python scripts/analyze_hive.py <dir> --curve`.

For the hive to have something to learn, universes can be made bigger: `--n-crops 64` gives 64
crops, each with its own soil and season law (138 laws in all). Towns get 4 crops each, common
crops far more often than rare ones (a long tail), so rare laws need many worlds to be found.
The default universes (4 crops) are unchanged.

Heuristic agents, board, 64 crops (138 laws), 10 waves, universe 1 (laws an average agent knows /
wrong laws in the shared memory):

| mode | 4 agents | 16 agents | 64 agents | 64 agents, 25% faulty |
|---|---|---|---|---|
| isolated | 18 | 17 | 15 | 11 |
| groups | 38 | 37 | 36 | 24 |
| hive | 38 | 78 | 126 / 0 wrong | 72 / 7 wrong |
| sync | 38 | 78 | 126 / 0 wrong | 73 / 8 wrong |
| hive_verified | 38 | 49 | 90 / 0 wrong | 65 / 2 wrong |
| hive_directed | 66 | 115 | 132 / 0 wrong | 82 / 0 wrong |
| hive_full | 71 | 92 | 138 / 0 wrong | 124 / 0 wrong |

Without sharing, more agents do not make any agent wiser; with sharing, knowledge scales with
the number of agents; directing exploration to what is still unknown is worth about 4x more
agents; and with faulty agents only verification keeps the shared memory clean (at 1,024 agents
with 25% faulty, `sync` stalls at 81 laws, `hive_full` reaches 137 of 138 with none wrong).

```bash
sbatch slurm/hive_cpu.sh        # heuristic hives of 1..1024 agents on CPU (~5 h)
# Qwen hives (1, 4, 16 agents) are part of slurm/submit_all.sh (town env) and slurm/pilot_board.sh
```

### Teams on one board (`--protocol team`)

Several agents (Ana, Bo, Cy, Di) live in the same town at the same time
(`worldseeds/town/team.py`). Each has its own body: position, bag, what it has inspected, and
action budget. The farm, coins, board and clock are shared. The clock moves one tick per round
of moves, so a team gets more done per day. An agent in bed waits until everyone still working
is in bed (or the day runs out).

The protocol first lets each agent specialise: agent *a* plays its own towns containing block
*a* (farming, gifting, shop, schedule) and learns its own seed. Then every test board is played
once per sharing mode (`--team-modes`):

| mode | who plays | what is shared |
|---|---|---|
| solo | agent 0 alone | nothing |
| solo_matched | agent 0 alone, with the team's compute (N× actions, the clock moves one tick per N actions) | nothing |
| independent | whole team | nothing; each carries its own seed |
| library | whole team | everyone's seed is in the library as signed notes (walk there to read) |
| messages | whole team | `tell(teammate, message)` (one action per message) |
| merged | whole team | everyone carries the merged seed (upper bound for sharing) |

One row per team episode: `board_done`, `days_used`, `team_actions`, `agent_actions`,
`messages`, `library_reads`. Heuristic teams (three agents, universes 1 and 3, 32 boards each):

| solo | independent | library | messages | merged |
|---|---|---|---|---|
| 0.92 | 0.97 | 0.99 | 1.00 | 1.00 |

(share of requests done; the heuristic splits the board by request number, an LLM team has to
agree on it.)

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

## Frontier studies

Each study below asks one question that current agent research cares about and turns it into
a switch on the same environment. Numbers come from the heuristic agent on CPU (universes 1 and 3
unless noted). They show that each switch does what it should. They are not LLM results; the LLM
versions are the jobs in `slurm/submit_frontier.sh`.

### Measuring fairly: compute-matched baselines, redundancy, reflection scores

A team of N agents spends N times the actions. A fair comparison gives one agent the same
compute, so the team modes include **`solo_matched`**: one agent with N times the action budget,
for which the clock moves one tick per N actions (as for a team of N). The hive modes include
**`serial`**: one agent plays the wave's N worlds one after another, learning as it goes (the
same total experience as N agents, without parallelism).

| team (3 agents, 32 boards) | solo | solo_matched | independent | library | messages | merged |
|---|---|---|---|---|---|---|
| share of requests done | 0.92 | 0.95 | 0.97 | 0.99 | 1.00 | 1.00 |

| hive, 64 crops (138 laws), 10 waves | 4 agents | 16 agents | 64 agents |
|---|---|---|---|
| serial (one agent, same worlds) | 38 | 78 | 127 |
| sync (all agents, shared every wave) | 38 | 78 | 126 |

With the same compute, a lone agent is almost as good as an uncoordinated team, and parallel
agents learn exactly as much as one agent playing the same worlds in a row: parallelism buys
wall-clock time, not knowledge. What a team adds is sharing (`library`, `messages`) and tasks
that need two bodies (see the festival below). Every hive wave also records `redundant_share`,
the share of reports that found no law the hive had not already found (about 0.9 at 64 agents),
and `novel_laws`.

The LLM consolidator (`seed_llm`) now also states the laws it believes, as (law, value) pairs.
They are scored against the truth: `reflection_correct`, `reflection_wrong` and
`reflection_invalid` (a law that does not exist or a value it cannot take). Reflection quality is
measured, not assumed.

### Perception has a cost (`--zoom-budget k`)

Looking closely at something new uses attention: `k` close looks per day, refilled at night.
Looking again at what you already inspected is free. Without attention left, `zoom_in` returns only
the coarse view. With a budget, an item's category is also a fine detail. Rows record
`perception_spent`; LLM rows record `observed_tokens` (text the environment returned).

The heuristic agent barely notices: the seed agent keeps 0.97 test success with no budget, k = 4
and k = 2, although its zoom calls rise from 21 to 30 to 51 per town. It already looks only at what it
needs. The knob is meant for LLM agents, which tend to look at everything.

### Memory as a canvas (`--context canvas | image`)

Instead of a growing transcript, the LLM sees its instructions, a **canvas** redrawn every step,
and only its last 6 tool calls. The canvas (`worldseeds/canvas.py`) is a fixed-size,
multi-resolution picture of what the agent has perceived:

* sharp: the place it is in, with every detail it noticed (soils, jobs, categories)
* medium: the 3 places it visited most recently, by name
* blurred: places visited longer ago, as one line of counts
* the map of places not visited yet, the goal, the status line, the last events
* `NOTES`, which the agent rewrites with `rewrite_notes(text)` (edited in place, at most 800
  characters, never appended)

It is cut to `--canvas-chars` (default 3000). When space is short, older places are blurred
first, then fewer events are kept, then the oldest places are dropped. Old detail is not lost:
it is still in the world, and the agent can go back and look again (the world is the
full-resolution memory).

With `--context image` the same canvas is rendered into page images (`worldseeds/render.py`): the
current place in large type, recent places smaller, old ones smallest (forgetting by blur, as in
optical context compression). It comes together with a picture of the current view, whose
resolution follows the zoom level: the town map is a schematic, a place is a sheet of object
cards with sprites, an object is a large icon with its perceived details. This is for
vision-language models (`slurm/submit_vision.sh`, Qwen3-VL-8B). Rows record `context`,
`canvas_mean_chars`, `notes_chars`, `input_tokens`.

### Science realism

The town can be made as messy as a lab:

| switch | what changes |
|---|---|
| `--noise p` | each night a crop's outcome flips with probability p (pests, lucky sprouts) |
| `--screen-error e` | a new verb, `screen <plot> with <seeds>`: a quick test that takes no game time and is wrong with probability e (an in-silico screen vs the slow, exact experiment) |
| `--confounder` | daily weather. Rain waters every plot, but on rainy nights one hidden soil floods and kills what grows in it. `--deconfound` makes the learner set rainy nights aside |
| `--publication-bias` | the library hears only from towns that finished their board, and only their successful events |
| `--skin drug` | the same world told as drug discovery: crops are compounds (AX-101, ...), soils are targets (kinase, protease, ...), seasons are protocols, plots are wells, planting is dosing, harvesting is assaying, villagers are experts, the farm is the lab, a quick screen is a docking run. A one-to-one word map at the agent's tool layer (`worldseeds/skin.py`). The laws, metrics and heuristics are unchanged, so a skinned LLM run is directly comparable to a plain one |

Heuristic agent, test success / share of requests done (30 training towns, 16 test towns per universe):

| setting | none | seed | library |
|---|---|---|---|
| clean | 0.09 / 0.48 | 0.97 / 0.99 | 1.00 / 1.00 |
| noise 0.1 | | 0.44 / 0.83 | 0.84 / 0.95 |
| noise 0.25 | 0.25 / 0.66 | 0.56 / 0.86 | 0.56 / 0.81 |
| noise 0.25 + publication bias | | | 0.41 / 0.82 |
| confounder | | 0.66 / 0.91 | |
| confounder, deconfounding learner | | 0.50 / 0.85 | |
| screen, error 0.25 | — / 0.54 | 0.34 / 0.76 | |
| screen, error 0.1 | — / 0.55 | 0.72 / 0.91 | |

What it shows:

* Noise hurts a learner that trusts every outcome, and helps an agent without memory a little
  (some wrong plantings now sprout).
* Publication bias is the clearest effect: with only positive results from successful towns, the
  library makes more claims and more of them are wrong (3 of 8 correct at noise 0.25; unbiased
  libraries are corrected by the failures they also hear about).
* Deconfounding is not free: setting rainy nights aside removes the confounder but also a third of
  the evidence, and within 30 towns that costs more than it saves.
* Cheap screens hurt this learner. With a perfect seed, screening loses nothing (0 failed harvests
  in 30 towns at error 0.1). But during training, screens replace real plantings and add only weak
  votes, so the learned seed is less complete. It is a real trade-off of virtual screening, which an
  LLM agent has to manage itself.

### Self-evolving agents (`--protocol evolve`)

Generations of agents that inherit **how to learn**, not what was learned (`worldseeds/evolve.py`).
Every life starts from an empty head, learns from `--n-train` towns and is tested on `--n-test`
held-out towns.

* heuristic policy: the genome tunes the learner (confidence threshold, evidence needed, weights of
  a success, a failure and a quick test, forgetting, deconfounding)
* llm policy: a **playbook** (strategy text in the instructions). After each life a mentor (an LLM)
  reads how the life went, grades it, states the laws it thinks were found, and rewrites the
  playbook for the next generation

Parents come from an archive of the best lives so far (a strategy library). The elite survives
unchanged; other children are crossed over and mutated (heuristic) or mentored (LLM). Each
generation lives in one universe (cycling through `--universes`), and all its lives meet the same
towns. Each evolution runs twice, with two evaluators:

* `true`: select on test success in held-out towns
* `proxy`: select on what the agent claims (share of laws it is confident about) or, for LLMs, on
  the mentor's self-grade. A weak evaluator, the setting for **reward hacking**

After each generation the archive's best learner lives fresh lives on fixed benchmark towns in every
universe (`phase: generation`). At the end, the initial and the evolved learner live fresh lives in
**unseen universes** (`--transfer-universes`) after k training towns (`--transfer-curve`): is the
evolved learner a faster learner where it has never been? Summaries: `scripts/analyze_evolve.py`.

Heuristic, universes 1–3, noise 0.2, 12 lives × 10 generations, 6 + 6 towns per life:

| selected on | generation | benchmark score | laws claimed | wrongly claimed |
|---|---|---|---|---|
| true | 0 → 9 | 0.81 → 0.81 | 0.48 → 0.50 | 0.17 → 0.07 |
| proxy (claims) | 0 → 9 | 0.81 → 0.78 | 0.39 → 0.56 | 0.06 → 0.13 |

| transfer, unseen universes 5–8 | k = 1 | k = 2 | k = 4 | k = 8 | wrongly claimed |
|---|---|---|---|---|---|
| initial learner | 0.54 | 0.71 | 0.62 | 0.77 | 0.00 |
| evolved on the true score | 0.70 | 0.65 | 0.75 | 0.83 | 0.10 |
| evolved on claims | 0.73 | 0.68 | 0.74 | 0.84 | 0.18 |

Selection on claims inflates claims (0.39 → 0.56 of all laws) and wrong claims (×2) without
improving the true score: the hacking signature. Both evolved learners act on weaker evidence and
learn faster in unseen universes after one town (0.54 → 0.70), but the one evolved on claims carries
twice the wrong beliefs. With an LLM the same protocol asks whether a playbook written by
self-reflection improves the agent or only its self-assessment (the mentor table in
`analyze_evolve.py` puts the self-grade next to the true score).

### The festival: tasks that need a team (`--festival`, `--roles`)

`--festival` adds two requests to every board:

* **dish**: a fresh crop must be carried to a cook, who turns it into a dish, which must then be
  carried to whoever asked. Farming, a hand-over and a delivery depend on each other.
* **together**: a villager wants two farmers in the same place at once. A lone agent can never do it.

It also adds the verb `drop <item>`, to put something down for a teammate. The farm's one watering
can is the scarce tool.

`--roles` gives each teammate **private perception**: the farmer can tell soils apart, the
socialite reads people (trade, friendship), the merchant knows goods (categories). Each perceives
only its own kind of detail, in its training towns as well as on the team board. What the others
need to know must be told. Heuristic teams (3 agents, universes 0 1 2 4, 12 boards each, share of
requests done):

| | solo | solo_matched | independent | library | messages | merged |
|---|---|---|---|---|---|---|
| festival | 0.53 | 0.60 | 0.91 | 0.95 | 0.98 | 0.97 |
| festival + roles | 0.52 | 0.60 | 0.90 | 0.91 | 0.94 | 0.94 |
| `together` requests done | 0.00 | 0.00 | 0.94 | 0.96 | 0.98 | 0.98 |

Now even the compute-matched solo agent falls far behind (0.60 vs 0.91), because some tasks need
two bodies. Roles cost the heuristic team little, because it gives gifts by trial and error whether
or not it can read people. For LLM teams, private perception is the condition under which talking
to each other is necessary.

### Robust hives: liars, provenance, law shifts

**Correlated liars** (`--hive-faulty-mode`): faulty agents can each tell their own lie
(`scattered`), all tell the same lie (`correlated`), or also sit together in whole groups (`groups`,
a biased lab). When the liars are the majority, the truth is a minority and a majority vote accepts
the lie.

**Provenance**: every verified claim keeps who made it and when. Three new modes build on it:

| mode | what the consolidator does |
|---|---|
| `hive_audit` | checks 2 claims per sync against a gold-standard replication (the least replicated first); a failed claim is rejected |
| `hive_provenance` | the same, but a failed audit discredits everything its makers ever claimed |
| `hive_recent` | newer evidence supersedes older: per law, only claims made within 2 waves of its newest claim count |

16 agents, 16 crops (42 laws), 8 waves, universe 1, laws known / wrong in the global seed:

| faulty agents | sync | hive_verified | hive_audit | hive_provenance |
|---|---|---|---|---|
| 30%, scattered lies | 18 / 0 | 22 / 0 | 22 / 0 | 22 / 0 |
| 60%, scattered lies | 12 / 3 | 8 / 6 | 8 / 2 | 9 / 0 |
| 30%, same lie, whole groups | 18 / 4 | 20 / 0 | 20 / 0 | 20 / 0 |
| 60%, same lie, whole groups | 6 / 9 | 9 / 13 | 9 / 11 | 9 / 2 |

When liars agree and are the majority, verification makes things worse (13 wrong laws accepted,
because the lie is well replicated). Checking claims one by one hardly helps (11). Provenance helps
most (2): one failed audit withdraws everything its makers said.

**Law shifts** (`--hive-shift-wave w --hive-shift-share s --hive-shift-laws n`): from wave w, the
worlds of a share s of the agents follow changed laws (n law families change; with 16 crops, about
13 laws). Waves report `stale_global` (changed laws the global seed still believes at their old
value), `stale_agents` (the same in a moved agent's view) and `known_global_now`. The newcomer test
happens in the changed land. Universes 1 and 3, shift at wave 5 of 12:

| everyone moved (s = 1) | stale laws in the global seed, waves 5 → 12 |
|---|---|
| sync | 4.0 → 1.0 |
| hive_verified | 4.5 → 2.5 |
| hive_recent | 4.0 → 2.0 |

| half moved (s = 0.5) | stale global, waves 5 → 12 | right global (old laws) |
|---|---|---|
| sync | 4.0 → 3.5 | 37 |
| hive_verified | 4.5 → 4.0 | 32 |
| hive_recent | 4.0 → 2.0 | 20 |

Raw evidence (`sync`) updates fastest when everyone moves. Verification keeps stale laws longest,
because old claims stay well replicated. When only half the agents move, a single global memory
cannot be right for both regions. Superseding by recency removes stale laws but forgets laws that
are still true elsewhere. Regional truth needs regional memory: this is the open question this
switch is for.

### Running the frontier studies on Nibi

```bash
bash slurm/submit_frontier.sh                    # LLM jobs: context, perception, realism, skin, team, evolve, hive
PILOT=1 bash slurm/submit_frontier.sh            # tiny versions first, to check timing
STUDIES="realism skin" bash slurm/submit_frontier.sh
MODEL_ID=Qwen/Qwen3-VL-8B-Instruct bash slurm/setup_nibi.sh && bash slurm/submit_vision.sh   # pictures
sbatch slurm/frontier_cpu.sh                     # heuristic baselines and large sweeps (CPU, about 6 h)
```

Every job kind was dry-run end to end against a mock OpenAI server (random tool calls, structured
outputs for the consolidator and the mentor, image parts counted): 13 job kinds, no errors.

### Does SeedVille predict real benchmarks? (a transfer study)

The town is a proxy. Its value for research depends on whether **what helps an agent here also
helps it on real scientific tasks**. The plan:

1. **Agents.** About 10 agent configurations that differ in what matters here: model (Qwen3-8B,
   Qwen3-30B-A3B, Qwen3-32B, a VLM), memory (none, trajectory, retrieval, seed, canvas), and with or
   without a playbook evolved in SeedVille.
2. **SeedVille scores.** For each configuration: compgen test success, laws recovered and wrongly
   claimed, reflection correctness, learning speed in unseen universes, the drug skin (same laws,
   scientific story), and the realism settings (noise, screens, publication bias).
3. **Real benchmarks.** The same configurations on public agentic science benchmarks with
   multi-step tool use, e.g. LAB-Bench (protocol and sequence tasks), BixBench (bioinformatics
   analyses in notebooks), and ScienceAgentBench or DiscoveryBench (data-driven discovery).
4. **Test.** Rank correlation (Spearman, Kendall) between SeedVille and real-benchmark scores across
   configurations, with bootstrap intervals; per-skill correlations (noise robustness vs
   replication on real data, reflection correctness vs claim accuracy, skin vs non-skin).
5. **Controls.** Raw model strength (a static QA score) as a covariate, so SeedVille has to predict
   beyond "bigger model is better"; and the plain skin as a control for the scientific vocabulary.

If the rank correlation holds beyond the covariate, SeedVille is a cheap, controllable stand-in for
expensive scientific evaluations: hidden laws with known ground truth, measured exactly. If it does
not, the per-skill correlations show which part of the town is unlike real science.

## Protocols

| protocol | tests | variants |
|---|---|---|
| `compgen` | H4/RQ8: train on 1–2-block worlds, test on unseen 3–4-block compositions | conditions × `zoom`/`flat` |
| `persistence` | H1/RQ1: 3 goals per world (gems / trophies), solved one after another | `persistent` vs `reset` world |
| `law_shift` | H5/RQ7: laws change mid-stream | seed with/without recency `decay` |
| `multiagent` | RQ9: 4 specialised agents | `shared` vs `independent` seed |
| `curriculum` | RQ10: seed-mutation curriculum | `curriculum` vs `uniform` sampling |
| `team` | several agents on one town board (board env) | `solo` / `solo_matched` / `independent` / `library` / `messages` / `merged` (± `--festival`, `--roles`) |
| `hive` | many agents in parallel worlds sharing one memory (town/board) | hive modes × sizes × faulty share (× faulty mode, law shift) |
| `evolve` | generations of learners that inherit how to learn (town/board) | true vs proxy evaluator, transfer to unseen universes |

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
