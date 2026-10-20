# Nibi fidelity A/B final comparison

Both jobs completed successfully, and all **400 question-arm outcomes** are present: 50 identical GSM8K questions × four arms × two settings. The saved `progress.json` outcomes, `debate.json` per-question arrays, aggregate accuracy, recorded tokens and arm wall times agree exactly.

**The port does substantially better in setting A, but fidelity is not established. Setting B has a large absolute performance deficit despite passing the original gain-only check.**

## Accuracy

| Arm | A: thinking / required / 8192 | B: no thinking / auto / 2048 |
|---|---:|---:|
| official-single | 44/50 — 88% | 45/50 — 90% |
| official-debate | 45/50 — 90% | 45/50 — 90% |
| port-single | 40/50 — 80% | 8/50 — 16% |
| port-debate | 44/50 — 88% | 9/50 — 18% |
| port-single − official-single | **−8 percentage points** | **−74 percentage points** |
| Paired bootstrap 95% interval | **[−18, 0] percentage points** | **[−86, −62] percentage points** |

The confidence intervals resample the same 50 question indices jointly for the two single-agent arms (20,000 replicates, seed 1, percentile interval). In A, one question was correct only in the port and five only in the official arm. In B, zero were correct only in the port and 37 only in the official arm. Fifty questions and one sampled run per setting limit precision and generalization; A's interval includes zero and does not demonstrate equivalence.

Debate improves accuracy by 2 points in the official A arms and 8 points in the port A arms. For B, the gains are 0 and 2 points. The original report's gain-only gate is false for A and true for B. **B's true gate is not evidence of fidelity:** similarly small gains can coexist with 90% versus 16–18% absolute accuracy.

## Recorded time and output tokens

Arm wall time is elapsed time with eight question processes, excluding server startup. It is not the sum of worker latencies. Output tokens are the counts saved by the harness, not an independent billing measurement.

| Arm | A wall time | A output tokens | B wall time | B output tokens |
|---|---:|---:|---:|---:|
| official-single | 643.7 s (10.73 min) | 103,670 | 54.8 s (0.91 min) | 14,444 |
| official-debate | 3,374.5 s (56.24 min) | 488,902 | 248.0 s (4.13 min) | 67,199 |
| port-single | 1,438.4 s (23.97 min) | 140,406 | 191.1 s (3.19 min) | 23,554 |
| port-debate | 2,187.4 s (36.46 min) | 309,201 | 736.9 s (12.28 min) | 102,512 |
| Total recorded tokens | — | **1,042,179** | — | **207,709** |

Relative to official-single, port-single took 2.23× wall time and 1.35× recorded output tokens in A; 3.49× wall time and 1.63× tokens in B.

## Actual job timing — America/Toronto (EDT, UTC−04:00)

| Setting / job | Actual start | Actual end | Elapsed / allocated H100 hours | Node / status |
|---|---|---|---|---|
| A / 24309180 | Oct 19, 22:26:41 | Oct 20, 00:42:20 | 2h15m39s / **2.2608 H100 h** | g11 / COMPLETED, exit 0:0 |
| B / 24309183 | Oct 20, 00:50:02 | Oct 20, 01:16:14 | 26m12s / **0.4367 H100 h** | g17 / COMPLETED, exit 0:0 |

Total allocated GPU time: **2.6975 H100 hours**. Each job used one full H100, four CPUs and 32 GB RAM; no retry was submitted. Job elapsed includes server initialization and other overhead. A took 5.18× B's allocated wall time. These are actual accounting times, replacing earlier provisional queue estimates. After terminal jobs aged out of `scontrol`, it returned “Invalid job id”; `sacct` retains both completed records.

## Interpretation and diagnostics

- The official plain-chat baseline stays at 88–90%, while the tool-based port changes from 80/88% to 16/18%. This points toward the port/harness interaction as a priority for investigation; it does not establish a specific failure mechanism.
- A and B change **three settings together**: thinking, tool choice and maximum output tokens. This experiment cannot isolate the causal effect of thinking alone. Hardware type and question set match, but jobs ran sequentially on different physical nodes.
- The official arms score the parsed final text (majority vote for debate). The port arms score `NetworkEnv.solved`, which requires a successful environment submission. Thus these measurements include protocol, tool use and submission behavior, not just mathematical answer quality. With `auto`, returning text without submitting is a plausible mechanism; the saved artifacts do not prove how often this occurred.
- The Slurm logs contain 61 (A) and 72 (B) occurrences of `RuntimeError: Event loop is closed` in asynchronous HTTP-client cleanup. The vLLM logs contain three (A) and one (B) tool-parser error events. All 400 records still completed. These warnings must not be hidden, but their counts do not identify the incorrect questions or prove their causes. The saved vLLM completion access lines contain no non-200 HTTP status.
- `progress.json` stores correctness, duration and token totals; it does **not** retain full generated answers, tool arguments, environment events or member error reports. Per-question root-cause attribution and unreported usage on failed requests cannot be reconstructed reliably. Recorded port token totals may omit usage from requests that failed before accounting.

No runtime code, resource request or experiment protocol was changed while collecting these results. No smoke, calibration, pilot or replacement run was launched.

## Reproducible artifacts

- [Machine-readable verified summary and raw-file SHA256 hashes](20261017-fidelity-final-summary.json)
- [Raw Slurm accounting and job-query results](20261017-fidelity-final-accounting.json)
- [Manifest and exact settings](20261017-fidelity-comparison.json)
- [Analysis script](20261017-fidelity-analyze.py) — run from any directory with `python3 /path/to/20261017-fidelity-analyze.py`; uses only saved artifacts and the standard library.
- [A report](../runs/20261017-fid-think/fidelity/debate.json), [A checkpoint](../runs/20261017-fid-think/fidelity/progress.json), [A raw logs](../runs/20261017-fid-think/logs/), [A final state](../runs/20261017-fid-think/final-status.json)
- [B report](../runs/20261017-fid-nothink/fidelity/debate.json), [B checkpoint](../runs/20261017-fid-nothink/fidelity/progress.json), [B raw logs](../runs/20261017-fid-nothink/logs/), [B final state](../runs/20261017-fid-nothink/final-status.json)

Run source: `b8813d2562d557874cf6d6a624a0656b99d263d8`. The downloaded dataset/author-code cache is excluded from the public archive; the exact selected question set is retained in each checkpoint. The original `debate.json` reports and raw logs are preserved without rewriting them.
