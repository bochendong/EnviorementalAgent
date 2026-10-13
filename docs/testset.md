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
| `react` ReAct | Yao et al., ReAct: Synergizing Reasoning and Acting in Language Models, ICLR 2023; code: ysymyth/ReAct, noahshinn/reflexion (MIT) | port | solo | native tool calls instead of Thought/Action text lines; no few-shot examples (theirs are task-specific) |
| `reflexion` Reflexion | Shinn et al., Reflexion: Language Agents with Verbal Reinforcement Learning, NeurIPS 2023; code: noahshinn/reflexion (MIT) | port | solo | trials share one episode and its budget instead of re-running the same task; a trial fails on a wrong submission or when its step quota runs out; the environment's verdict is the evaluator; no few-shot reflection examples |
| `debate` Multiagent debate | Du et al., Improving Factuality and Reasoning in Language Models through Multiagent Debate, ICML 2024; code: composable-models/llm_multiagent_debate (no licence: prompt paraphrased) | port | team | agents use tools between rounds; a solution is what an agent states at the end of a round; solutions pass through the design's channel (the framework, or the environment's network); agents submit themselves instead of a majority vote over final answers; team size is the preset's, not 3 |
| `moa` Mixture-of-Agents | Wang et al., Mixture-of-Agents Enhances Large Language Model Capabilities, arXiv 2406.04692 (2024); code: togethercomputer/MoA (Apache-2.0) | port | team | one model in every position instead of different open-source models; proposers use tools; their responses pass through the design's channel; the aggregate prompt is a user message, not a system message; the aggregator is one of the team, with its role's tools |
| `sas` Single-agent system (Kim et al.) | Kim et al., Towards a Science of Scaling Agent Systems, arXiv 2512.08296 v3 (2026); code: ybkim95/agent-scaling (MIT) | port | solo | iterations are tool calls; the single agent gets the team's whole pool of calls (the paper gives it proportionally more iterations) |
| `independent` Independent (Kim et al.) | Kim et al. 2026; code: ybkim95/agent-scaling (MIT) | port | nonet | the agents act in one shared environment, not in a copy each; the synthesis-only aggregate is recorded but not submitted: our submissions need a task and an artifact, so each agent submits its own; team size is the preset's, not 3 |
| `centralized` Centralized (Kim et al.) | Kim et al. 2026; code: ybkim95/agent-scaling (MIT) | port | team | the orchestrator reads the task list once through the first worker (one action); the final auto-submit is a turn of the first worker given the synthesis; orchestrator-worker messages pass through the design's channel: the framework, as in the authors' code, or the environment's network; team size is the preset's, not 3 |
| `decentralized` Decentralized (Kim et al.) | Kim et al. 2026; code: ybkim95/agent-scaling (MIT) | port | team | the consensus vote over final answers is recorded; agents submit their own results; peer answers pass through the design's channel (the framework, or the network); team size is the preset's, not 3 |
| `hybrid` Hybrid (Kim et al.) | Kim et al. 2026; code: ybkim95/agent-scaling (MIT) | port | team | as centralized, plus the authors' final peer round; team size is the preset's, not 3 |
| `blackboard` LbMAS blackboard system | Han & Zhang, Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture, arXiv 2507.01701v1 (2025); prompts from the paper (code not released) | port | team | the team's members (with the environment's tools) join as experts of their roles, besides 1-3 generated experts; one model for every agent instead of one drawn per agent from two models; no private spaces (debate, self-reflection); the decider's answer is handed to the team members to submit; solution by the decider only (not the similarity vote) |
| `autogen-roundrobin` AutoGen round-robin group chat | Wu et al., AutoGen, arXiv 2308.08155 (2023); autogen-agentchat 0.7.5 (MIT) | framework | team | members talk in the framework's shared conversation, outside the environment's network (not charged, no topology) |
| `autogen-selector` AutoGen group chat with a model-selected speaker | Wu et al., AutoGen, arXiv 2308.08155 (2023); autogen-agentchat 0.7.5 (MIT) | framework | team | members talk in the framework's shared conversation, outside the environment's network (not charged, no topology) |
| `magentic-one` Magentic-One orchestrator | Fourney et al., Magentic-One, arXiv 2411.04468 (2024); autogen-agentchat 0.7.5 (MIT) | framework | team | members talk in the framework's shared conversation, outside the environment's network (not charged, no topology); the orchestrator directs our role agents instead of Magentic-One's web, file and code agents |
| `camel-roleplay` CAMEL role playing | Li et al., CAMEL: Communicative Agents for "Mind" Exploration of Large Language Model Society, NeurIPS 2023; camel-ai 0.2.90 (Apache-2.0) | framework | solo | the assistant is the solo agent with every tool and the team's budget; the user agent has no tools; no task-specifier agent: the task given is already precise |

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

To do before publication:
- Run the fidelity checks on Nibi. Debate on GSM8K is ready (`sbatch slurm/net_fidelity.sh`).
- Decide on MetaGPT. Its released versions pin a dependency that has been removed from PyPI (`lancedb==0.4.0`).

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
  - `stopped_early`: members who stopped with budget left while the problem was unsolved.

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

发表前还要做三件事：
- 把 MetaGPT 也接成框架设计（AutoGen、Magentic-One、CAMEL 已完成）；
- 在 Nibi 上跑还原度检查。辩论在 GSM8K 上的检查已经写好（`sbatch slurm/net_fidelity.sh`）：同一个模型、同一批题，作者自己的消息构造函数和我们的移植版放在一起比，看移植版相对单智能体的提升，是否落在官方提升的置信区间内。

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
| `compat` | 兼容赛道：可分解数学、顺序数学、6 个独立项目的 CodeWorld |

## 指标

- **结果**：是否解出、任务完成比例、环境动作数。
- **成本**：工具调用次数、token。
- **交流**：消息、帖子、共享库写入。
- **失败信号**，按 MAST 的三类：
  - 重复劳动（系统设计）；
  - 未读消息（智能体之间不协调）；
  - 错误提交（任务检验）；
  - 有预算却提前停下。
