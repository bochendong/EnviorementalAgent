# Network scale: predictions for 16 and 32 agents

Written on 2026-10-22, before any run with more than 8 agents. The predictions come only from the two Codex pilots on the DAG provider:

- grain 1: `results/net/runs/20261022-codex-dag-pilot-02`
- grain 4: `results/net/runs/20261022-codex-dag-grain4-pilot-03`

Both use the fixed 16 x 4 problem, 1, 2, 4 and 8 agents, seeds 100-102, gpt-6.1-sol on high. The new runs check the predictions; they do not revise them.

## Two readings of the pilots

**Bulk synchronous (BSP).** A team's time is the lower bound plus a fixed loss per superstep:

T(N) = T_lb(N) + S x L

- T_lb = max(ceil(W / N), D) is the lower bound;
- S = depth + 1 = 5 supersteps (the four layers and the final task);
- L is the rounds lost per superstep to sharing and synchronising.

Over the 9 runs of 2-8 agents in each pilot, L does not depend on N and hardly on the grain:

| grain | L, median (quartiles) | the scripted reference's L |
|---|---|---|
| 1 | 3.6 (3.3-6.6) | 1.8 |
| 4 | 4.2 (3.5-6.7) | 2.2 |

The upper quartile comes from teams that settled on the shared store: 4 agents at grain 1 (seeds 100 and 102), and 8 agents at grain 4 (seed 102). Teams that batched their answers in messages lost 3-4.5 rounds per superstep.

BSP says that above 8 agents the work term stops shrinking. At 16 agents and beyond, T_lb is the span D, so T levels off.

**Universal Scalability Law (USL).** USL is fitted to the speed-ups T(1) / T(N):

| grain | sigma | kappa |
|---|---|---|
| 1 | 0.17 | 0 |
| 4 | 0.08 | 0.0001 |

Its speed-up keeps growing past 8 agents, because the fit has no term for the span.

## Predictions

T is in lockstep rounds, as the mean over seeds 100-102.

| grain | agents | lower bound | scripted reference | BSP: T (quartile range of L) | BSP speed-up | USL: T | USL speed-up |
|---|---|---|---|---|---|---|---|
| 1 | 16 | 10 | 18 | 28 (26-43) | 4.8 | 30 | 4.5 |
| 1 | 32 | 10 | 16 | 28 (26-43) | 4.8 | 27 | 5.1 |
| 4 | 16 | 25 | 33 | 46 (42-58) | 7.2 | 46 | 7.2 |
| 4 | 32 | 25 | 31 | 46 (42-58) | 7.2 | 37 | 8.9 |

Grain 4 with 32 agents tells the readings apart. Three outcomes are possible:

