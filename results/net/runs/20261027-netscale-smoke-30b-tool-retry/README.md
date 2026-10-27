# Qwen3 30B tool-call smoke retry

GPU job 25096393 and dependent CPU summary 25096394 finished on Nibi on 2026-10-27. Slurm reported COMPLETED, exit 0, but neither experiment solved its DAG: this is a failed smoke test, not a successful run. The GPU was allocated for 01:44:58 (6,298 seconds, 1.7494 H100-hours).

| Peers, seed 100 | Accepted nodes | Last observed progress round | Wrong submissions | Duplicate work | Final error |
|---|---:|---:|---:|---:|---|
| n=1 | 8/65 | 54 | 28 | 0 | required tool missing / parser failed after 3 attempts |
| n=8 | 16/65 | 79 | 92 | 63 | required tool missing / parser failed after 3 attempts |

Observed progress rounds are not completion times. Both runs stopped early with model errors. n=8 had five context-overflow events summed over members; no recorded trims. The Hermes server log includes JSON decoding errors. The validation events record 97 rejected responses: 95 missing required tool calls and 2 non-object or invalid arguments; these labels are model-response validation outcomes, not a proven one-to-one classification of server parser exceptions.

The experiment's `runs.jsonl` reports zero token usage due to an accounting issue; that is not actual zero usage. Individually receipted validation-event responses total 357,491 tokens for n=1 and 2,388,548 for n=8, or 2,746,039 input plus output tokens across 448 returned responses. SDK retries or failures without usage receipts are unknown; do not add these event counts to other accounting of the same calls.

Source commit: 05fc8d44b39fd4ce72bc850f92a6c796b5107faa. The two smoke cases use peers n=1 and n=8, seed 100, fixed DAG width16/depth4/grain1, with the same model, prompts, sampling parameters, CUDA12.9 and resources as job 25069829. Invalid responses are retried up to twice and can add inference calls. Twenty-four focused tests passed locally and on Nibi, including a real SDK HTTP-path simulation. A broader local check had 69 passed, 8 failed and 2 skipped, involving local website and molecule dependencies; see tests-local-broad.xml.

`nibi-raw.tar.gz` preserves the original logs, run outputs, progress, traces, response-validation events and experiment settings. Its 18 file hashes were compared individually with Nibi and are listed in `nibi-raw-files.sha256`; a basic credential-pattern scan found no matches. No recurring monitor was created.
