# Recorded Qwen workshop pilot

This diagnostic follows Nibi job 23602469, whose players looped on invalid rule syntax and unaffordable studies. Its original outputs remain in `results/town_mig_pilot/23602469` locally and on scratch.

The revised pilot requests one H100 3g.40gb MIG instance, four CPUs, 32 GB host memory and one hour. It keeps the previous task configuration: universe 1, eight workshops with six machines each, notebook capacity 12, four-player budget of 40 actions each versus 160 for solo, one sprint, one order per team member, solo and owners variants, and banquet/prize/fund goals. A single Qwen3-8B service handles at most four sequences, with 32K context.

Job 23612422 enabled Qwen thinking, automatic tool choice and up to 4,096 generated tokens per call. Four players exhausted that allowance before producing an action. Its reasoning and failures remain recorded. Returned reasoning text is model output, not an observation of internal computation.

The next prepared diagnostic (`ws-town-mig-grounded`) restores non-thinking mode, required tool calls and a 1,024-token output cap, keeping full request/response recording. This separates a working action baseline from a future bounded-thinking experiment. Neither this change nor the new consistency checks should be claimed as an isolated improvement in model reasoning.

## Repairs

- All variants and sprints share one event loop; a live model client is no longer reused across closed loops.
- Rule instructions and errors require numeric coefficients and give concrete syntax examples. Examples are explicitly not a machine's answer.
- Unaffordable actions describe cheaper alternatives. Two consecutive budget failures, or three identical rejected calls, stop the player with an explicit status while preserving remaining budget. Zero budget and completed work also stop execution.
- Token usage is counted after each response, including runs that later reach the turn limit or raise an exception.
- Player exceptions remain in the result denominator and cause a nonzero experiment exit after results are saved. Zero completed orders is a behavioral result, not itself a runtime error.

### Observation-grounded feedback (2026-10-09)

- `remember` checks candidate rules only against samples the current player actually obtained through `run`/`study` this sprint. It rejects contradictions with the input, observed value and predicted value; it never tests a note against the hidden answer. Passing limited observations still permits an incorrect hypothesis on unobserved inputs.
- `compute` explicitly labels its result as a notebook prediction rather than a real machine execution.
- Submission errors report actual versus required output on a public order example. They do not reveal the correct chain or an unobserved machine law.
- Three rejected submissions of the same chain stop a player even when free computations are interleaved. Rejected notes do not generate false learning events in the replay.
- HTTP usage is counted before SDK response parsing, so reasoning-only truncated responses are still counted when the SDK raises an error.

## Records

Job 23612422 used `$WS_STORE/results/town_mig_recorded/<job-id>`. The next prepared script uses a new directory under `$WS_STORE/results/town_mig_grounded/<job-id>`.

| File | Content |
| --- | --- |
| `events.jsonl` | Immediately flushed, ordered events with universe/variant/sprint/player tags: full prompts, SDK responses, exact HTTP request and response bodies, tool feedback, engine events, errors and ending status. Authentication headers and API keys are never recorded. |
| `traces.jsonl` | Complete tool arguments, returned observation, location, budget and current order, grouped by player and sprint. |
| `replay.json` | Actual recorded engine events, map, player roles, orders, starting notebooks and metrics for completed sprints. Load this file in `web/codeworld.html`; no separate agent run is used. |
| `process.html` | Expandable viewer of dialogues and tool feedback. Raw returned reasoning is shown when present. |
| `codeworld.jsonl` | Metrics and all player ending statuses; failures are retained. |
| `source.tar.gz`, `source-sha256.json`, `source.patch` | Exact implementation snapshot and hashes, including uncommitted repairs. |
| `config.json`, `commit.txt`, `job.sh` | Experimental configuration, base commit and job script. Effective model settings and dependency versions are also in `events.jsonl`. |
| `vllm.log`, `gpu-samples.log`, `gpu-start.txt`, `timing.txt` | Server messages, sampled GPU memory/cache state, device identity, startup and experiment duration. |

Events are written throughout a sprint, so model/tool/engine evidence survives a later crash or timeout. Browser replays are saved after each completed sprint; an unfinished sprint may require reconstruction from the event log. The HTML viewer can also be regenerated from partial event records:

```bash
python scripts/report_codeworld_run.py <result-directory>
```

Submit from the repository root after login:

```bash
mkdir -p logs
sbatch slurm/town_mig_pilot.sh
```

Before interpreting scores, inspect `statuses`, returned tool errors, reasoning truncation (`finish_reason`), and whether players actually learned, asked questions and delivered orders.