1. **T near 46**: BSP holds. The span caps the team, and the cost of coordination is a fixed loss per superstep, independent of the team's size.
2. **T near 37**: USL's growth holds. 32 agents found time BSP does not see, for example by overlapping supersteps.
3. **T well above 58, or T(32) > T(16)**: neither reading holds. The loss per superstep grows with the team (reading 31 agents' messages and agreeing on who does what), and there is a size beyond which more agents are slower (kappa > 0).

At 16 agents the two readings agree, so those runs test BSP's level and not the choice between the readings.

## How to check

```bash
python -m netagents.codex_netscale --suite netscale --sizes 16 32 --grains 4 --seeds 100 101 102 \
  --out results/net/runs/<run>/netscale
python -m netagents.netscale results/net/runs/<run>/netscale
```

Calls are not the limit. Each agent may take three times its share of the work plus every layer's applies and sharing: 168 calls per agent at 16 agents and 138 at 32. The pilots used at most 42% of their calls.

## Result at 32 agents (2026-10-23)

`results/net/runs/20261022-codex-dag-n32-grain4-04`, grain 4, seeds 100-102: T = 39, 38, 37 (mean 38). Every node's whole four-step apply chain was audited.

- BSP predicted 46 (42-58): **off by 8, below even the lower end of its range. The prediction failed.**
- USL predicted 37: off by 1.
- T(32) = 38 is far from the third outcome (well above 58).

Speed-up 8.68, b = 0.658. The 32 teams kept every answer in the store (64 writes each) and also sent messages (134-182 per run), and about half the agents waited at any time (7 waits per agent).

### Why BSP missed

The predictions above took the Brent bound max(W / N, D) as the base of T = base + S x L. Below the span, that bound spreads the final task and the layers' remainders over the whole team. A team that finishes each layer before the next cannot do that: the fastest such schedule (`netagents/scaling.py` `layered_bound`) takes ceil(width / N) tasks' time per layer and the final task alone:

| agents | 2 | 4 | 8 | 16 | 32 |
|---|---|---|---|---|---|
| Brent bound, grain 4 | 163 | 82 | 41 | 25 | 25 |
| layered schedule, grain 4 | 165 | 85 | 45 | 25 | 25 |

At 8 agents the base was 4 rounds too low, and those 4 rounds went into L. With the layered schedule as the base, the 2-8-agent runs give L = 3.4 per superstep (quartiles 2.9-6.1), not 4.2. That would have predicted 42 for 32 agents: closer, but still 4 above what was observed. At 32 agents L was 2.6 (2.4-2.8).

**This correction was made after seeing the 32-agent result; it is not a confirmed prediction.** What stands is that the pre-registered BSP prediction failed. The corrected reading has to earn its place on runs not yet made.

## Second prediction: 16 agents, grain 4 (2026-10-23, before any 16-agent run)

16 agents on a 16-wide problem is the boundary case: one task per agent and layer, and (unlike 32) no idle agents to take on the talking.

| reading | how | T at 16 |
|---|---|---|
| BSP, layered base | 25 + 5 x L, L = 3.0 (median of all 12 runs with 2-32 agents; quartiles 2.8-5.1) | **40** (39-50) |
| USL | refitted with the 32-agent runs (sigma = 0.08, kappa = 0.0002) | **46** |

Outcomes:

1. **T about 39-42**: the layered BSP reading holds. The loss per superstep is a property of the team's protocol (about 3 rounds, against the scripted reference's 1.2-1.6), not of its size.
2. **T about 45-47**: USL is better. Something grows with the team that BSP does not have.
3. **T well above 50**: neither. Without idle agents, 16 agents lose more per superstep than 32 do, so slack absorbs coordination.

A run whose team settles on the store alone is reported as such (`sharing`): in the pilots, those teams lost 5-7 rounds per superstep.

## Result at 16 agents (2026-10-23)

`results/net/runs/20261022-codex-dag-n16-grain4-05`, grain 4, seeds 100-102: T = 44, 58, 50 (mean 50.7). Every node's whole four-step apply chain was audited.

- Layered BSP predicted 40 (39-50): **failed**. The mean lies above the whole range.
- USL predicted 46: off by 4.7.
- The third outcome ("well above 50") did not clearly happen either.

So neither reading predicted 16 well. One thing holds on every seed: **32 agents were faster than 16** (39 against 44, 38 against 58, 37 against 50), although both have the same lower bound (25) and 16 already have one agent per task.

## Where the time went (from the traces; `python -m netagents.netscale` "Where the time went")

The time splits into two parts:

- **the layers' handoffs**: rounds a layer took beyond the fastest it could go;
- **the join**: the final task, which needs all 16 answers of the last layer.

| agents (grain 4) | rounds lost per layer, layers 1-3 | join: rounds lost | join: store reads by its solver |
|---|---|---|---|
| 2 | 7.0, 3.0, 3.0 | 1, 4, 1 | 0 |
| 4 | 3.3, 3.0, 6.0 | 3, 3, 1 | 0 |
| 8 | 4.3, 3.3, 7.3 | 2, 2, 3 | 0 |
| 16 | 5.3, 4.7, 5.3 | 2, 16, 7 | 0, 15, 6 |
| 32 | 2.7, 3.0, 2.3 | 2, 2, 3 | 0 |

Two mechanisms show:

1. **A second crew hides the handoff.** Up to 16 agents, a layer loses 3-7 rounds (median 4.5): the agent that hands an answer on is the one that must then read the next layer's inputs and start. The 32-agent teams split into two crews at once ("a0-a15 handle L0 and L2; a16-a31 handle L1 and L3"), so one crew reads and waits while the other computes. Their layers lost 2.3-3.0 rounds, against the scripted reference's 1.2-1.6.
2. **The join costs what its solver's reading costs.** Two of the three 16-agent teams left the final task to an agent that pulled the 16 answers from the store one by one: 15 and 6 store reads, 16 and 7 rounds lost. Everywhere else the join lost 1-4 rounds.

