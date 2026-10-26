# Qwen3-30B-A3B-FP8 Nibi smoke

Submitted 2026-10-26 00:51:22 America/Toronto (EDT). GPU **25021202**, CPU summary **25021203** (afterany). Initial state: PENDING / Priority; start unknown.

- Source: `0406489c534a4285c8436dd8411c78c951bb08d1`, isolated sparse source checkout `/scratch/bdong/worldseeds/code/0406489-20261026-netscale-smoke-30b`.
- Model: Qwen/Qwen3-30B-A3B-FP8; downloaded HF revision `d206ba732169f29bb77fbf80fc2c4b81d4d30782`. Seven weight shards, 32,449,487,768 bytes; tokenizer files verified. Weights stay on scratch.
- One full H100, 4 CPUs, 64G system RAM, 6-hour limit; FP8 KV cache. Thinking on, required tool calls, max output3072, 2 parallel teams.
- Two runs: peers, fixed16x4 DAG, grain1, n1/n8, seed100. Per-round state and environment event snapshots every20 rounds under `netscale-smoke/all/progress/`; retained conversations in final traces for completed runs.
- Two mocked checks passed on Nibi (27.97s): progress persistence and per-call context trimming. Real-model execution has not yet been verified.

This is a new model/settings comparison; do not treat changes from the earlier 8B smoke as the isolated effect of one code fix. Submission does not authorize a full experiment or automatic retries. No recurring monitor was recreated.
