# Two-machine action and information-sharing diagnostic

This is an onboarding diagnostic for Qwen3-8B after the failed large-town pilots. It does not measure general planning ability or a network's advantage over equal compute.

The visible environment has two machines in two workshops: wheat → flour and flour → dough. Each uses a simple affine integer rule modulo 101; there are no branches. Three seeds (11, 22, 33) change the coefficients. Walking is free, there is no money system and there are no shared grand goals. Each player has 32 actions, a two-rule notebook and at most 40 model calls. Qwen thinking is disabled; exact requests/responses and all tool feedback remain recorded.

## Stage 1: solo

One player begins with an empty notebook and one two-machine order. The prompt gives a short numerical learning procedure: measure at 0, 1, 2, infer coefficients, remember, compute each public example, submit. The tool requires at least three actual samples per machine, rules in the notebook and predicted checks before accepting a submission. It does not infer the coefficients for the player. These workflow requirements deliberately prevent a signature-only shortcut in a world with only one valid type chain.

Run all three seeds. Continue only if at least two pass. Otherwise record that the pair stage was skipped and inspect the solo failures.

## Stage 2: split information

Two players each receive an accurate private rule for their own machine. Each independently has one order requiring both machines. They cannot probe the other player's machine; they can ask its owner for the missing rule, which the tool answers from the owner's notebook automatically. Each must obtain an explanation, compute both public examples and submit. This diagnoses whether model players can use the question/answer interface; it is not free-form conversation or a demonstration that cooperation emerged spontaneously. The initially supplied rules are logged as supplied knowledge, not as learned discoveries.

Each stage and seed is tagged in `events.jsonl`. Results, final statuses, token usage, initial private notes, actual engine events, `replay.json`, `process.html`, source snapshots and GPU/time samples are saved under `$WS_STORE/results/town_tutorial/<job-id>`. Existing pilot records are kept separately.

Run on Nibi from the repository root:

```bash
mkdir -p logs
sbatch slurm/town_tutorial.sh
```

One H100 3g.40gb MIG slice, four CPUs, 32 GB host memory, one-hour limit. The server permits at most two concurrent sequences. Full-map graphics remain for display, but only the two named workshops/machines are accessible.

## Recorded Nibi result: job 23645311

Qwen3-8B completed all three solo cases and all six player orders in the three pair cases: nine orders total. Every player ended with `completed`; there were no wrong deliveries or exhausted budgets. Each pair player made one successful `ask` call before checking both public examples and submitting. The solo players inferred both machine rules correctly from actual observations. Seed 11 redundantly called `study` after collecting three samples per machine, spending 23 actions; seeds 22 and 33 spent seven actions each.

Model startup took 341 seconds, the experiment took 99 seconds, and the Slurm job completed in 7 minutes 27 seconds. These outcomes establish success on this explicitly guided, two-machine diagnostic only. In the pair stage the initial rules were supplied, and answers were generated automatically from the teammate's notebook; this is not evidence of free-form negotiation or success in the larger town.

The [archived record](../results/town_tutorial/23645311/README.md) includes exact model payloads, tool feedback, metrics, replay, source snapshot and timing. Public hardware logs retain only model/memory/MIG configuration; the operational server log is excluded from the public archive. Original logs remain on Nibi and locally. `commit.txt` is the base revision used at execution; the captured patch, source archive and hashes identify the then-uncommitted implementation actually run.
