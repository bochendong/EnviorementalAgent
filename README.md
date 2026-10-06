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
  experiment.py  protocols: compgen, persistence, law_shift, multiagent, curriculum
scripts/  run_experiment.py, analyze.py, play.py, similarity_demo.py
slurm/    env.sh, setup_nibi.sh, serve_and_run.sh, submit_all.sh
tests/    world / memory / scripted-Agents-SDK tests (no GPU needed)
```

## Quick start (laptop, no GPU)

```bash
pip install -r requirements.txt
pytest -q                                              # 13 tests
python scripts/play.py --mode human --blocks lockable fragile machine --universe 1
python scripts/run_experiment.py --policy heuristic --protocol compgen \
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
   sbatch slurm/serve_and_run.sh --protocol compgen --conditions none retrieval seed oracle \
          --universes 0 1 --views zoom flat --out $SCRATCH/worldseeds/results/try1
   tail -f logs/worldseeds-<jobid>.out     # vLLM log: logs/vllm-<jobid>.log
   ```
   Do a short pilot first (e.g. `--n-train 4 --n-test 4 --universes 1`) to check
   tool-calling quality and timing before submitting everything.
4. **Full study** (5 protocols × 5 universes, one GPU job each):
   ```bash
   bash slurm/submit_all.sh
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

## Protocols

| protocol | tests | variants |
|---|---|---|
| `compgen` | H4/RQ8: train on 1–2-block worlds, test on unseen 3–4-block compositions | conditions × `zoom`/`flat` |
| `persistence` | H1/RQ1: 3 gems per world, solved one after another | `persistent` vs `reset` world |
| `law_shift` | H5/RQ7: laws change mid-stream | seed with/without recency `decay` |
| `multiagent` | RQ9: 4 specialised agents | `shared` vs `independent` seed |
| `curriculum` | RQ10: seed-mutation curriculum | `curriculum` vs `uniform` sampling |

## Sanity results (heuristic agent, CPU)

These check the pipeline only. They are not LLM results.

* All 8,476 generated worlds (every block combination, 6 universes, multi-goal) are solvable by the oracle.
* The learned seed recovers the true laws from perceived evidence and is never confidently
  wrong, including counter-intuitive ones such as keys matching by shape or material.
* `persistence`: by the third goal a persistent world needs ~12.6 actions vs ~28.8 when reset.
* `law_shift`: a non-decayed seed drops to 0.92 success after the shift; the decayed seed stays at 1.00.
* `multiagent`: the shared seed knows 5 laws vs 2 for an independent agent.
* Interventional similarity is 1.00 within a universe vs 0.60 across universes; appearance-based similarity is 0.35 vs 0.33.
