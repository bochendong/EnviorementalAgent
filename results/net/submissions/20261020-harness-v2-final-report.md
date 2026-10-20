# Protocol-v2 harness comparison — completed and diagnosed

All three jobs completed with exit `0:0`. Each contains 50 official-single and 50 port-single outcomes, a 50-entry diagnosis file and **50 distinct readable compressed port traces**. All 300 checkpoint outcomes match their aggregate reports. The same questions and pinned source `a220bb0c4ce5f76f20388c3cd339209bfc39d889` were used throughout.

## Accuracy and paired uncertainty

| Setting | Official | Port | Port − official | Paired bootstrap 95% interval |
|---|---:|---:|---:|---:|
| H1: thinking / required | 44/50 (88%) | 44/50 (88%) | 0 points | [−10, +10] points |
| H2: no thinking / required | 46/50 (92%) | 9/50 (18%) | −74 points | [−86, −62] points |
| H3: no thinking / auto | 45/50 (90%) | 1/50 (2%) | −88 points | [−96, −78] points |

Intervals were recomputed from paired question outcomes with 20,000 resamples, seed 1. H1 meets the proposed five-percentage-point **point-estimate** gate. With only 50 questions, its ±10-point interval does not establish statistical equivalence. These v2 results cannot be treated as a controlled comparison against the earlier v1 runs, which also differed in protocol and, for the old nonthinking arm, output limit.

Within v2, H1/H2 hold required tool choice and the 8192 output limit fixed; H2/H3 hold thinking off and the output limit fixed. This isolates the intended setting changes across single sampled runs, subject to sampling variability and different run times/nodes. Tool choice is not sent by the official plain-chat arm, making the official H2/H3 arms repeat baselines under identical actual model settings.

## What the failed traces actually show

The original diagnosis labels are preserved. In particular, `submitted a wrong value` is too broad: it also includes submissions rejected **before numeric scoring** because they name a nonexistent store key. The table below is a separate derived classification based on the actual submission errors and environment events, not a rewrite of the raw files.

| Port outcome, mutually exclusive | H1 | H2 | H3 |
|---|---:|---:|---:|
| Solved | 44 | 9 | 1 |
| Never submitted | 0 | 11 | 46 |
| All submissions blocked by missing store key | 3 | 26 | 3 |
| At least one value reached scoring but differed from reference | 3 | 4 | 0 |

**H3 often describes tool use instead of invoking tools.** Of its 49 failed questions, 45 have zero actual environment operations. All 46 never-submitted questions have textual `Observation:` content in saved model turn outputs. For example, [H3 q2](../runs/20261020-h3-nothink-auto/fidelity/traces/port-single/q2.jsonl.gz) computes the correct answer, 80, writes `Action: submit` and JSON containing `artifact: "80"`, then writes “Task submitted successfully.” The trace has no real operation events. The claimed success is model-generated text, not a tool result. This directly demonstrates a tool-protocol failure for that question, rather than a mathematical inability.

**H2 frequently uses the optional `key` argument as though it were an answer label.** In the environment, a nonempty `key` means “read the latest value from this shared-store key” and takes precedence over the supplied `artifact`. Invented keys such as `answer` or `Q` therefore return `no key ...` before the numeric artifact is scored. Thirty of H2's 41 failed questions encounter that error; 26 never reach numeric scoring at all. Twelve failed H2 questions contain at least one literally correct numeric artifact in a rejected submission, which does not mean they would all be solved under a different protocol.

For example, [H2 q1](../runs/20261020-h2-nothink-required/fidelity/traces/port-single/q1.jsonl.gz) submits `240` for reference `240`, but supplies `key: "Q"` and receives `no key 'Q'`. In [H1 q29](../runs/20261020-h1-think-required/fidelity/traces/port-single/q29.jsonl.gz), the sole submission contains correct value `68`, but `key: "answer"` prevents it from being scored. Thus even H1 retains submission-interface friction.

“Different from reference” is not a claim that every such answer is mathematically indefensible. For example, the saved q32 text says 8 AM to 11 PM, the reference is 360, and a port answer of 1800 corresponds to the literal 15-hour interval. That benchmark item merits manual wording/label review; the present report retains the original reference and scores unchanged.

## Diagnostics and costs

All three jobs record zero member LLM errors and zero `Event loop is closed` occurrences in their saved Slurm/vLLM logs. H1 has three vLLM tool-parser error events; H2 and H3 have none. No accepted submission in any setting is marked as using the new answer-text normalization. This run therefore provides no successful normalized-submission examples from which to measure that patch's benefit.

Trace files were checked for readable JSON, a member transcript, and agreement between operation counts and checkpoint diagnoses. This verifies the retained evidence, not that every SDK-internal event survived every possible history trim or interrupted run.

| Setting / arm | Arm wall time | Recorded output tokens |
|---|---:|---:|
| H1 official-single | 778.6 s | 115,454 |
| H1 port-single | 1,496.9 s | 156,213 |
| H2 official-single | 37.1 s | 13,354 |
| H2 port-single | 90.6 s | 8,853 |
| H3 official-single | 34.4 s | 12,389 |
| H3 port-single | 756.5 s | 48,145 |

Arm times use eight parallel question processes and exclude server startup. Tokens are harness-recorded totals, not independent billing measurements. H3's port is slower and emits more recorded output than H2 while solving fewer questions.

All actual times below are **October 20, 2026, America/Toronto (EDT, UTC−04:00)**:

| Job | Actual start | Actual end | Allocated elapsed | H100 hours |
|---|---|---|---:|---:|
| H1 / 24645791 | 02:58:36 | 03:41:51 | 43m15s | 0.7208 |
| H2 / 24645795 | 03:51:57 | 03:56:45 | 4m48s | 0.0800 |
| H3 / 24645806 | 04:00:47 | 04:16:48 | 16m01s | 0.2669 |

Total allocated GPU time: **1.0678 H100 hours (64m04s)**. Each job used one full H100, four CPUs and 32 GB RAM. No retry, additional four-arm experiment or calibration was launched during this check. The existing automation remains paused and no new email was sent.

## Artifacts and reproduction

- [Verified summary, per-question derived failure stages and SHA256 hashes](20261020-harness-v2-final-summary.json)
- [Raw final Slurm accounting](20261020-harness-v2-final-accounting.json)
- [Analysis script](20261020-harness-v2-analyze.py): uses only saved artifacts and Python's standard library.
- [H1 results, diagnosis, traces and logs](../runs/20261020-h1-think-required/)
- [H2 results, diagnosis, traces and logs](../runs/20261020-h2-nothink-required/)
- [H3 results, diagnosis, traces and logs](../runs/20261020-h3-nothink-auto/)
- [Submission manifest](20261020-harness-v2-comparison.json) and [protocol/source record](20261020-harness-v2-plan.md)
