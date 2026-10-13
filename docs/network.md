# The agent network: one environment, pluggable tasks

`worldseeds/net/` is the environment for studying networks of agents: task distribution, information
sharing, many agents attacking one problem, division of labour. It is a simulator. It moves messages,
runs the task market and the shared store, charges every action and keeps score. It never says how
agents should cooperate; that is left to whatever drives them (scripts, LLMs, a policy being trained).

The work itself comes from a **task provider**. Swap the provider and the work changes, while
everything else stays: the network switches, the event log, the LLM tools and the HTTP API.

```
            agents (LLM / RL / scripts / anything over HTTP)
                 │  step(agent, op, args) -> observation
        ┌────────┴─────────────────────────────────────────┐
        │ NetworkEnv  messages · board · task market (DAG)  │
        │             versioned store · credits · reputation│
        │             topology · latency · outages · budget │
        └────────┬─────────────────────────────────────────┘
                 │  roles · ops · apply · tasks · verify · tick
        ┌────────┴──────┬────────────┬─────────────┬───────────┐
        │ codeworld     │ math       │ website     │ molecule  │  … your own
        └───────────────┴────────────┴─────────────┴───────────┘
```

## The provider interface (`worldseeds/net/core.py`)

```python
class TaskProvider:
    def reset(self, seed) -> dict              # a fresh instance; a public description
    def roles(self) -> list[Role]              # who takes part, which ops each role may use, how many
    def ops(self) -> list[OpSpec]              # name, help text, JSON-schema parameters, cost in actions
    def apply(self, agent, role, op, args) -> dict   # do one op, return what the agent sees
    def tasks(self) -> list[Task]              # a DAG: a task opens when its deps are done; `final` ends it
    def verify(self, task, artifact, agent) -> Score # the ground truth lives only here
    def tick(self, round) -> list[dict]        # optional: the world changes (drift, new requirements)
    def artifact_schema(self) -> dict          # what `submit` takes
```

To put a new kind of work on the network, write these few methods. A real task needs a checker
(`verify`) and a set of operations with costs. Everything else is already there.

## The network (`worldseeds/net/env.py`)

`env.step(agent, op, args)` returns a JSON-able observation and charges the op's cost to the agent's
budget. A *round* passes when the agents together have spent as many actions as there are agents.
Latency, outages and `tick` run on rounds.

| op | what it does |
|---|---|
| `status`, `who` | own state; everyone's role, reputation, online status (free) |
| `tasks` | the market: open, blocked and done tasks, deps, claims, tries |
| `claim`, `release` | take a task (`market="claim"`; `exclusive` locks it) |
| `send`, `inbox` | messages to neighbours (or `*`), delivered after `latency` rounds |
| `post`, `board` | public notice board (world events are posted there too) |
| `put`, `get`, `keys` | shared store; every version kept with writer and round; `store_price` pays the writer |
| `transfer` | give credits |
| `submit` | hand in an artifact (or a store key); checked by the provider (`verify_cost`) |
| `wait` | pass |

Switches in `NetConfig` include:
- `agents`: how many of each role.
- `budget`.
- `messaging`, `board`, `store`.
- `market`: `open`, `claim` or `assigned`.
- `topology`: `full`, `ring`, `star` or `random` (with `degree`).
- `latency`, `outage`, `outage_rounds`.
- `credits`, `bounty`, `store_price`, `transfers`.
- `reputation`, `verify_cost`, `wrong_penalty`.
- `team`: 0 gives each reward to the solver, 1 shares it equally.

Every call is logged (`env.events`, `save_events`). `metrics()` sums up the run.

## The providers

**codeworld**: the synthetic twin.
- Functions have hidden laws. Projects ask for a chain of functions that fits some examples.
- Ops: `signatures`, `run` (cost 1), `study` (learn a law, cost 8).
- `owners=True` gives each module an owner role, and only the owner can study that module, so knowledge must travel. `drift` re-tunes laws.

**math**: a problem cut into lemmas, checked by SymPy.
- Roles split the tools. The explorer has `evaluate` and `sequence`; the algebraist has `simplify`, `solve` and `rsolve`.
- Answers are checked symbolically after a numeric screen. Expressions go through a whitelist parser that refuses attribute access, with a time limit.
- Seeded problem families are `recurrence` and `sum`. Any number of them can be joined by a final `combine` task.
- You can load your own problem from JSON (`problem_file=`). Tasks of kind `lean` are checked by a `lean` executable if one is installed.

**website**: building software.
- The team shares a versioned workspace: `ls`, `read`, `write`, `log`. Roles own path prefixes.
- `run_tests` runs the public tests and the team's own `tests/` in a sandbox. The sandbox is a temp dir, a separate `python -I` process, CPU, memory and time limits, and a stripped environment. It is not a security boundary, so run untrusted agents in a container.
- `ask_client` answers from hidden notes, and only the PM may ask.
- Features have hidden acceptance tests. The final `release` task runs them all.
- The built-in task is a small WSGI shop. Its name, hours, products and discount are drawn from the seed.
- `change` makes the client change a price mid-episode.
- You can load any task from a directory with `task.json`, `starter/` and `hidden/` (`task_dir=`).