Together these account for the 16-32 gap. Per layer the gap is about 2.4 rounds over three layers, about 7; at the join, 8.3 against 2.3, about 6. That makes about 13, against an observed 12.7.

**A critical-path reading** (fitted post hoc on these 15 runs; it is a hypothesis, not a result):

T = T_bsp + e0 + lambda x (depth - 1) + j

- T_bsp is the fastest layer-by-layer schedule;
- e0, about 2, is layer 0's start;
- lambda is the handoff loss per later layer: about 4.5 with one agent per task, about 2.7 with two;
- j is the join's loss: about 2, plus one round per answer its solver pulls from the store.

It gives 182, 102, 62, 42 and 37 rounds for 2, 4, 8, 16 and 32 agents, against observed 188, 106, 64, 51 and 38. The 16-agent runs that pulled the join from the store are the ones it does not cover.

## Third prediction: an 8-wide problem (2026-10-23, before any run of it)

Suite `netscale-slack`: width 8, depth 4, grain 4, 4, 8, 12 and 16 agents, seeds 100-102. The shape is new, so this is out of sample for the reading above. Its lower bound and the scripted reference are:

| agents | 4 | 8 | 12 | 16 |
|---|---|---|---|---|
| T_bsp (fastest layer-by-layer) | 45 | 25 | 25 | 25 |
| scripted reference | 53 | 33 | 31 | 31 |
| predicted T (critical-path reading) | 62 | 42 | (exploratory: between) | 37 |

The primary claim concerns the handoff loss, measured per layer from the traces, which is less sensitive to how a team does its join: **16 agents (two per task) lose less per layer than 8 (one per task), about 2.7 against 4.5 rounds, and T(16) < T(8) on every seed.**

- If the 16-agent teams do not form a second crew, or form one and still lose as much per layer as 8 agents do, the crew mechanism is wrong.
- Secondary: a join solved by pulling answers from the store loses about one round per pulled answer.

```bash
python -m netagents.codex_netscale --suite netscale-slack --out results/net/runs/<run>/netscale-slack
```

## Result on the 8-wide problem (2026-10-25)

`results/net/runs/20261025-codex-dag-w8-slack-06`: 8 and 16 agents, seeds 100-102; 4 and 12 agents were not run. Every node's whole four-step apply chain was audited.

| seed | T, 8 agents | T, 16 agents | loss per layer, 8 | loss per layer, 16 | join lost, 8 / 16 |
|---|---|---|---|---|---|
| 100 | 38 | 34 | 3.3 | 2.0 | 2 / 2 |
| 101 | 40 | 35 | 3.7 | 2.3 | 3 / 2 |
| 102 | 38 | 35 | 3.3 | 2.3 | 2 / 2 |

- **The primary prediction held on every seed.** 16 agents lost less per layer than 8 (mean 2.2 against 3.4), and T(16) < T(8) (34.7 against 38.7).
- **The numbers did not.** The prediction was T = 42 and 37, with losses of 4.5 and 2.7. Both teams were about 3 rounds faster, and both losses were smaller.
- **The 16-agent teams formed two crews themselves, out of sample.** On all three seeds, a0-a7 did layers 0 and 2 and a8-a15 did layers 1 and 3, as the tasks each one actually had accepted show (`coordination-evidence.json`). The 8-agent teams worked by column.
- **The secondary prediction (store pulls at the join) had nothing to test.** No join pulled from the store.

Exploratory, not predicted: the loss per layer grows with the width. With one crew, it was 3.4 at width 8 against 4.1-5.1 at width 16; with two crews, 2.2 against 2.7. Each layer's handoff has more answers to pass on, and more messages to read, when the layer is wider.

What this does and does not show:

- Two shapes, six seeds: wherever there were twice as many agents as tasks in a layer, the team split into two crews and lost less per layer.
- That is an association that replicated out of sample. It is not yet a cause: the teams that formed crews also changed how they shared answers.
- `peers-columns` (below) is the causal test.

## Fourth prediction: two interventions (2026-10-25, before any run of them)

Suite `netscale-intervene`: the fixed 16 x 4 problem, grain 4, seeds 100-102, the same cases as the plain peers runs above, so that each run pairs with its plain run seed by seed. Each intervention is the peers design with one rule added (`netagents/designs.py`); nothing else changes.

