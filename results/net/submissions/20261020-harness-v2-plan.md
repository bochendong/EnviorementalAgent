# Protocol-v2 single-agent harness comparison — submitted

Three new jobs were explicitly authorized on October 20, 2026. They compare settings within protocol v2; the completed October 17 protocol-v1 comparison remains a historical result and is not directly comparable.

| Label | Run | Slurm job | Thinking | Tool choice | Output limit |
|---|---|---:|---|---|---:|
| H1 | 20261020-h1-think-required | 24645791 | on | required | 8192 |
| H2 | 20261020-h2-nothink-required | 24645795 | off | required | 8192 |
| H3 | 20261020-h3-nothink-auto | 24645806 | off | auto | 8192 |

Each job runs only `official-single` and `port-single`, 50 identical GSM8K questions, with eight question processes. All three use Qwen3-8B, one full H100, four CPUs, 32 GB RAM, an eight-hour job limit, temperature 0.6, top-p 0.95, top-k 20, a 65,536-token model context and a 39,321-token estimated history budget. The existing dataset and author-code cache was copied from the completed comparison; hashes of the full inputs and selected questions match across all three jobs.

Submitted at approximately **2026-10-20 02:54 EDT (America/Toronto)**. At **02:55:19 EDT**, all three were `PENDING (Priority)`, with no assigned node or scheduler start estimate. Running-time estimates are provisional and exclude unknown queue delay. No smoke, calibration or four-arm job was submitted.

## Source and verification

The user's protocol-v2 implementation is commit `2e4f9213ba82afd0718a55e1d3d7de37dfd2ed5e`. Review found a trace collision: every parallel worker receives a one-question list, so saving by its local index overwrote `q0.jsonl.gz`. The submitted source adds the global question index to worker tasks and trace filenames. The change affects diagnostic persistence, not prompts or scoring.

Pinned run source: **`a220bb0c4ce5f76f20388c3cd339209bfc39d889`** on the work branch, in a clean isolated Nibi worktree at `/scratch/bdong/worldseeds/code/2e4f921-20261020-harness`. Existing source directories and old jobs were not changed.

- Two local checkpoint/order tests passed. This local virtual environment lacks SymPy, so the port integration was verified in Nibi's module-loaded runtime instead.
- All three focused parallel tests passed on Nibi. The integration test runs real spawned workers against a local mock HTTP server, checks official request counts, then checks that two port questions save two readable compressed traces containing the corresponding question.
- The fixed source was verified byte-for-byte against the published commit before its worktree HEAD/index was aligned; the submission helper requires a clean source checkout.
- Each submitted job's GPU, CPU, memory, time limit and working directory were verified with Slurm.

## Analysis to perform after completion

Verify 50 records for each selected arm, the aggregate report/checkpoint agreement, 50 distinct readable port trace files, and one diagnosis per question. Read failure traces before attributing causes. Report the outcome categories, all submissions and normalization events, errors, context trims, per-arm wall time and recorded tokens, plus the paired bootstrap interval for port-single minus official-single.

Compare H1/H2 for thinking with required tools fixed, and H2/H3 for tool choice with thinking off. Tool choice is used by the port; it is not sent in the official plain-chat sampling arguments, so H2/H3 official arms are replicate baselines under the same actual settings. Sampling is stochastic; this is one run per setting. A point difference within five percentage points is the proposed progression gate, not a statistical equivalence claim.

Inspect diagnostic completeness rather than assuming the filename alone establishes a full trace: transcripts currently expose member history and turn outputs; history trimming or an interrupted/failed SDK run can limit what is retained. Environment operation events and checkpoint diagnosis records must also be read.

Only these three jobs are authorized by the submission manifest. No automatic retry, debate expansion or calibration is configured by this submission. The previous comparison's completed email automation remains paused.

## Records

- [Manifest](20261020-harness-v2-comparison.json)
- [Initial Slurm status and resource checks](20261020-harness-v2-initial-status.json)
- [Submission helper with lock and durable job IDs](20261020-harness-v2-submit.py)
- [H1 run metadata](../runs/20261020-h1-think-required/), [H2 run metadata](../runs/20261020-h2-nothink-required/), [H3 run metadata](../runs/20261020-h3-nothink-auto/)
