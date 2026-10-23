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