**`peers-columns` on 32 agents: no second crew.** The assignment is fixed in advance: agent aK does column K in every layer, a0 also does the final task, and agents with no column take no task. This is the assignment the plain 16-agent teams chose themselves, with 16 idle agents added. If the second crew is what hid the handoff:

- each later layer loses about as much as at 16 agents (4.7-5.3 rounds), not 2.3-3.0 as in the plain 32-agent runs;
- T is about 25 + 2 + 3 x 5 + 2 = 44 (up to about 58 if the join is pulled from the store), against 37-39 for the plain 32-agent runs, and is longer than its plain run on every seed.

If the layers still lose about 2.7 rounds and T stays near 38, the idle agents help in some other way, and the crew mechanism is wrong.

**`peers-msgjoin` on 16 agents: the join by messages.** Every last-layer answer is sent to everyone at once, and the final task's solver reads its inbox rather than the store. If the join costs what its solver's reading costs:

- the join loses 1-4 rounds on every seed, with no more than a few store reads by its solver (plain: 2, 16 and 7 rounds; 0, 15 and 6 reads);
- the layers are unchanged (about 5 rounds lost each), so T is about 25 + 2 + 3 x 5 + 2 = 44, against 44, 58 and 50 for the plain runs.

```bash
python -m netagents.codex_netscale --suite netscale-intervene --design peers-columns --sizes 32 --out results/net/runs/<run>/columns
python -m netagents.codex_netscale --suite netscale-intervene --design peers-msgjoin --sizes 16 --out results/net/runs/<run>/msgjoin
```

## Result of `peers-columns` on 32 agents (2026-10-25)

`results/net/runs/20261025-codex-columns-n32-grain4-07`, seeds 100-102, paired with the plain 32-agent runs. The rule was obeyed throughout: a0-a15 did every task of their own column, a0 did the final task, and a16-a31 only waited. No second crew formed.

| seed | plain 32: T | columns 32: T | plain: loss per layer | columns: loss per layer | join lost, plain / columns | join store reads, plain / columns |
|---|---|---|---|---|---|---|
| 100 | 39 | 56 | 3.0 | 4.7 | 2 / 16 | 0 / 15 |
| 101 | 38 | 56 | 2.7 | 4.7 | 2 / 16 | 0 / 15 |
| 102 | 37 | 49 | 2.3 | 6.3 | 3 / 4 | 0 / 3 |

- **The predicted direction held on every seed.** Without a second crew, each later layer lost 5.2 rounds on average instead of 2.7 (predicted 4.7-5.3; two seeds at its lower edge, one above it). T rose by 12-18 rounds.
- **T was 56, 56, 49, not 44.** The prediction allowed up to about 58 if the join was pulled from the store, and it was: on two seeds a0 read 15 answers from the store one by one and the join lost 16 rounds. On the third it read 3 and lost 4. That is the one-round-per-pulled-answer rule of the third prediction.
- **Barred from working, 16 idle agents bought nothing.** The columns runs (56, 56, 49) are where the plain 16-agent runs were (44, 58, 50).
- **What it does not isolate.** The rule also changed how the teams shared answers. They sent far fewer messages (12-55 against 134-182) and read the store more (64-102 reads against 58-127). The comparison is with earlier runs, not a concurrent random assignment.

## 中文摘要

16 人和 32 人还没跑之前，先用两轮试跑的结果写下预测。

- **整体同步并行（BSP）读法**：T = 下界 + 5 × L，L 是每层同步多花的轮数。
  - 实测 L 约为 4（grain 1 是 3.6，grain 4 是 4.2），与人数无关；脚本团队约为 2。
  - 选了共享存储的团队 L 更大。
  - 预测：16 人以上时下界变成关键路径，T 停在约 46 轮（grain 4）。
- **通用扩展定律（USL）读法**：拟合出的加速曲线还会继续上升，预测 32 人约 37 轮。
- **结果有三种可能**：
  - 32 人约 46 轮：BSP 成立，协调开销是每层固定的；
  - 约 37 轮：USL 成立；
  - 远超 58 轮，或者 32 人比 16 人慢：每层开销随人数增长，存在"再加人就变慢"的规模。

  第三种最可能写成论文的核心结论。

**32 人的结果（10 月 23 日）**：T = 39、38、37，平均 38 轮。

