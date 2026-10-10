# The ladder: from the tutorial to the full town

Qwen3-8B passes the two-machine tutorial ([diagnostic](tutorial-diagnostic.md), job 23645311: 9/9 orders)
but barely acts in the full town (jobs 23602469 and 23612422). The jump between them adds everything at
once: 48 machines instead of 2, a dozen chains per order instead of one, edge-case rules, walking, money,
goals, and 40 actions each (one study costs 8). The ladder (`worldseeds/codeworld/ladder.py`) adds one
difficulty per level and stops at the first level a model cannot climb, so a failure points at its cause.

| level | name | what is new | players | machines | pass |
|---|---|---|---|---|---|
| 1 | two | the tutorial without its gates: two machines, one chain | 1 | 2 | all orders |
| 2 | choose | four chains fit the goods; the order's examples single one out | 1 | 4 | all orders |
| 3 | edges | every rule has an edge case (a different rule on multiples of 2, 3 or 5) | 1 | 4 | all orders |
| 4 | masters | two players; each may only use its own workshop's machines and must learn them; every order needs both: ask | 2 | 4 | all orders |
| 5 | town | eight workshops of three machines, orders of 2-3 machines; the machines that fit an order are listed with it | 4 | 24 | half the orders |
| 6 | full | the town of the experiments: 48 machines, walking, money, the festival and the prize | 4 | 48 | half the orders |

Three seeds per level; a level is climbed when two of three pass. Each level's prompt says how to work
("run on 0, 1, 2; the output at 0 is b ..."), like the tutorial, but no tool forces a step: levels measure
what the model does, not what the tools make it do. The tutorial's observation-grounded `remember`, stop
reasons and recording are reused as they are.

```bash
python scripts/run_ladder.py --out results/ladder/try1                  # stop at the first failing level
python scripts/run_ladder.py --levels 4 5 6 --no-stop --out results/ladder/upper
sbatch slurm/town_ladder.sh                                              # Nibi, same recording as the tutorial
LADDER_ARGS="--levels 3 4 5 6 --no-stop" sbatch slurm/town_ladder.sh
```

Outputs as for the tutorial (`events.jsonl`, `traces.jsonl`, `replay.json`, `codeworld.jsonl`) plus
`summary.json`: per level, seeds passed and whether it was climbed. Rows record the level, statuses, tool
counts, rules noted and how many were right, and the number of chains per order.

Ending statuses distinguish `completed` (delivered orders, with no handovers), `orders_transferred`
(no work left after handing over one or more orders), and `no_orders` (no orders and no deliveries).
The per-player `done` and `handed_over` counts remain separate; passing always uses actual deliveries.
Level 6 uses 100 actions and two orders per player, plus a relevant-machine hint; the old full-town pilot
used 40 actions and one order per player. These are different conditions despite sharing the larger town.

## First recorded Qwen run

[Nibi job 23670383](../results/town_ladder/23670383/README.md) completed normally but stopped at level 1:
zero of three seeds passed. The players repeatedly proposed incorrect affine coefficients or collected
the same observations again, reaching the turn or action limit before any computation/submission.
This localizes the observed failure to rule inference, before chain selection or team communication.

Level 1 also changes the coefficient distribution relative to the earlier tutorial: `tiny_world` used
`a=2..5, b=1..7`, whereas the ladder uses the general universe generator and its observations wrap modulo
101. Prompts and notebook capacities differ too. The tutorial-versus-level-1 comparison therefore does
not isolate removal of the tutorial's workflow gates. Likewise, the levels are diagnostic stages rather
than a strict cumulative single-factor design: level 4 returns to affine rules after level 3's edge cases,
and upper levels change budgets, order counts and hints along with scale.

---

## 中文

两台机器的入门试点（23645311）Qwen3-8B 全部通过，但在完整小镇（23602469、23612422）里几乎不动：两者之间一下子加了太多东西（48 台机器、每单十几条候选链、边界规则、走路、钱、目标、每人只有 40 行动而研究一次就要 8）。阶梯（`ladder.py`）每一级只加一种难度，在第一个过不去的级别停下，这样失败就能指出原因：

1. 两台机器、一条链（入门试点去掉强制步骤）
2. 四条链都符合货物类型，要用订单的例子选出正确的那条
3. 同上，但每条规律都有边界情况
4. 两名玩家，各自只能用自己工坊的机器、要自己学；每单都需要两个工坊：去问对方师傅
5. 八个工坊各三台机器、四名玩家、两到三步的订单；订单会列出相关机器
6. 实验用的完整小镇：48 台机器、走路、钱、丰收节和大奖

每级三个种子，两个通过才能上一级。提示里写明做法，但工具不强制任何步骤：测的是模型自己会怎么做。`sbatch slurm/town_ladder.sh` 在 Nibi 上运行，记录方式与入门试点相同，另有 `summary.json` 汇总每一级的结果。
