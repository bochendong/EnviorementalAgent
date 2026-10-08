# CodeWorld: networks of developer agents in a world too big for one mind

[English] · [中文 below](#中文)

## Why

The goal is an agent *network* whose collective knowledge exceeds what any single agent can hold, as a
foundation for many agents developing in parallel and across domains. Current multi-agent benchmarks do
not test that. Their tasks fit in one agent's context (with equal compute, a single agent matches or beats
the team: [Tran & Kiela 2026](https://arxiv.org/abs/2604.02460)), their knowledge is given rather than
learned ([EntCollabBench](https://arxiv.org/abs/2605.08761), [MultiAgentBench](https://arxiv.org/abs/2503.01935)),
their coordination tasks are unrelated to knowledge ([AgentsNet](https://arxiv.org/abs/2507.08616)), and
shared-memory studies have no ground truth to score memory against
([Governed Shared Memory](https://arxiv.org/abs/2606.24535)). CodeWorld is built so that

1. the world holds more knowledge than one agent can keep in mind,
2. that knowledge has to be learned by experiment,
3. useful work (a project) needs knowledge from several domains at once,
4. everything is scored exactly: every believed law, every program, every message.

The claim it can test: **a network beats one agent with the same compute exactly when the world is too big
for one agent, and only if the network knows who knows what.**

## The world

A universe is a software ecosystem (`worldseeds/codeworld/world.py`):

* **Modules** (auth, billing, geo, ...) expose **functions** with public signatures
  (`billing.quote_price: Order -> Price`) and hidden behaviour, a **law** on integers mod 101: `a*x + b`, or
  a different `a2*x + b2` on an edge case (`x` a multiple of 2, 3 or 5). Popular modules are used more (a
  long tail).
* Types sit on levels; every function goes one level up, so a **program** from type S to type G is a chain
  of known length. Many chains type-check (often 60–700), usually through functions of different modules.
* A **project** is a feature request: input type, output type and a few examples chosen so that exactly one
  program (up to programs computing the same thing) fits them. Its answer crosses about 3 modules.

## Developers and organisations

A developer (`org.py`) has a **notebook** of limited capacity (laws it can keep in mind; least recently used
are forgotten) and an action budget per sprint. To find out what a function does it can study it
(8 actions: probe inputs 0..7, which pins any law), or ask a teammate (1 action each; the teammate explains
the law, which the asker keeps for the current project only). It searches programs cheapest first, running
them on the examples, and submits the one that fits.

| organisation | who | how knowledge moves |
|---|---|---|
| `solo` | one developer with the **whole team's budget** | it studies everything itself |
| `solo_unbounded` | the same with unlimited memory | upper bound for one head |
| `independent` | n developers on their own projects | never talk |
| `owners` | n developers; every module has an owner (CODEOWNERS) | ask the owner, who learns its own module and keeps it |
| `directory` | n developers and a live registry of who knows what | ask someone who knows (else the owner) |
| `random` | n developers, no idea who knows what | ask up to two random teammates, then study yourself |
| `pooled` | n developers, one shared notebook of n × capacity, no message cost | upper bound for sharing |

LLM developers (`llm_agent.py`) get the same world through tools: `signatures`, `run`, `study`, `remember`
(write a law, scored against the truth), `notebook`, `compute` (run a program with known laws, free),
`ask`, `who_knows`, `submit`. Teammates answer from their notebooks.

## First results (heuristic developers, CPU)

Share of projects done in steady state (sprints 5–8, universes 1 and 2, teams of 4, 120 actions per
developer per sprint; solo gets 480):

| functions | capacity | regime | solo | solo, unlimited memory | independent | random | owners | directory | pooled |
|---|---|---|---|---|---|---|---|---|---|
| 16 | 16 | fits one head | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| 32 | 8 | fits the team | 0.40 | 1.00 | 0.42 | 0.53 | 1.00 | 1.00 | 1.00 |
| 64 | 16 | fits the team | 0.32 | 1.00 | 0.27 | 0.27 | 0.96 | 0.96 | 1.00 |
| 64 | 8 | too big | 0.20 | 1.00 | 0.19 | 0.20 | 0.31 | 0.27 | 0.59 |
| 128 | 16 | too big | 0.13 | 1.00 | 0.15 | 0.14 | 0.16 | 0.16 | 0.42 |

Growing the team in the biggest world (128 functions, capacity 16):

| team | solo (same compute) | random | owners | directory | pooled |
|---|---|---|---|---|---|
| 2 | 0.33 | 0.19 | 0.16 | 0.16 | 0.31 |
| 4 | 0.13 | 0.14 | 0.16 | 0.16 | 0.42 |
| 8 | 0.07 | 0.11 | 0.45 | 0.45 | 1.00 |
| 16 | 0.05 | 0.11 | 0.43 | 0.44 | 1.00 |

What it shows:

* **Three regimes.** When the world fits one head, organisation does not matter. When it is too big for
  one head but fits the team's heads together, a network with routing (owners, directory) does as well as
  perfect sharing (0.96–1.00) and three times better than one developer with the same compute (0.32–0.40),
  who keeps forgetting and re-learning (≈ 320 laws re-learned per sprint). When it is too big even for the
  team, everyone fails.
* **Routing is the network.** The same team asking at random does no better than working alone (0.27 at 64
  functions): a network without "who knows what" is not a network.
* **The coordination tax.** In the biggest world, 8 developers with owners finish 0.45 against 0.07 for one
  developer with their compute, but pooled memory finishes everything: the gap is the cost of asking (one
  question per foreign function per project). What to communicate, and when to delegate a sub-problem
  instead of asking for facts, is the open question for agent networks that this world measures.

## The town: CodeWorld you can watch

The same world, told as a city (`--theme town`, `worldseeds/codeworld/replay.py`): modules are
**workshops** (bakery, smithy, florist, mine, clinic, inn, shop, farm) with **machines** (functions such as
`bakery.spin_herb: wheat -> herb`), types are goods, a project is an **order**, a developer is an
**apprentice**, and the owner of a module is its **master**. A town has 8 workshops; bigger worlds are
several **districts** of 8 (`oak_bakery`, `river_inn`, ...), joined by roads.

* The town has a street map (`citymap.py`): districts of 12 x 12 tiles with a road every 6 tiles, two
  workshops per block, each with its door on a road. Apprentices walk the shortest way along the roads and
  remember each way they have walked (recorded in the replay, so the client draws the very route).
* `--walk`: studying a machine or asking someone means going there, one action per block of road (6 tiles)
  on the shortest route. Distance makes the cost of a question visible.
* `--batch`: one visit to a master explains every machine of theirs the order may need, not just the one
  asked about.

The standard town is 8 workshops x 6 machines (48 rules), apprentices who keep 12 rules in mind, teams of
4 (so the world fits the team but not one head). Share of orders delivered in steady state (sprints 5–8):

| world | questions | solo (same compute) | random | owners | directory | pooled |
|---|---|---|---|---|---|---|
| town, 48 machines, team of 4 | per machine | 0.46 | 0.50 | 1.00 | 1.00 | 1.00 |
| town, walking | per machine | 0.31 | 0.34 | 1.00 | 1.00 | 1.00 |
| 3 districts, 144 machines, team of 12 | per machine | 0.04 | 0.11 | 0.43 | 0.43 | 1.00 |
| 3 districts, walking | per machine | 0.04 | 0.05 | 0.15 | 0.15 | 1.00 |
| 3 districts | one visit | 0.04 | 0.14 | 1.00 | 1.00 | 1.00 |
| 3 districts, walking | one visit | 0.04 | 0.06 | 0.93 | 0.84 | 1.00 |

At town scale the network already doubles what one apprentice does with the same time. With three
districts, one head is hopeless (4%), a routed network that asks one machine at a time pays a heavy
coordination tax (43%, 15% once questions cost a walk), and asking for everything a master knows that the
order might need removes most of it (100%, 93% with walking). With walking, the roster that sends each
question to the *nearest* apprentice who knows does worse than asking the master (0.84 vs 0.93): the
nearest holder knows one rule, the master knows the whole workshop, so a one-visit question is better spent
on the master. What and how much to say per message is a first-class variable.

**Watching it.** `web/codeworld.html` (SeedVille Workshops) plays back sprints recorded by the engine, so
the picture is exactly what happened: an isometric city of workshops, apprentices walking the roads,
questions drawn between asker and master, what each one keeps in mind (and forgets), the orders and the
time left.

```bash
python scripts/build_codeworld_web.py      # writes web/replays/codeworld.json (7 recorded runs)
python -m http.server -d web 8000          # open http://localhost:8000/codeworld.html
python web/tools/isoart.py                 # (re)draws the isometric sprites, web/assets/iso.png
```

![SeedVille Workshops: one town, four masters](images/workshops_town.png)
![Three districts, twelve masters](images/workshops_districts.png)

## Running

```bash
python scripts/run_codeworld.py --out results/codeworld/core                 # heuristic, ~10 s
python scripts/run_codeworld.py --modules 32 --capacities 16 --team-sizes 2 4 8 16 --out results/codeworld/scale
python scripts/analyze_codeworld.py results/codeworld/core --costs
# the town (8 workshops x 6 machines) and three districts, walking, one-visit questions
python scripts/run_codeworld.py --theme town --walk --modules 8 --fns-per-module 6 --capacities 12 --team-sizes 4 --out results/codeworld/town
python scripts/run_codeworld.py --theme town --walk --batch --modules 24 --fns-per-module 6 --capacities 12 --team-sizes 12 \
    --projects-per-dev 3 --out results/codeworld/districts
# LLM developers (any OpenAI-compatible server)
WS_BASE_URL=http://localhost:8000/v1 WS_MODEL=qwen3-8b python scripts/run_codeworld.py --policy llm \
    --modules 8 --capacities 8 --team-sizes 4 --sprints 2 --projects-per-dev 2 --budget 100 --save-traces --out results/cw_llm
# Nibi
PILOT=1 bash slurm/submit_codeworld.sh && bash slurm/submit_codeworld.sh && sbatch slurm/codeworld_cpu.sh
```

## Next

* **Delegation**: ask an owner to solve a sub-chain ("from Order to Price, fitting these values") instead
  of asking for laws: fewer, richer messages; it tests whether agents can split work, not just share facts.
* **Teaching**: an explanation that lands in the asker's notebook (costs capacity) vs working memory only.
* **Specialists that drift**: modules change between releases (laws shift), owners leave, wrong
  explanations (correlated faulty owners) — the hive's provenance, audits and regional memory carry over.
* **Heterogeneous agents**: different models and capacities in one network; routing by competence.
* **Bigger and deeper worlds**: functions of two arguments, side effects (state), and modules whose
  behaviour depends on configuration from other modules (cross-domain dependencies beyond the type graph).

---

## 中文

**为什么做这个。** 目标是建一个 agent 网络：整体知识量超过任何单个 agent 能装下的量，为以后多 agent 并行、跨领域开发打基础。现有多 agent 基准测不了这件事：任务一个 agent 就装得下（等算力下单 agent 持平甚至更好），知识是给定的而不是学来的，协调任务和知识本身无关，共享记忆研究没有标准答案。CodeWorld 的设计保证四点：世界的知识量超过单个 agent 的容量；知识要靠实验学；项目必须同时用到多个模块（领域）的知识；所有东西都能精确打分。它要检验的命题是：**只有当世界大到一个 agent 装不下时，网络才会胜过等算力的单 agent，而且前提是网络知道"谁知道什么"。**

**世界。** 一个软件生态：模块（auth、billing、geo……）暴露函数，签名公开，行为隐藏（模 101 的 `a*x+b`，或在边界情况下换成另一组系数）。类型分层，每个函数升一层，所以程序是一条长度已知的函数链；能通过类型检查的链常有几十到几百条，通常跨多个模块。项目是功能需求：输入类型、输出类型和几个例子，例子保证只有一个程序（或与它等价的程序）符合。

**开发者与组织。** 每个开发者有容量有限的笔记本（记得住的规律数，最久没用的先忘）和每个冲刺的行动预算。研究一个函数要 8 个行动；问同事双方各花 1 个行动，同事讲解规律，讲解只在当前项目里有效。组织方式：单人（拿全队的预算）、单人无限记忆、各干各的、按模块负责人提问（owners）、目录（知道谁会什么）、随机问、共享笔记本（上限）。LLM 开发者通过工具使用同一个世界，写下的规律逐条对照真值打分。

**初步结果（规则开发者，CPU）：** 见上面两张表。三种情况：世界装得进一个人的脑子时，组织方式无所谓；装不进一个人、但装得进全队时，有路由的网络（owners、directory）达到 0.96–1.00，和完美共享一样，是等算力单人（0.32–0.40）的约三倍；随机提问的团队和单干一样差，没有"谁知道什么"的网络不算网络；世界大到全队都装不下时，所有人都失败。最大世界里 8 个人的网络完成 0.45，单人 0.07，共享记忆 1.00，中间的差距就是"沟通税"：该传什么、什么时候直接委派子问题而不是问事实，这正是 agent 网络要研究的问题。

**小镇：看得见的 CodeWorld。** 同一个世界换成城市的说法（`--theme town`）：模块是工坊（面包房、铁匠铺、花店、矿场、诊所、旅店、商店、农场），函数是工坊里的机器，类型是货物，项目是订单，开发者是学徒，模块负责人是师傅。一个镇 8 个工坊；更大的世界由多个 8 工坊的街区组成，用道路连起来。小镇有街道地图：每个街区 12×12 格、每 6 格一条路，学徒沿最短路线走，走过的路会记住（回放里记录了路线，界面画的就是这条路）。`--walk`：研究机器或问人都要走过去，最短路线上每 6 格路花 1 个行动；`--batch`：去一次师傅那里，师傅把订单可能用到的他的所有机器都讲了。标准小镇是 8 工坊 × 6 机器（48 条规律），每个学徒记得住 12 条，4 人一队：单人（等算力）完成 0.46（要走路时 0.31），有路由的网络 1.00。三个街区（144 台机器、12 人）：单人 0.04；一次只问一台机器的网络 0.43，要走路时只剩 0.15（沟通税）；一次问全的网络 1.00（要走路时 0.93）。要走路时，"问最近的知情者"的名册反而不如直接问师傅（0.84 对 0.93）：最近的人只懂一条规律，师傅懂整个工坊。每条消息说什么、说多少，是 agent 网络的核心变量。

**界面。** `web/codeworld.html`（SeedVille Workshops）回放引擎记录下来的冲刺，画面就是实际发生的事：等距视角的城市、沿路走动的学徒、提问的连线、每个人脑子里的规律（以及忘掉的）、订单和剩余时间。运行 `python scripts/build_codeworld_web.py` 生成回放，再 `python -m http.server -d web 8000` 打开 `codeworld.html`；`python web/tools/isoart.py` 重新绘制等距素材。

**下一步：** 委派子问题、把讲解写进笔记本的"教学"、会漂移的专家（版本更新、负责人离开、讲解出错）、异构 agent、两个参数的函数、带状态的函数、跨模块的配置依赖。