- BSP 预测是 46 轮，偏了 8 轮，比预测区间的下限还低，**预测失败**；通用扩展定律预测 37 轮，只差 1 轮。
- 原因：BSP 用了 Brent 下界做基线。人少的时候，这个下界把汇总题和每层的零头摊给了全队，实际上做不到；8 人时少算了 4 轮，这 4 轮被错误地算进了每层开销 L。
- 改用"逐层完成的最快日程"做基线后，2 到 8 人的 L 是 3.4，32 人是 2.6。这个修正是看到结果之后才做的，不算被证实的预测。

**16 人的新预测（跑之前写下）**：

- 修正后的 BSP 读法：40 轮（区间 39 到 50）；
- 通用扩展定律重新拟合：46 轮；
- 两者相差 6 轮，16 人可以区分它们。
- 如果远超 50 轮，说明没有空闲成员时协调开销更大，即"空闲成员吸收了协调开销"。

**16 人的结果（10 月 23 日）**：T = 44、58、50，平均 50.7。

- 修正后的 BSP 预测是 40 轮，**失败**；通用扩展定律预测 46 轮，差 4.7 轮。两者都没有预测好。
- 每个种子上 32 人都比 16 人快，尽管两者的下界都是 25，而且 16 人已经是每题一人。

**轨迹拆解出两个机制**：

- **第二班人能把交接藏起来。** 16 人及以下，每层交接多花 3 到 7 轮。32 人一开始就自发分成两班（一班做第 0、2 层，另一班做第 1、3 层），一班计算时另一班在读数据、等待，所以每层只多花 2.3 到 3 轮。
- **汇总题的成本取决于收集答案的方式。** 16 人的三个种子里有两个，汇总题由一个人从共享存储里逐个读取答案，分别读了 15 次和 6 次，多花了 16 轮和 7 轮。

两项合起来，正好解释了 16 人和 32 人相差的约 13 轮。

**第三个预测（宽 8 的新题，跑之前写下）**：

- 8 人（每题一人）每层多花约 4.5 轮；16 人（每题两人）约 2.7 轮。
- T(16) < T(8)，并且每个种子都如此。
- 预测的 T：4 人 62 轮，8 人 42 轮，16 人 37 轮。

**第四个预测：两个干预实验（10 月 25 日，跑之前写下）**：

- **不准分班（32 人，`peers-columns`）**：
  - 设置：每人固定负责一列，a0 兼做汇总题，没有列的人不接任何题。这正是 16 人团队自己选的分工，只是多了 16 个闲人。
  - 预测：如果"第二班藏延迟"成立，每层交接损失回到约 5 轮，T 约 44 轮，每个种子都比不加干预的 32 人（37 到 39 轮）慢。
  - 如果仍是约 2.7 轮、T 约 38 轮，分班这个机制就是错的。
- **汇总改用消息（16 人，`peers-msgjoin`）**：
  - 设置：最后一层的答案一完成就发给所有人，汇总者从收件箱读，不从存储逐个读。
  - 预测：每个种子的汇总损失都在 1 到 4 轮；每层交接不变，T 约 44 轮（不加干预时是 44、58、50）。

**宽 8 的结果（10 月 25 日）**：

- **主要预测在每个种子上都成立**：16 人每层交接损失低于 8 人（平均 2.2 对 3.4 轮），而且 T(16) < T(8)（34.7 对 38.7）。
- **具体数值没有命中**：两组都比预测快了约 3 轮。
- **16 人在新形状上又自发分成了两班**（a0 到 a7 做第 0、2 层，a8 到 a15 做第 1、3 层），实际接受的任务也印证了这一点。
- **事后观察**：题目越宽，每层交接损失越大。

结论：分班与交接损失降低之间的关联，在样本外得到了复现；因果检验要靠不准分班的 `peers-columns`。

**不准分班的干预结果（32 人，10 月 25 日）**：

- **规则被完整遵守**：a16 到 a31 只在等待，没有形成第二班。
- **预测方向在每个种子上都成立**：每层交接损失从 2.7 轮升到 5.2 轮，T 从 38 轮升到 49 到 56 轮。
- **汇总题**：有两个种子由 a0 从存储逐个读了 15 个答案，汇总多花 16 轮；第三个种子读 3 次，多花 4 轮。正好符合"每逐个读一个答案多花约一轮"。
- **多出来的 16 人被禁止干活后，毫无帮助**：结果和普通 16 人相当。
- **局限**：这条规则同时让团队少发消息、多用存储；对照组是之前的运行，不是同期随机分组。

