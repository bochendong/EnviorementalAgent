# Test set and published agent designs

This is how agent designs are compared on the network environment (`worldseeds/net`):
- which published designs are implemented;
- what they run on;
- how compute is matched;
- what is measured.

The code is in `netagents/designs.py`, `netagents/testset.py` and `netagents/evaluate.py`.

```bash
python -m netagents.evaluate --suite dev --designs all                    # any OpenAI-compatible server
SUITE=test sbatch slurm/net_eval.sh                                       # on Nibi, Qwen on vLLM
```

## Running every experiment on Nibi

`slurm/run_all.sh` submits the paper's experiments from a login node, one GPU job per experiment and design, and lays out one directory per run:

```bash
bash slurm/setup_nibi.sh                                   # once: venvs and model weights
ACCOUNT=def-yourpi STAGE=smoke bash slurm/run_all.sh       # first: ~10 GPU minutes, every request kind and two tiny runs
ACCOUNT=def-yourpi STAGE=check bash slurm/run_all.sh       # then: fidelity and calibration (see below)
ACCOUNT=def-yourpi DRY=1 STAGE=all bash slurm/run_all.sh   # see the jobs; nothing is submitted or written
ACCOUNT=def-yourpi bash slurm/run_all.sh                   # stage 1: baselines, fidelity, compatibility track
ACCOUNT=def-yourpi RUN=<run> STAGE=2 bash slurm/run_all.sh # stage 2: the network track, into the same run
python -m netagents.report $SCRATCH/worldseeds/results/net/runs/<run>   # rebuild the index at any time
```

`STAGE=smoke` (`netagents/smoke.py`) comes first and costs a few GPU minutes:
- does the server start?
- does it answer every kind of request the designs make (plain chat, tools required and auto, thinking off, JSON, a 40k-token prompt)?
- do one `sas` and one `centralized` run finish without model errors?

It prints a table and keeps every error in full in `smoke/smoke.json`.

Runs of a job go eight at a time (`--parallel`, `NETAGENTS_PARALLEL`), each in its own process with its own model client; the server batches their requests. A step whose thinking uses up all 8192 output tokens is redone once without thinking, and counted (`overflows`). These fixes come from the pilot (`results/net/runs/20261015-pilot`):
- Triton's cache on the shared file system failed with a stale file handle;
- thinking ran out of the old 4096-token limit;
- one model client was reused across runs ("Event loop is closed");
- runs went one at a time. Evaluation jobs also stop by themselves after three runs in a row with model errors (`--stop-after`), printing the errors, rather than spending a GPU day on a broken setup.

`STAGE=check` runs next, and its two answers decide whether the real runs are worth their GPU hours:
- **fidelity**: is our harness as good as plain chat? The port's single agent should be close to the official single agent on GSM8K.
  - First A/B (`results/net/runs/20261017-fid-think`, `-fid-nothink`, 50 questions each):
    - thinking on with tool calls required: official single 88%, port single 80%;
    - thinking off with tool choice automatic: official 90%, port 16%.
  - The two runs changed thinking, tool choice and the output limit together, so the gap cannot be put on any one of them.
  - Protocol 2 (`fidelity.PROTOCOL_VERSION`) changes the harness in three ways:
    - the briefing lists the tasks one can work on, so a first call is no longer spent finding the question;
    - a math answer is read as the official scorer reads one (a `\boxed{}` value; "$1,200." as 1200; the one number in "18 dollars"), and each submission records how it was read;
    - every port question keeps its whole conversation (`traces/<arm>/q<i>.jsonl.gz`) and an outcome: solved, never submitted, submitted something unreadable, or submitted a wrong value (`diagnosis-<arm>.json`).
  - `ARMS="official-single port-single"` checks the harness alone at a fraction of the cost.
  - Single-variable runs on protocol 2 (`results/net/runs/20261020-h*`, 50 questions, official vs port single):

    | run | official | port | port failures |
    |---|---|---|---|
    | h1: thinking on, tools required | 88% | 88% | 6 wrong values; 58 submissions first blocked by a store key |
    | h2: thinking off, required | 92% | 18% | 26 questions stopped at a store key that did not exist, 11 never submitted |
    | h3: thinking off, auto | 90% | 2% | 46 never submitted; in 45, Actions and Observations were written as text and no tool was called |

  - Protocol 3 fixes the two harness faults these runs exposed:
    - `submit` had an optional `key` field (submit from the store). The model filled it with "Q", "answer" or "a0"; a single agent has no store at all. Now the field is called `store_key`, it is offered only where there is a store, and a value given as `artifact` wins over it.
    - One sentence was added to ReAct's instruction: Actions are real tool calls, never text.
  - h1's gap of 0 has a 95% interval of −10 to +10 points at 50 questions: within the threshold, but not shown equivalent. That needs more questions.
- **calibration**: four designs (`sas`, `reflexion`, `centralized`, `debate`) on the easy and medium presets and the compatibility cases, dev seeds. The presets were tuned on scripted teams. A case where these designs complete on average under 20% or over 80% of the tasks is marked too hard or too easy in `calibration/summary.md`: designs cannot be told apart there, and the preset should be adjusted for this model before the test runs.

Stage 1 is 22 jobs (baselines on CPU, the GSM8K fidelity check, 10 designs on `compat`, 8 on `compat` through the network, a summary job per experiment); stage 2 is 66. `FRAMEWORKS=1` adds AutoGen, Magentic-One and CAMEL to `compat-framework` and `test`; `SEEDS=2` makes a quick pass; `MODEL_ID` picks the model. Running the script again with the same `RUN` resumes: evaluation jobs skip runs already recorded, and finished baselines and fidelity checks are skipped.

```
$SCRATCH/worldseeds/results/net/runs/<date>-<model>/
  README.md                 index: every experiment, its jobs, runs per design and main table
  plan.tsv                  experiment, design, Slurm job id, command
  commit.txt, env.txt       the commit (and local changes) and the settings of each submission
  logs/                     Slurm and vLLM logs
  baselines/                baselines.md, baselines.json (scripted teams)
  fidelity/debate.json      official vs ported debate on GSM8K, with the paper's numbers
  compat-framework/         compatibility track, messages through the framework
    <design>/runs.jsonl     one job per design
    summary.md              every design (written when the experiment's last job ends)
    hypotheses.json         each published finding: reproduced, contradicted or inconclusive
  compat-network/           the same cases, messages through the environment's network
  test/ hard/ heldout/ scaling/ topology/ robustness/     the network track, same layout
```

