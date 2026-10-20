# Protocol-v3 single-agent harness comparison

These are the three requested new jobs. Run names retain the requested 20261021 prefix; actual submission occurs on October 20, 2026 (America/Toronto). Previous runs remain intact.

| Label | Run | Questions per arm | Thinking | Tool choice | Output limit |
|---|---|---:|---|---|---:|
| H1 | 20261021-h1-n200 | 200 | on | required | 8192 |
| H2 | 20261021-h2-v3 | 50 | off | required | 8192 |
| H3 | 20261021-h3-v3 | 50 | off | auto | 8192 |

Only `official-single` and `port-single` run. Each job uses Qwen/Qwen3-8B, one full H100, four CPUs, 32 GB RAM, eight question processes and an eight-hour limit. Temperature 0.6, top-p 0.95, top-k 20, model context 65,536, and estimated history budget 39,321 are fixed. The source is pinned to `8b16328c5d295d2d6f0591fba915075160768dda`, protocol 3, in a clean isolated Nibi checkout. No existing source checkout is changed.

Inputs are copied from the previous comparison's cache and hashed. All three use the same full GSM8K test file and author code. H2/H3 use H1's first 50 selected questions (shuffle seed 0), enabling matched 50-question comparisons without incorrectly asserting identical 200-question and 50-question hashes.

## Pre-submission validation

Four focused checks passed in the module-loaded Nibi agent environment (19.58 seconds): the new submit/store-key regression and all three parallel fidelity tests, including real spawned workers against a local mock HTTP server and distinct question trace files. This does not claim a rerun of the full local test suite. The detached source checkout was clean at the pinned commit.

## Analysis specified before results

Check all expected records (H1: 200 per arm; H2/H3: 50 per arm), checkpoint/report agreement, one diagnosis and one readable distinct compressed trace per port question. Read failures before attributing causes. Report each arm's accuracy, wall time and output tokens; paired bootstrap 95% intervals for port minus official; outcome categories, actual submit attempts and errors; and total elapsed time/GPU hours from Slurm. Distinguish invalid submissions, absent submissions, unreadable values and scored wrong answers using raw environment events as well as the derived diagnosis labels. Preserve all checkpoints on failure; no automatic retries.

H1's equivalence margin is ±5 percentage points. A paired 95% interval entirely within that margin supports equivalence for this fixed benchmark/model/budget; a point gap inside the margin alone does not. Two hundred questions do not guarantee a particular interval width. Use the same 20,000 paired bootstrap draws (seed 1) as the previous archived analysis. Compare H1's first 50 questions with H2 for the thinking setting, and H2 with H3 for port tool choice. Official H2/H3 arms are stochastic replicate baselines: plain chat does not consume the port's tool-choice setting.

This sample extends a previously inspected 50-question prefix and is a diagnostic follow-up, not a fresh independent benchmark. The protocol and prompts changed from v2; cross-version comparisons measure the combined protocol change, not an isolated causal effect of either patch.

Provisional runtime after allocation: H1 about three hours, extrapolating the previous 43-minute 50-question H1 run; H2/H3 estimates are more uncertain because the fixes change their behavior. Approximate total cost of four H100 hours is a planning estimate. The three eight-hour limits permit up to 24 allocated GPU hours if all hit their limits. Queue delays are unknown, and scheduler estimates are not actual start times.

No debate expansion, calibration, smoke rerun, email or recurring monitor is configured by this submission. The old completed comparison monitor stays paused. Full four-arm fidelity and calibration remain subsequent decisions.

## Submitted jobs and first observation

Submitted on **2026-10-20 at 13:03:04–13:03:06 EDT (America/Toronto)**. H1 is job **24679535**, H2 **24679536**, and H3 **24679537**. At **13:03:23 EDT**, all three were `PENDING (Priority)`, with `StartTime=Unknown`. Slurm confirmed one full H100, four CPUs, 32 GB RAM, the eight-hour limit, the pinned working directory and account `rrg-hup_gpu` for each job.

## Submission records

See `20261021-harness-v3-comparison.json`, `20261021-harness-v3-initial-status.json`, and `20261021-harness-v3-submit.py` for durable job IDs, observed Slurm states/resources, parameters and input hashes. The submission helper holds a shared lock, records each job immediately, and checks existing plans/queued jobs before any uncertain submission can be repeated.
