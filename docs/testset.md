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

## Agent designs (each from a published paper)

| name | design | source |
|---|---|---|
| `react` | one agent that reasons and acts with one tool call at a time | Yao et al., [ReAct](https://arxiv.org/abs/2210.03629), ICLR 2023 |
| `reflexion` | ReAct, plus a verbal self-reflection after every rejected submission. Reflections are kept in an episodic memory, optionally across episodes. | Shinn et al., Reflexion, NeurIPS 2023 (arXiv 2303.11366) |
| `independent` | n agents in parallel with no communication | Kim et al., [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296), 2025 ("independent") |
| `centralized` | an orchestrator assigns work by message; workers report back; only the orchestrator submits | Kim et al. 2025 ("centralized"). Orchestrator-worker as in AutoGen's group chat manager ([Wu et al. 2023](https://arxiv.org/abs/2308.08155)). |
| `decentralized` | peers work, publish their results on the board each round, read and critique the others' results, and revise | Kim et al. 2025 ("decentralized"); Du et al., [Multiagent Debate](https://proceedings.mlr.press/v235/du24e.html), ICML 2024 |
| `hybrid` | an orchestrator, and workers who may also message each other | Kim et al. 2025 ("hybrid") |
| `blackboard` | all communication goes through the board; a control unit reads it each round and picks who acts | Han & Zhang, [blackboard LLM multi-agent systems](https://arxiv.org/abs/2507.01701), 2025; Salemi et al., [blackboard system for information discovery](https://arxiv.org/abs/2510.01285), 2025 |
| `moa` | layers of proposers, each reading the previous layer's outputs; an aggregator submits | Wang et al., [Mixture-of-Agents](https://arxiv.org/abs/2406.04692), 2024 |
| `metagpt` | roles act in the provider's order (a standard operating procedure). Each role publishes a structured document to a shared pool and reads only the roles before it (publish-subscribe). | Hong et al., [MetaGPT](https://proceedings.iclr.cc/paper_files/paper/2024/hash/6507b115562bb0a305f1958ccc87355a-Abstract-Conference.html), ICLR 2024 |

The prompts paraphrase each paper's protocol and say nothing specific to a task provider. Rules are
enforced where the protocol needs them:
- workers in `centralized` and `hybrid` have no `submit` tool;
- `blackboard` members have no direct messages;
- `independent` runs on the `nonet` variant (no messages, board or store).

Every design uses the same tools, generated from the environment's op specs, and the same model.

Not implemented as separate designs:
- **Network shape** is a property of the environment, not of a design: the `topology` suite runs designs on full, chain, star, tree, ring and random networks.
- **CAMEL's two-agent role play** (an AI user instructing an AI assistant) is close to `centralized` with one worker.
- **GPTSwarm** ([Zhuge et al., ICML 2024](https://proceedings.mlr.press/v235/zhuge24a.html)), DyLAN and other designs that optimise the graph would be trained on the dev suite and evaluated on the test suite like any other design.

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

`summary.md` gives one table per suite. The rows are designs and the columns are cases. Each cell shows the share of seeds solved, with the share of tasks done in brackets. Mean tokens and failure signals are added at the end of each row.

---

# 测试集与已发表的智能体设计（中文）

这份文档说明在网络环境上比较智能体设计的方法：
- 实现了哪些已发表的设计；
- 在哪些设置上跑；
- 怎么对齐算力；
- 量哪些指标。

代码在 `netagents/designs.py`、`netagents/testset.py`、`netagents/evaluate.py`。

## 设计（每个都对应一篇论文）

| 名字 | 做法 | 论文 |
|---|---|---|
| `react` | 单个智能体，边推理边调用工具 | Yao 等，ReAct，ICLR 2023 |
| `reflexion` | ReAct 加上提交失败后的自我反思，反思存进记忆，可以跨局保留 | Shinn 等，Reflexion，NeurIPS 2023 |
| `independent` | 多个智能体并行，互不通信 | Kim 等 2025 的"independent" |
| `centralized` | 协调者通过消息分派任务，工人回报结果，只有协调者能提交 | Kim 等 2025；AutoGen 的群聊管理者 |
| `decentralized` | 平级的智能体每轮把结果贴到公告板，读别人的、批评、修改 | Kim 等 2025；Du 等的多智能体辩论，ICML 2024 |
| `hybrid` | 有协调者，工人之间也能直接交流 | Kim 等 2025 |
| `blackboard` | 所有交流只走公告板，控制单元每轮读板决定谁行动 | Han & Zhang 2025；Salemi 等 2025 |
| `moa` | 多层提议者，每层读上一层的结果，最后由聚合者提交 | Wang 等，Mixture-of-Agents，2024 |
| `metagpt` | 按标准流程像流水线一样依次行动，结构化文档发到共享池，只订阅前面角色的文档 | Hong 等，MetaGPT，ICLR 2024 |

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

## 指标

- **结果**：是否解出、任务完成比例、环境动作数。
- **成本**：工具调用次数、token。
- **交流**：消息、帖子、共享库写入。
- **失败信号**，按 MAST 的三类：
  - 重复劳动（系统设计）；
  - 未读消息（智能体之间不协调）；
  - 错误提交（任务检验）；
  - 有预算却提前停下。