## The main experiment (`--suite focus`)

The paper's question: once tools and information are split across roles, does a multi-agent team still beat a single agent with the same compute? Kim et al. (2026) compared architectures with identical agents. The environment can split the tools, which they could not. It is a 2×2 on math:

| | every agent has every tool | tools split: 2 explorers (numbers), 1 algebraist (symbols) |
|---|---|---|
| decomposable: 4 independent recurrences | `focus/math-decomposable-shared` (Kim et al.'s setting) | `focus/math-decomposable-split` |
| sequential: the same 4 in one chain | `focus/math-sequential-shared` (Kim et al.'s setting) | `focus/math-sequential-split` |

- Designs: `sas`, `centralized` and `decentralized`, ported from Kim et al.'s code.
- Test seeds 100–109. The designs' messages pass through the framework, so only who holds which tools changes between the columns.
- Same tasks, budgets and team size in all four cells. The single agent always holds every tool.
- The scripted reference team solves all four cells on all 10 seeds.
- `STAGE=focus bash slurm/run_all.sh` runs it as one job, so the server starts once; `SEEDS=5` gives a first pass, and the same command later resumes it to 10.

## When does splitting the work pay? (`--suite load`)

HiddenBench (Li, Naito & Shirado, ICML 2026) shows that teams of LLM agents holding distributed facts do far worse than one agent with every fact. There, the single agent always knows everything, so it is an upper bound by construction. The load suite asks the question that this leaves open: as the world to master grows, does a team that splits it overtake one agent that must master all of it, at the same compute?

- **The work stays fixed**: 6 projects, each a chain of 3 functions.
- **Only the world grows**:

  | modules | functions | chains per project's types, about |
  |---|---|---|
  | 4 | 16 | 5 |
  | 8 | 32 | 40 |
  | 12 | 48 | 100 |

- **Teams of four**:
  - `shared`: everyone can study anything;
  - `split`: four owners, each the only one who can study its share of the modules.
- **The single agent** can study everything. It runs once per size, because its runs are the same for both tool settings.
- Each run records its load (`functions`, `candidates_per_project`, `distinct_functions_needed`).
- The scripted team and the scripted single agent solve every size.
- `python -m netagents.load_report <dir>` gives each team's paired difference from the single agent at each size, with its 95% interval. A crossing is where that interval moves from below zero to above it.

```bash
ACCOUNT=... STAGE=load SEEDS=3 LOAD_DESIGNS="sas centralized" bash slurm/run_all.sh   # the pilot: 3 sizes x 3 seeds
```

## Agent-network scaling (`--suite netscale-pilot`, `--suite netscale`)

How does a team of LLM agents scale on a problem that is larger than one agent, compared with what is possible? Mieczkowski et al. (2026, arXiv 2603.12229) measured Amdahl's law with 1-5 agents on 20 coding subtasks; this suite takes it to 32 agents, to problems that grow with the team, and to a lower bound and a reference curve for every size.

- **The problems** (the DAG provider, `worldseeds/net/providers/dag.py`; presets `dag/fixed` and `dag/scaled`):
  - `depth` layers of `width` tasks and a final task;
  - every task has a hidden function of its own (a keyed hash), learned only through the `apply` operation;
  - a task starts from its parents' answers (the sum mod 1000) and applies its function `grain` times in a row;
  - the answer is a bare whole number, checked exactly.

  No reasoning shortcuts a task. One agent needs at least W = tasks x (grain + 1) actions; a team of N needs at least max(W / N, D) rounds, with D = (depth + 1) x (grain + 1).
  - `fixed`: 16 x 4 for every team size (Amdahl).
  - `scaled`: 4 layers as wide as the team (Gustafson).
  - `grain` 1 or 4: how much computation a task holds against what sharing its answer costs.
- **Why not recurrences.** The first version used the math provider's recurrences (`dag` option). In the 2026-10-22 pilot (`results/net/runs/20261022-codex-netscale-pilot-01`), a strong model handed in closed forms such as `Mod((5**31 - 1)/4, 1009)` without any tool. It also nested parents' expressions into their children's, so the single agent beat the "reference" (T = 82 against 129) and neither work nor span held.
- **The team**: `peers`, N identical agents working at once, an equal share of the calls, and nothing prescribed about how to share the work. With N = 1 it is a single agent with the same briefing.
- **Time**: lockstep rounds (`netagents/lockstep.py`). Every round, every agent still working takes one action, so a team is as slow as it really is in parallel.
- **The lower bound and the reference** (`python -m netagents.scaling`):
  - the lower bound counts sharing as free;
  - the reference is the fastest of three scripted teams:
    - a message per answer plus one inbox read;
    - the store, with one write and one read per answer;
    - batch (bulk synchronous): each layer's tasks are dealt out in turn, and each agent sends all its answers of a layer in one message.

    Batch was added after the grain-1 Codex pilot (`results/net/runs/20261022-codex-dag-pilot-02`), where two agents batching their answers beat the per-answer team. Each task's function is keyed so that its chain repeats no value, so no apply can be skipped by reusing a value already seen.

  Seed 0, fixed family:

  | agents | 1 | 2 | 4 | 8 | 16 | 32 |
  |---|---|---|---|---|---|---|
  | grain 1: lower bound | 130 | 65 | 33 | 17 | 10 | 10 |
  | grain 1: reference | 130 | 74 | 42 | 26 | 18 | 16 |
  | grain 4: lower bound | 325 | 163 | 82 | 41 | 25 | 25 |
  | grain 4: reference | 325 | 173 | 93 | 53 | 33 | 31 |

  With 8 agents, the reference reaches 65% of the bound's speed-up at grain 1 and 77% at grain 4: coarser tasks pay for their sharing.
- **Calls**: three times the actions a team needs (at least 40 per agent); budgets are not the limit, time is.
- **Measured** (`summary.md`, "Network scale"; or `python -m netagents.netscale <dir>`):
  - T, the team's rounds;
  - b = T_lb / T, efficiency against the bound;
  - a = T_ref / T, closeness to the reference;
  - eta = a(N) / a(1), coordination efficiency;
  - the speed-up and a Universal Scalability Law fit;
  - where the actions went;
  - each seed's T, and how each run's team passed answers on (store, broadcast or batch).
- **The pilot**: fixed, grain 1 and 4, N = 1, 2, 4, 8, 3 seeds (24 runs).
- **On Nibi** (an open model served by vLLM), every netscale stage runs 2 teams at once, with replies of at most 3072 tokens. Each member's history is trimmed before every model call, not only at the start of a turn. The first Nibi pilot (2026-10-21) ran on the old recurrence DAG with 8 runs at once and 8192-token replies; its requests timed out and its histories outgrew the window (`results/net/submissions/20261021-netscale-pilot-final-report.md`).
- **The smoke stage** runs for up to 6 hours with an FP8 KV cache. Each run's state is saved every round, and its events every 20 rounds, under `progress/`. In the 2-hour smoke of 2026-10-25, the single agent was still working when the job ended and left no record. Its team of 8 Qwen3-8B agents duplicated most of their work: 262 of 289 refused submissions were tasks already done. They spent the whole call budget and finished 53 of 65 tasks.
- **On one H100**, use `MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 GPU_RESOURCE=h100:1`. Download the weights on a login node first.

```bash
ACCOUNT=... STAGE=netscale-smoke bash slurm/run_all.sh     # first: 1 and 8 agents, one seed, under 2 GPU hours
ACCOUNT=... STAGE=netscale-pilot bash slurm/run_all.sh     # the pilot, one packed job
ACCOUNT=... STAGE=netscale bash slurm/run_all.sh           # 1-32 agents, fixed and scaled, both grains, 5 seeds
python -m netagents.codex_netscale --out ...               # the same suite with Codex as the model (docs/codex-netscale.md)
```

## Two tracks

The published designs assume settings this environment deliberately goes beyond: identical agents, answer-checked tasks, no deadline, and messages handed over by the framework for free. A design that fails here could fail because the design is weak, or because it was never meant for these settings. So every design runs on two tracks:

- **Compatibility track** (`--suite compat`): the published settings. The presets `compat/*` give every agent every tool, set no deadline, and check answers. The designs' messages pass through their framework, as in the authors' code. On this track we first reproduce published findings; only a design whose finding reproduces is carried over to the network track.
- **Network track** (every other suite): what this environment adds. Tools are split across roles, the agents share one world, and the network has a shape, latency, outages and costs. The designs' messages travel through the environment's network: a send is charged to the sender, reading it to the receiver, and a message to a non-neighbour is lost. Speakers that are not agents of the environment (Kim et al.'s orchestrator, LbMAS's control unit) speak from the first agent's seat.

The switch is one object, `Channel` in `netagents/designs.py`, used by every multi-agent port, so the prompts and protocol are the same on both tracks. `--route framework|network` overrides the track, for example to run the compatibility cases through the network and isolate the cost of real communication. AutoGen and CAMEL pass their messages themselves and always use their own route; runs record which route was used (`route`, and the channel's delivered and lost counts).

**Published findings checked on the compatibility track** (`testset.HYPOTHESES`):

| finding | source | cases | check |
|---|---|---|---|
| every multi-agent architecture beats the single agent on decomposable tasks | [Kim et al. 2026](https://arxiv.org/abs/2512.08296), Sec. 4 (Finance-Agent, +57% to +81%) | `compat/math-decomposable`: 4 independent recurrences and a final sum | `independent`, `centralized`, `decentralized`, `hybrid` − `sas` > 0 |
| every multi-agent architecture is worse than the single agent on sequential tasks | Kim et al. 2026, Sec. 4 (PlanCraft, −39% to −70%) | `compat/math-sequential`: the same 4 recurrences in one chain, each starting from the previous answer | the same differences < 0 |
| debate beats a single agent on arithmetic word problems | [Du et al. 2024](https://arxiv.org/abs/2305.14325) | GSM8K itself | `netagents/fidelity.py`, against the authors' own code |

The evaluation pairs runs by seed, computes the mean difference in task completion with a 95% bootstrap interval, and labels each finding *reproduced* (the interval lies on the published side of zero), *contradicted* (on the other side) or *inconclusive*. The table is added to `summary.md`, and `hypotheses.json` holds the numbers.

## Agent designs and how close they are to their sources

Each design is labelled by how it was built:
- **port**: from the authors' released code. Their prompts are quoted under the code's licence, and their settings are used. It is adapted to tool use where the original answered in text.
- **reimplementation**: from the paper's description, because no code was released or found. It must be checked against the paper before publication.
- **framework**: the authors' own framework, used as released, driving our tools through an adapter (`netagents/frameworks/`). It runs in its own Python environment against the environment served over HTTP, with the same model server and the same pool of tool calls.

The last column lists every known difference from the source; it is meant to go into the paper as is. The table is generated from `netagents/designs.py` (`cards_markdown()`).

| design | source | fidelity | runs on | differs from the source |
|---|---|---|---|---|
| `react` ReAct | Yao et al., ReAct: Synergizing Reasoning and Acting in Language Models, ICLR 2023; code: ysymyth/ReAct, noahshinn/reflexion (MIT) | port | solo | native tool calls instead of Thought/Action text lines, with one sentence added to the instruction: Actions are real tool calls, never text; no few-shot examples (theirs are task-specific); the step limit is the call budget (the paper: 7 steps on HotpotQA, 5 on FEVER, 50 on ALFWorld), and the agent is prompted to continue when it stops with tasks left; no back-off to CoT-SC |
| `reflexion` Reflexion | Shinn et al., Reflexion: Language Agents with Verbal Reinforcement Learning, NeurIPS 2023; code: noahshinn/reflexion (MIT) | port | solo | trials share one episode and its budget instead of re-running the same task; a trial fails on a wrong submission or when its step quota runs out; the environment's verdict is the evaluator, not the paper's ALFWorld heuristic (the same action and observation more than 3 times, or more than 30 actions); no few-shot reflection examples |
| `debate` Multiagent debate | Du et al., Improving Factuality and Reasoning in Language Models through Multiagent Debate, ICML 2024; code: composable-models/llm_multiagent_debate (no licence: prompt paraphrased) | port | team | agents use tools between rounds; a solution is what an agent states at the end of a round; solutions pass through the design's channel (the framework, or the environment's network); agents submit themselves instead of a majority vote over final answers; team size is the preset's, not 3 |
| `moa` Mixture-of-Agents | Wang et al., Mixture-of-Agents Enhances Large Language Model Capabilities, ICLR 2025 (arXiv 2406.04692); code: togethercomputer/MoA (Apache-2.0) | port | team | one model in every position: the paper's single-proposer setting, not its default of six different open-source models; two layers (MoA-Lite) by default, not three; proposers use tools; their responses pass through the design's channel; the aggregate prompt is a user message, not a system message; the aggregator is one of the team, with its role's tools |
| `sas` Single-agent system (Kim et al.) | Kim et al., Towards a Science of Scaling Agent Systems, arXiv 2512.08296 v3 (2026); code: ybkim95/agent-scaling (MIT) | port | solo | iterations are tool calls; the single agent gets the team's whole pool of calls (the paper gives it proportionally more iterations) |
| `independent` Independent (Kim et al.) | Kim et al. 2026; code: ybkim95/agent-scaling (MIT) | port | nonet | the agents act in one shared environment, not in a copy each; the synthesis-only aggregate is recorded but not submitted: our submissions need a task and an artifact, so each agent submits its own; team size is the preset's, not 3 |
| `centralized` Centralized (Kim et al.) | Kim et al. 2026; code: ybkim95/agent-scaling (MIT) | port | team | the orchestrator reads the task list once through the first worker (one action); the final auto-submit is a turn of the first worker given the synthesis; orchestrator-worker messages pass through the design's channel: the framework, as in the authors' code, or the environment's network; team size is the preset's, not 3 |
| `decentralized` Decentralized (Kim et al.) | Kim et al. 2026; code: ybkim95/agent-scaling (MIT) | port | team | the consensus vote over final answers is recorded; agents submit their own results; peer answers pass through the design's channel (the framework, or the network); team size is the preset's, not 3 |
| `hybrid` Hybrid (Kim et al.) | Kim et al. 2026; code: ybkim95/agent-scaling (MIT) | port | team | as centralized, plus the authors' final peer round; team size is the preset's, not 3 |
| `blackboard` LbMAS blackboard system | Han & Zhang, Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture, arXiv 2507.01701v1 (2025); prompts from the paper (code not released) | port | team | the team's members (with the environment's tools) join as experts of their roles, besides 1-3 generated experts; one model for every agent instead of one drawn per agent from two models; no private spaces (debate, self-reflection); the decider's answer is handed to the team members to submit; solution by the decider only (not the similarity vote) |
| `autogen-roundrobin` AutoGen round-robin group chat | Wu et al., AutoGen, COLM 2024 (arXiv 2308.08155); autogen-agentchat 0.7.5 (MIT) | framework | team | members talk in the framework's shared conversation, outside the environment's network (not charged, no topology); a fixed speaking order: a team of the AutoGen library, not one evaluated in the paper |
| `autogen-selector` AutoGen group chat with a model-selected speaker | Wu et al., AutoGen, COLM 2024 (arXiv 2308.08155): the dynamic group chat of Sec. 3 (A5), where a manager selects the next speaker and broadcasts its message; autogen-agentchat 0.7.5 (MIT) | framework | team | members talk in the framework's shared conversation, outside the environment's network (not charged, no topology); SelectorGroupChat of AutoGen 0.7 stands for the paper's GroupChatManager (AutoGen 0.2) |
| `magentic-one` Magentic-One orchestrator | Fourney et al., Magentic-One, arXiv 2411.04468 (2024); autogen-agentchat 0.7.5 (MIT) | framework | team | members talk in the framework's shared conversation, outside the environment's network (not charged, no topology); the orchestrator directs our role agents instead of Magentic-One's web, file and code agents; one model for the orchestrator and the agents (the paper: GPT-4o, or o1-preview for the outer loop); no time limit; the turn limit is the call budget |
| `camel-roleplay` CAMEL role playing | Li et al., CAMEL: Communicative Agents for "Mind" Exploration of Large Language Model Society, NeurIPS 2023; camel-ai 0.2.90 (Apache-2.0) | framework | solo | the assistant is the solo agent with every tool and the team's budget; the user agent has no tools; no task-specifier agent: the task given is already precise; the paper's termination conditions are kept (40 messages, 3 rounds without an instruction, the end-of-task token) except role reversal, which is not detected |

Every design uses the same model and the same tools, generated from the environment's op specs.

How the ported frameworks pass messages:
- In the Kim et al. designs and LbMAS, agents talk through the framework, as in the authors' code. The orchestrator's guidance, the peers' answers and the blackboard are passed by the framework. The workers hold the task's tools and the submit tool, but no network operations.
- In the debate and Mixture-of-Agents ports, solutions travel as messages through the environment's network.

Sources of the ports:
- ReAct: `ysymyth/ReAct`, MIT.
- Reflexion: `noahshinn/reflexion`, MIT. The instruction, reflection prompt and header are taken from `hotpotqa_runs/prompts.py`.
- Debate: `composable-models/llm_multiagent_debate`. The repository has no licence, so the prompt is paraphrased. `gsm/gen_gsm.py` uses 3 agents and 2 rounds.
- Mixture-of-Agents: `togethercomputer/MoA`, Apache-2.0. The aggregate-and-synthesize prompt is quoted from `utils.py`. The default is one round, i.e. two layers.
- Kim et al.: `ybkim95/agent-scaling`, MIT.
  - Prompts come from their YAML templates (`netagents/prompts/kim2025.py`).
  - Control flow comes from their `multiagent_*.py` and `mas_lead_agent.py`.
  - Settings follow the paper's Appendix E.2: single agent up to 10 iterations; independent with 3 agents, synthesis only; centralized with an orchestrator, at most 5 rounds and 3 iterations per agent per round; decentralized with 3 debate rounds of 3 iterations; hybrid as centralized plus a peer round.
  - Their repository's YAML configs use larger limits (25 iterations, 10 rounds). We follow the paper and note the difference.
- LbMAS (Han & Zhang): the code has not been released. The prompts are transcribed from the paper's Figures 4–6 (`netagents/prompts/han2025.py`), and the cycle follows its Algorithm 1 with K = 4 rounds.

Tool calls are matched across designs, but tokens are not, and cannot be by construction. An orchestrator, a control unit and the predefined blackboard agents only talk: they cost tokens but no tool calls. This coordination overhead is what Kim et al. measure, and every run records it.

### Settings checked against the papers

| design | the paper's setting | here |
|---|---|---|
| ReAct (Yao et al., ICLR 2023) | PaLM-540B, few-shot, greedy decoding; at most 7 steps (HotpotQA), 5 (FEVER), 50 (ALFWorld); back-off to CoT-SC with 21 samples at temperature 0.7 | zero-shot with tools; the step limit is the call budget; no CoT-SC back-off |
| Reflexion (Shinn et al., NeurIPS 2023) | memory bounded to Ω = 1–3 reflections (3 on HotPotQA and ALFWorld, 1 for code); reflect after a failed trial (exact-match grading) or, on ALFWorld, after the same action and observation more than 3 times or more than 30 actions; 2-shot reflections | Ω = 3; reflect after a rejected submission or an unfinished trial; zero-shot reflections |
| Multiagent debate (Du et al., ICML 2024) | 3 agents, 2 rounds (Table 1), zero-shot, gpt-3.5-turbo-0301, answer from a box, 100 GSM8K problems: single 77.0, debate 85.0 | 3 agents and 2 rounds on the compatibility track and in the fidelity check, which reports the paper's numbers next to ours |
| AutoGen (Wu et al., COLM 2024) | GroupChatManager: select a speaker (role-play prompt), ask it to respond, broadcast (Sec. 3, A5) | `autogen-selector` (SelectorGroupChat, the same protocol in AutoGen 0.7); `autogen-roundrobin` is a library team the paper does not evaluate |
| Mixture-of-Agents (Wang et al., ICLR 2025) | 3 layers of 6 different open-source models, Qwen1.5-110B-Chat aggregating (MoA); 2 layers with Qwen1.5-72B-Chat aggregating (MoA-Lite); the Aggregate-and-Synthesize prompt (Table 1); the original prompt added to every layer's input; single-proposer variant: one model sampled n times at 0.7 | 2 layers (MoA-Lite, the repository's default; `rounds=2` gives 3); one model, i.e. the single-proposer variant; the Table 1 prompt, quoted |
| Magentic-One (Fourney et al., 2024) | an orchestrator with an outer loop (task ledger: facts, guesses, plan; agents reset at each re-plan) and an inner loop (progress ledger: done? looping? progress? next speaker, instruction); re-plan when the stall counter exceeds 2; GPT-4o for every agent, or o1-preview for the outer loop | AutoGen's MagenticOneGroupChat with `max_stalls=3` (the same threshold); one model throughout; our role agents instead of the web, file and code agents |
| CAMEL (Li et al., NeurIPS 2023) | inception prompts; task specifier; the chat ends at 40 messages, after 3 rounds without an instruction, on the end-of-task token, on role reversal or at the token limit | the framework's own prompts; no task specifier; every termination condition but role reversal |

Every design has now been checked against its paper.

**Model settings, shared by every design and framework** (`netagents/llm.py`): Qwen3's thinking mode with its recommended sampling (temperature 0.6, top_p 0.95, top_k 20) and up to 4096 output tokens; vLLM's reasoning parser keeps the reasoning out of answers and histories. The papers used greedy decoding (ReAct), 0.7 (Reflexion's retries) or the API default (debate, CAMEL).
- The first full run (`20261013-qwen3-8b-ea182dd`) had thinking off while every step had to be a tool call, so agents could not reason at all. The same model scored 90% on GSM8K in plain chat and 51% through our harness.
- Fixed with it:
  - each agent's history is trimmed to 60% of the window before a turn, oldest steps first;
  - the window is 64k (YaRN);
  - AutoGen models see the task and the last 30 messages (most AutoGen runs had overflowed the context);
  - Magentic-One's ledgers use structured JSON output (every Magentic-One run had failed to parse them).
- Every run now records its tool-call counts, errors, context trims and peak context, and keeps a full trace for the first seed of each case.

To do before publication: rerun the fidelity check with the fixed harness (`STAGE=fidelity`) and, once the port's single agent is close to plain chat, rerun everything.

MetaGPT ([Hong et al., ICLR 2024](https://arxiv.org/abs/2308.00352)) is cited as related work, not run: its released versions pin a dependency that has been removed from PyPI (`lancedb==0.4.0`), and its fixed software-company roles (product manager, architect, engineer) are close to what the website provider's roles already test.

## Matched compute

Several papers warn that a multi-agent "advantage" is often only extra compute:
- [Tran & Kiela 2026](https://arxiv.org/abs/2604.02460): single agents match or beat multi-agent systems on multi-hop reasoning at equal thinking-token budgets.
- [Kim et al. 2025](https://arxiv.org/abs/2512.08296): standardised tools, prompts and compute across architectures; coordination helps parallelisable tasks and hurts sequential ones.
- [MAST](https://arxiv.org/abs/2503.13657): multi-agent gains over single agents and best-of-N are often minimal.

So, in every run:
- **LLM tool calls**: every design on a case gets the same total, `CALLS_PER_MEMBER` (40) × team size. One pool is shared by all members; no design exceeds it.
- **Environment actions**: equal totals. Single-agent designs run on the `solo` variant (one agent, the whole team's budget); `independent` on `nonet`; the rest on `team`. Medium and hard presets have a deadline equal to one member's budget, so the single agent has the same compute but not more time.
- **Tokens**: input and output tokens are recorded per member. Reflections and the blackboard's control unit use text-only calls; their tokens are counted, but they take no tool calls.

## Suites

Seeds 0–2 are for development. Seeds 100–109 are test seeds and must not be used to tune a design.

| suite | cases | seeds | what it asks | related work |
|---|---|---|---|---|
| `dev` | codeworld, math, website and molecule at medium | 0–2 | development | |
| `test` | the same four | 100–109 | the main table | |
| `hard` | the four at hard (owners, drift, sparse and slow networks, outages, costly mistakes) | 100–109 | | |
| `heldout` | two math problem sets, a to-do API, a kinase-like target profile (`tasks/heldout/`) | 3 repeats, or 5 verified seeds | does the design carry over to tasks no script was written for? | |
| `scaling` | CodeWorld with 2, 4, 8, 16 developers | 100–104 | does the design hold up as the team grows? | [AgentsNet](https://arxiv.org/abs/2507.08616) (ICML 2025, up to 100 agents); MacNet, [Qian et al., ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/66a026c0d17040889b50f0dfa650e5e0-Abstract-Conference.html) |
| `topology` | math with full, chain, star, tree, ring, random networks | 100–104 | how much does the shape of the network matter? | [MultiAgentBench](https://arxiv.org/abs/2503.01935) (ACL 2025: star, chain, tree, graph); AgentsNet |
| `robustness` | CodeWorld with drifting laws, a client who changes their mind, a network with outages and latency | 100–104 | what breaks first? | [MAST](https://arxiv.org/abs/2503.13657) (NeurIPS 2025 D&B) |
| `org` | math and CodeWorld at medium with 0, 1 or 2 levels of managers | 100–104 | does a deeper hierarchy help at equal compute? | El Agente Q (Zou et al. 2025) |
| `faults` | the same with tool results that are silently wrong (15%) or fail loudly (15%) | 100–104 | who checks, and is it worth it? | El Agente Q; MAST (task verification) |
| `report` | a final report with every answer, scored per field; math also with the provenance rule | 100–104 | are results lost before the end? | El Agente Q (missing report items) |
| `guidance` | math easy and medium, CodeWorld medium, with and without procedural hints | 100–104 | how much do the hints matter? | El Agente Q (two levels per exercise) |
| `memory` | math and CodeWorld at medium, ten episodes in a row with a memory that carries over | 100–109 | do agents write down and reuse procedures? | |
| `compat` | decomposable math, sequential math, CodeWorld with 6 independent projects; identical agents, no deadline, messages through the framework | 100–109 | do the published findings reproduce here? | Kim et al. 2026 |

The tasks themselves follow established practice:
- **Molecule tasks** cap the number of oracle calls through the assay cost, following the sample-efficiency argument of [PMO (Gao et al., NeurIPS 2022 D&B)](https://arxiv.org/abs/2206.12411).
- **Website tasks** are scored by hidden acceptance tests run in a sandbox, as code agents are scored by tests.
- **Math tasks** are scored by exact symbolic answers.

## What is measured (per run)

- **Outcome**:
  - `solved`: every final task done;
  - `completion`: the share of tasks done;
  - `actions` and `rounds` in the environment.
- **Cost**: LLM tool calls, LLM requests, input and output tokens.
- **Communication**: messages, board posts, store writes.
- **Failure signals**, grouped as in MAST's three categories:
  - `duplicate_work`: the same costly operation with the same arguments by more than one agent (system design: step repetition);
  - `unread_messages`: messages delivered but never read (inter-agent misalignment);
  - `wrong_submissions`: rejected submissions (task verification);
  - `stopped_early`: members who stopped with budget left while the problem was unsolved;
  - `unsupported`: submissions whose value appears nowhere the team computed or passed on (a guess or an assumption);
  - `unseen`: submissions of a value only a teammate had computed and never passed on;
  - `used_faulty`: submissions taken from a silently wrong result.

- **Route**: how the design's messages travelled, and how many were delivered or lost.

`summary.md` gives one table per suite. The rows are designs and the columns are cases. Each cell shows the share of seeds solved, with the share of tasks done in brackets. Mean tokens and failure signals are added at the end of each row.

---

# 测试集与已发表的智能体设计（中文）

这份文档说明在网络环境上比较智能体设计的方法：
- 实现了哪些已发表的设计；
- 在哪些设置上跑；
- 怎么对齐算力；
- 量哪些指标。

代码在 `netagents/designs.py`、`netagents/testset.py`、`netagents/evaluate.py`。

## 在 Nibi 上跑全部实验

在登录节点上用 `slurm/run_all.sh` 提交，每个实验的每个设计一个 GPU 作业，结果全部写进一个运行目录：

```bash
bash slurm/setup_nibi.sh                                   # 只需一次：环境和模型权重
ACCOUNT=def-yourpi STAGE=smoke bash slurm/run_all.sh       # 最先跑：约 10 分钟 GPU，检查各类请求和两次小运行
ACCOUNT=def-yourpi STAGE=check bash slurm/run_all.sh       # 然后：还原度检查和难度校准（见下）
ACCOUNT=def-yourpi DRY=1 STAGE=all bash slurm/run_all.sh   # 只打印作业，不提交也不写文件
ACCOUNT=def-yourpi bash slurm/run_all.sh                   # 第 1 阶段：基线、还原度检查、兼容赛道
ACCOUNT=def-yourpi RUN=<run> STAGE=2 bash slurm/run_all.sh # 第 2 阶段：网络赛道，写进同一个运行目录
python -m netagents.report $SCRATCH/worldseeds/results/net/runs/<run>   # 随时重建索引
```

- `STAGE=smoke`（`netagents/smoke.py`）最先跑，只花几分钟 GPU：
  - 服务器能否启动；
  - 设计会发的各类请求（普通对话、必须调工具、自动调工具、关思考、JSON、4 万 token 长提示）是否都正常；
  - 一次 `sas` 和一次 `centralized` 小运行有没有模型错误。
  
  结果打印成表，完整错误保存在 `smoke/smoke.json`。
  
  一个作业里的运行默认 8 个并行（`--parallel`），每个在独立进程里、用独立的模型客户端。思考把 8192 个输出 token 用完的一步，会关掉思考重做一次，并计入 `overflows`。这些修复都来自 pilot 暴露的问题：
  - 共享文件系统上的 Triton 缓存报 stale file handle；
  - 原来 4096 的输出上限被思考用光；
  - 模型客户端跨运行复用（`Event loop is closed`）；
  - 运行逐个串行。评测作业连续 3 次运行出现模型错误就会自动停下并打印错误（`--stop-after`），不会在坏掉的配置上白耗一天 GPU。
- `STAGE=check` 接着跑，它的两个结果决定正式实验值不值得花 GPU 时间：
  - 还原度检查：我们的运行框架是否和直接对话一样好？移植版单智能体在 GSM8K 上应接近作者代码的单智能体；
  - 难度校准：`sas`、`reflexion`、`centralized`、`debate` 四个设计在简单档、中等档和兼容用例上跑开发种子。预设是按脚本团队校准的；平均完成率低于 20% 或高于 80% 的用例，在 `calibration/summary.md` 里标为“太难”或“太简单”，那里分不出设计高下，正式跑之前要先按这个模型调整预设。
- 第 1 阶段 22 个作业：脚本基线（CPU）、GSM8K 还原度检查、10 个设计跑兼容赛道、8 个多智能体设计让兼容用例改走网络，每个实验再加一个汇总作业。
- 第 2 阶段 66 个作业。
- `FRAMEWORKS=1` 把 AutoGen、Magentic-One、CAMEL 加进兼容赛道和 `test`；`SEEDS=2` 只跑前 2 个种子，快速试跑；`MODEL_ID` 换模型。
- 用同一个 `RUN` 再运行一次就是续跑：已完成的运行会跳过，已有结果的基线和还原度检查也不会重跑。

目录结构（`$SCRATCH/worldseeds/results/net/runs/<日期>-<模型>/`）：
- `README.md`：索引，每个实验的作业、各设计已完成的运行数和主表；
- `plan.tsv`：实验、设计、Slurm 作业号、命令；
- `commit.txt`、`env.txt`：代码版本（含未提交的改动）和每次提交时的设置；
- `logs/`：Slurm 和 vLLM 日志；
- `baselines/`：脚本团队基线；
- `fidelity/debate.json`：辩论的还原度检查，附论文数字；
- `compat-framework/`、`compat-network/`：兼容赛道（框架转交 / 走网络），每个设计一个子目录 `<设计>/runs.jsonl`，汇总在 `summary.md`，结论判定在 `hypotheses.json`；
- `test/`、`hard/`、`heldout/`、`scaling/`、`topology/`、`robustness/`：网络赛道，结构相同。

## 智能体网络的扩展（`--suite netscale-pilot`、`--suite netscale`）

- **问题**（DAG 环境 `worldseeds/net/providers/dag.py`）：
  - 若干层任务加一道汇总题；
  - 每道题有自己的隐藏函数（带密钥的哈希），只能通过 `apply` 一次一次地算；
  - 起点是父任务答案之和（模 1000），连续算 `grain` 次；
  - 只收整数答案，精确比对。

  推理绕不过去，所以工作量和关键路径是任何智能体的下界：单人至少 W = 任务数 x (grain + 1) 步，N 人至少 max(W / N, D) 轮。
- **为什么不用递推题**：10 月 22 日的试跑里，强模型直接提交闭式表达式，还把父任务的表达式嵌进子任务，单人比"参考"还快，工作量和关键路径都不成立。
- **参考**：理论下界（共享答案按零成本算），以及三种脚本团队中最快的一个：每题单独广播、共享存储、按层批量发送。8 人时，参考团队在 grain 1 下达到下界加速比的 65%，grain 4 下达到 77%：任务越粗，越能抵消共享的开销。每道题的函数链上没有重复值，所以不可能靠复用已经见过的结果省掉一次 `apply`。
- **指标**：轮数 T、相对下界的效率 b、相对参考的接近度 a、协调效率 eta、加速比、扩展定律拟合、动作分布。
- **试跑**：固定问题，grain 1 和 4，1、2、4、8 人，3 个种子，共 24 次运行。

## 两条赛道

已发表的设计默认的条件，正是本环境有意超出的：每个智能体都一样、任务靠答案检验、没有截止时间、消息由框架免费转交。如果一个设计在这里表现差，可能是设计本身弱，也可能只是它本来就不是为这种条件设计的。所以每个设计都跑两条赛道：

- **兼容赛道**（`--suite compat`）：原论文的条件。`compat/*` 配置让每人拥有全部工具、不设截止时间、只检验答案；设计之间的消息照原作代码那样由框架转交。先在这里复现已发表的结论，复现了的设计才拿到网络赛道上比较。
- **网络赛道**（其余测试组）：本环境新增的东西。工具按角色拆分、共处一个世界、网络有形状、延迟、掉线和成本。设计的消息改走环境的网络：发送记在发送方账上，读收件箱记在接收方账上，发给非邻居的消息会丢。不是环境里智能体的说话者（Kim 等的调度者、LbMAS 的控制单元）借第一个智能体的位置发言。

切换只靠一个对象：`netagents/designs.py` 里的 `Channel`，所有多智能体移植都用它，所以两条赛道上的提示词和协议完全一样。`--route framework|network` 可以覆盖赛道的默认值，例如让兼容用例改走网络，单独量出“真实通信”的代价。AutoGen 和 CAMEL 自己传消息，始终走框架；每次运行都记录实际走的路线，以及送达和丢失的条数。

**兼容赛道上检验的已发表结论**（`testset.HYPOTHESES`）：
- Kim 等 2026：可分解任务上，所有多智能体结构都优于单智能体（Finance-Agent，+57% 至 +81%）。对应 `compat/math-decomposable`：4 道互不相关的递推题加一个求和。
- Kim 等 2026：顺序任务上，所有多智能体结构都差于单智能体（PlanCraft，−39% 至 −70%）。对应 `compat/math-sequential`：同样 4 道递推题连成一条链，每道的初值取自上一道的答案。
- Du 等 2024：辩论在算术应用题上优于单智能体。直接在 GSM8K 上，用 `netagents/fidelity.py` 对照作者自己的代码检验。

评测按种子配对，计算任务完成比例之差的均值和 95% bootstrap 区间，并判定为“复现”（区间整体落在论文给出的一侧）、“相反”（落在另一侧）或“不确定”。结果表写进 `summary.md`，数字在 `hypotheses.json`。

## 设计和它们与原作的接近程度

每个设计都标了是怎么做出来的：
- **移植（port）**：照作者公开的代码做，提示词按代码许可原文引用，参数也照原样；原作只输出文字的，改成了用工具。
- **重新实现（reimplementation）**：作者没有公开代码（或没找到），按论文描述写的，发表前必须对照论文核实。
- **框架（framework）**：直接用作者自己的框架（原样使用），通过适配层驱动我们的工具；在各自的 Python 环境里运行，通过 HTTP 连接环境，模型服务和调用池与其他设计相同。

| 设计 | 出处 | 接近程度 |
|---|---|---|
| `react` | ReAct（Yao 等，ICLR 2023），官方代码，MIT | 移植 |
| `reflexion` | Reflexion（Shinn 等，NeurIPS 2023），官方代码，MIT，反思提示词原文引用 | 移植 |
| `debate` | 多智能体辩论（Du 等，ICML 2024），官方仓库无许可证，提示词为转述；原设定 3 人 2 轮 | 移植 |
| `moa` | Mixture-of-Agents（Wang 等，arXiv 2406.04692），官方代码，Apache-2.0，聚合提示词原文引用 | 移植 |
| `sas`、`independent`、`centralized`、`decentralized`、`hybrid` | Kim 等（arXiv 2512.08296 v3），官方代码 ybkim95/agent-scaling，MIT，提示词原文，参数按论文附录 E.2 | 移植 |
| `blackboard` | LbMAS（Han & Zhang，arXiv 2507.01701），代码未发布；提示词按论文附录图 4–6 转录，流程按算法 1 | 移植 |
| `autogen-roundrobin`、`autogen-selector` | AutoGen（Wu 等 2023），autogen-agentchat 0.7.5，MIT | 框架 |
| `magentic-one` | Magentic-One（Fourney 等 2024）的协调者，autogen-agentchat 0.7.5，MIT | 框架 |
| `camel-roleplay` | CAMEL 角色扮演（Li 等，NeurIPS 2023），camel-ai 0.2.90，Apache-2.0 | 框架 |

与原作的每一处差异见上面英文表格的最后一列，可直接放进论文。

**已对照原论文核对的设置**：
- ReAct：论文用贪心解码，最多 7 步（HotpotQA）、5 步（FEVER）、50 步（ALFWorld），失败时退回 CoT-SC。我们零样本、步数上限即调用预算、不退回 CoT-SC。
- Reflexion：论文的记忆上限 Ω 为 1–3 条（HotPotQA 和 ALFWorld 用 3 条），已从原来的 8 条改为 3 条。触发反思的条件：我们用“提交被拒或这一轮没做完”，没用论文 ALFWorld 上的启发式（同一动作和结果重复 3 次以上，或超过 30 步）。
- 辩论：论文 3 个智能体、2 轮，GSM8K 100 题上单智能体 77.0、辩论 85.0。兼容赛道和还原度检查都用 3 人 2 轮，还原度报告里并列给出论文数字。
- AutoGen：论文的动态群聊（管理者选下一位发言者，再广播），对应 `autogen-selector`；`autogen-roundrobin` 是框架自带的团队，论文里没有评测过。
- CAMEL：论文的终止条件已加上——40 条消息、连续 3 轮用户不下指令、结束标记；只有“角色反转”没有检测。

- Mixture-of-Agents：论文默认 3 层、6 个不同的开源模型；MoA-Lite 是 2 层。我们用 2 层（即 MoA-Lite，也是官方代码的默认值），只用一个模型，对应论文里的“单一提议者”设置。
- Magentic-One：外层循环维护任务账本（事实、猜测、计划，重订计划时所有智能体清空上下文），内层循环维护进度账本；停滞计数超过 2 就重订计划。我们用 AutoGen 的实现，显式设 `max_stalls=3`，阈值与论文相同；只用一个模型。

所有设计都已对照过原论文。

**统一的模型设置**：所有设计和框架用同一套设置——Qwen3 的思考模式，温度 0.6、top_p 0.95、top_k 20（Qwen 对思考模式推荐的值），单次输出上限 4096 token；思考内容由 vLLM 的推理解析器分离，不进入答案和对话历史。
- 原因：第一次正式运行（`20261013-qwen3-8b-ea182dd`）关掉了思考、又要求每步必须调用工具，智能体完全没有推理的机会。同一个模型在 GSM8K 上直接对话 90%，放进我们的环境只有 51%。
- 同时修了：
  - 每个智能体的对话历史在每轮开始前裁到窗口的 60%，先丢最早的步骤；
  - 上下文窗口开到 64k（YaRN）；
  - AutoGen 每个模型只看任务和最近 30 条消息（那次运行里 AutoGen 大多因超出上下文而中断）；
  - Magentic-One 的账本改用结构化 JSON 输出（那次全部因账本解析失败而中断）。
- 每次运行还会记录工具调用分布、错误、上下文裁剪次数和峰值，并为每个用例保存一条完整轨迹。

发表前还要做一件事：用修好的运行框架重跑还原度检查（`STAGE=fidelity`）。同一个模型、同一批题，作者自己的消息构造函数和我们的移植版放在一起比，看移植版相对单智能体的提升，是否落在官方提升的置信区间内。等我们的单智能体接近直接对话的准确率后，再重跑全部实验。

MetaGPT（Hong 等，ICLR 2024）只作为相关工作引用，不在环境里运行：它发布的版本都锁定了一个已从 PyPI 下架的依赖（`lancedb==0.4.0`），而且它固定的软件公司角色（产品经理、架构师、工程师）和网站任务里的角色分工已经很接近。

## 同等算力

- **工具调用**：同一用例上，每个设计的 LLM 工具调用总数相同（每人 40 次 × 团队人数），全队共用一个池，不会超额。
- **环境预算**：总量相同。单智能体设计用 `solo`（全队预算、但截止时间相同），`independent` 用 `nonet`，其余用 `team`。
- **token**：逐人记录。

依据是三项研究：
- Tran & Kiela 2026 发现，同等思考 token 下单智能体不输多智能体；
- Kim 等 2025 统一了工具、提示和算力来比较不同结构；
- MAST 指出，多智能体相对单智能体和 best-of-N 的提升常常很小。

## 测试组

种子 0–2 用于开发，100–109 是测试种子，不能用来调设计。

| 测试组 | 内容 |
|---|---|
| `dev`、`test` | 四个任务的中等难度（主表用 `test`） |
| `hard` | 困难档 |
| `heldout` | 留出任务 |
| `scaling` | 2、4、8、16 人（参考 AgentsNet 和 MacNet） |
| `topology` | 全连、链、星、树、环、随机（参考 MultiAgentBench 和 AgentsNet） |
| `robustness` | 规律漂移、客户改需求、网络掉线和延迟（参考 MAST） |
| `org` | 中等档数学和 CodeWorld，上面加 0、1、2 层经理（参考 El Agente Q） |
| `faults` | 工具结果有 15% 静默出错或 15% 直接报错，可用 `check` 检查 |
| `report` | 最后交一份包含所有答案的报告，逐项打分；数学另有一组要求答案必须有出处 |
| `guidance` | 同样的任务，给或不给操作提示 |
| `memory` | 连续十个回合，共享一个跨回合保留的记忆 |
| `compat` | 兼容赛道：可分解数学、顺序数学、6 个独立项目的 CodeWorld |

## 指标

- **结果**：是否解出、任务完成比例、环境动作数。
- **成本**：工具调用次数、token。
- **交流**：消息、帖子、共享库写入。
- **失败信号**，按 MAST 的三类：
  - 重复劳动（系统设计）；
  - 未读消息（智能体之间不协调）；
  - 错误提交（任务检验）；
  - 有预算却提前停下；
  - 无出处的提交（猜的或假设的值，团队里谁都没算出也没传过）；
  - 只有队友算过、却从没传过来的值；
  - 用了静默出错的结果。