**molecule**: design with RDKit.
- Chemists `edit` molecules with named edits (add a group to an aromatic carbon, aza, remove a substituent …) and compute `props`.
- Biologists run `assay` (activity, noisy, cost 5) and `tox` (noisy, cost 3).
- Only molecules someone has made can be assayed.
- The hidden structure–activity function is drawn from the seed: helpful and harmful motifs, a preferred logP and a size penalty. `oracle="pkg.mod:fn"` swaps in a real model.
- The tasks are hit → lead → candidate. Their thresholds are calibrated at reset by a search over the edit space, so the episode is solvable.
- You can load your own targets from JSON (`target_file=`).

## Agents live elsewhere (`netagents/`)

The environment holds no agent code. Agents are in `netagents/` and reach the environment only through its public interface (`step`, `ops`, `observe`, `public`), in the same process (`LocalEnv`) or over HTTP (`RemoteEnv`). The environment's HTTP server (`worldseeds/net/server.py`, `scripts/run_net.py`) also returns each agent's operations in OpenAI tool format.

## Adapters (in `netagents/`)

- `netagents/tools.py`:
  - `env.tools(agent)` gives the OpenAI chat "tools" list.
  - `function_tools(env, agent)` gives Agents SDK tools.
  - `briefing(env, agent)` gives neutral instructions with no strategy.
  - All of these are generated from the op specs, so new providers get tools for free.
- `netagents/team.py`:
  - `run_llm_team` runs every agent concurrently on its own conversation.
  - `random_policy` fuzzes a provider.
- `worldseeds/net/server.py` is the HTTP JSON API (`/info`, `/reset`, `/ops`, `/observe`, `/step`, `/events`, `/metrics`) for agents in any language.
- `python -m netagents.run` runs agents; `scripts/run_net.py` serves the environment:

```bash
python -m netagents.run --provider math --policy scripted --seeds 0 1 2
python -m netagents.run --provider website --policy llm --net budget=150 latency=1 team=0.5 --opt change=0.05
python scripts/run_net.py --preset molecule/hard --serve 8090          # the environment, in its own process
python -m netagents.run --remote http://127.0.0.1:8090 --policy llm    # agents, in another
```

## Watching a run in the town (`worldseeds/net/replay.py`)

`town_replay(env)` turns the event log of a run on the codeworld provider with `theme="town"` into a
replay for `web/codeworld.html`, whoever the agents were. Each operation becomes a scene:
- `study`: walk to the workshop and learn the machine's rule;
- `put` / `get`: the library;
- `send`: a letter through the post office;
- `post` / `board`: the notice board;
- `claim` / `submit`: take and deliver an order;
- anything else: a line in the log.

The network charges nothing for walking, so walks are only drawn. `python -m netagents.replays` records
reference teams, or LLM teams with `--llm`.

## Presets: difficulty, held-out tasks, variants (`worldseeds/net/presets.py`)

Each provider has three difficulties. Difficulty grows along the same axes everywhere:
- more work than one member's budget covers;
- information split across roles;
- a slower, sparser, less reliable network;
- a world that changes;
- costlier mistakes.

Medium and hard run against the clock. The deadline, in rounds, equals one member's budget.

Every preset comes in three variants with the same total compute and the same deadline:

| variant | what it is |
|---|---|
| `team` | the preset as written |
| `solo` | one agent with every tool and the whole team's budget, but the same time. A round is one action for one agent and n actions for a team of n, so solo can spend only 1/n of its budget before the deadline. |
| `nonet` | the team with no messages, board or shared store: everyone works alone, in parallel |

Held-out presets load tasks from `tasks/heldout/` that no scripted team was written for:
- two math problem sets (number theory, combinatorics);
- a to-do API website task;
- a molecule target profile around an aminopyrimidine.

They test whether what agents learned carries over. The molecule targets are relative to the start
(`activity_gain`). The preset lists the seeds on which a search over the edit space reaches every target.

```bash
python scripts/run_net.py --list-presets
python -m netagents.run --preset math/hard --variant solo --policy llm
python -m netagents.baselines --seeds 10 --out results/net/baselines     # the table below
```

## Reference teams (`netagents/scripted.py`)

The scripted teams are reference solutions written for the built-in generators. They know the problem
wording and what the client will say, so they are not baselines to beat. They work only on the built-in
tasks, not the held-out ones.

They are honest about the network:
- they pick agents by what their role can do;
- they claim tasks when the market requires it;
- they wait out outages;
- they move information between agents only through the network (store, else messages, else board). With those off, nothing travels.

What they give:
- proof that each built-in difficulty can be solved through the public operations;
- a reference cost;
- the effect of the network on a fixed strategy.

The comparison that matters for learning agents is a learned team against the same agents in the
`solo` and `nonet` variants, and performance on held-out tasks.

Ten seeds per cell. Each cell shows the share of seeds solved, and in brackets the share of tasks done:

| preset | team | solo | nonet | team rounds |
|---|---|---|---|---|
| codeworld/easy | 1.0 (1.00) | 1.0 (1.00) | 1.0 (1.00) | 44 |
| codeworld/medium | 1.0 (1.00) | 0.0 (0.03) | 0.0 (0.41) | 83 |
| codeworld/hard | 0.0 (0.72) | 0.0 (0.01) | 0.0 (0.00) | 66 |
| math/easy | 1.0 (1.00) | 1.0 (1.00) | 0.0 (0.57) | 8 |
| math/medium | 1.0 (1.00) | 1.0 (1.00) | 0.0 (0.62) | 10 |
| math/hard | 0.9 (1.00) | 0.0 (0.35) | 0.0 (0.64) | 26 |
| website/easy | 1.0 (1.00) | 1.0 (1.00) | 0.0 (0.00) | 5 |
| website/medium | 0.9 (0.95) | 0.7 (0.87) | 0.0 (0.00) | 4 |
| website/hard | 0.7 (0.90) | 0.2 (0.65) | 0.0 (0.00) | 7 |
| molecule/easy | 0.8 (0.80) | 0.8 (0.80) | 0.0 (0.00) | 51 |
| molecule/medium | 0.7 (0.70) | 0.1 (0.20) | 0.0 (0.00) | 59 |
| molecule/hard | 0.6 (0.67) | 0.0 (0.00) | 0.0 (0.00) | 84 |

How to read it:
- **Easy** has no deadline: team and solo both solve it, and nonet already fails wherever roles must exchange information.
- **Medium and hard** separate the variants.
  - Under the same deadline, `solo` falls behind: it has the compute but not the time.
  - `nonet` fails wherever roles hold different information or tools. In CodeWorld without owners, it only wastes work (everyone studies the same functions).
- **The reference teams do not max out hard.** Laws drift (CodeWorld), the client changes their mind (website), assays are noisy (molecule), and the scripts do not adapt to any of it. That is the room left for agents that learn.
- **Exceptions:**
  - On math/medium, solo still makes the deadline (38 of 40 rounds).
  - The website tasks are small enough that solo solves most seeds.


---

# 智能体网络：一个环境，可插拔的任务（中文）

`worldseeds/net/` 是研究智能体网络的环境，研究的对象包括任务分发、信息共享、多个智能体一起攻克一道题，以及分工协作。

它是模拟器，负责的事情是：传递消息，运行任务市场和共享库，给每个动作计费，记分。它不规定智能体该怎么合作，这留给驱动智能体的东西（脚本、LLM、将来要训练的策略）。

具体做什么工作，由**任务提供者**决定。换一个提供者，工作就换了，其余的都不变：网络开关、事件日志、自动生成的 LLM 工具和 HTTP 接口。

**接口**：一个提供者只需实现这几个方法：`reset`、`roles`、`ops`、`apply`、`tasks`、`verify`，可选 `tick`。真实任务只需要两样东西：一个检验器（`verify`），一组带成本的操作。

**网络层**：
- 每个操作都扣行动预算；所有智能体合计花掉的动作数等于人数时，算过了一轮。
- 内置操作：
  - 消息：`send`/`inbox`，有延迟和拓扑限制。
  - 公告板：`post`/`board`。
  - 任务市场：`tasks`/`claim`，任务是依赖图。
  - 版本化共享库：`put`/`get`/`keys`，可以设读取付费。
  - 转账：`transfer`。
  - 提交检验：`submit`。
- 都能在 `NetConfig` 里开关，包括：拓扑、延迟、掉线、额度、信誉、检验成本、错误惩罚，以及团队/个人奖励的混合比例。

**四个提供者**：
- **codeworld**：合成的对照任务。打开 `owners` 后只有模块主人能研究本模块，知识必须在网络里流动。
- **math**：题目拆成引理依赖图，用 SymPy 检验。探索者只能算数，代数手只能做符号推导。可以用 JSON 载入自己的题目，Lean 是可选的。
- **website**：
  - 共享的版本化工作区，角色只能写自己的文件。
  - 测试在沙箱里跑，验收测试是隐藏的。
  - 只有产品经理能"问客户"，客户还会中途改需求。
  - 可以从目录载入任意编程任务。
- **molecule**：
  - 用 RDKit。化学家做结构修改，生物学家做带噪声、成本高的活性和毒性实验。
  - 隐藏的构效关系由种子决定，也可以换成真实模型。
  - 阈值在重置时校准过，保证有解。

**对外接口**：
- 根据操作说明自动生成 OpenAI tools 和 Agents SDK 工具。
- LLM 团队并发运行。
- 随机策略用来做健壮性测试。
- HTTP 服务任何语言都能接入。
- 智能体全部在 `netagents/`，只通过公开接口（本进程或 HTTP）访问环境；`python -m netagents.run` 运行智能体，`scripts/run_net.py` 只负责提供环境服务。

**基线**（脚本团队，10 个种子）：
- CodeWorld：共享规律 128 个动作，不共享 190 个，都 10/10 解出。
- 数学：10/10，26 个动作。
- 网站：10/10，23 个动作。
- 分子：8/10，205 个动作。
