# compat (qwen3-8b)

| design | compat/math-decomposable | compat/math-sequential | compat/codeworld | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|---|---|
| blackboard | 0.00 (0.09) | 0.00 (0.15) | 0.00 (0.00) | 0.08 | 172 | 7.5 | 1.0 |
| centralized | 0.00 (0.14) | 0.00 (0.12) | 0.00 (0.12) | 0.13 | 311 | 6.4 | 1.2 |
| debate | 0.00 (0.06) | 0.00 (0.08) | 0.00 (0.00) | 0.05 | 258 | 1.3 | 1.7 |
| decentralized | 0.00 (0.03) | 0.00 (0.12) | 0.00 (0.02) | 0.06 | 165 | 1.3 | 0.8 |
| hybrid | 0.00 (0.12) | 0.00 (0.27) | 0.00 (0.08) | 0.16 | 384 | 8.2 | 1.3 |
| independent | 0.00 (0.00) | 0.00 (0.00) | 0.00 (0.00) | 0.00 | 432 | 5.5 | 4.2 |
| moa | 0.30 (0.40) | 0.20 (0.30) | 0.00 (0.07) | 0.26 | 466 | 3.9 | 5.2 |
| sas | 0.00 (0.00) | 0.20 (0.28) | 0.00 (0.00) | 0.09 | 712 | 4.8 | 0.0 |

Each cell: share of seeds solved (share of tasks done).

## Published findings

| case | design − baseline | published | difference [95% CI] | seeds | verdict |
|---|---|---|---|---|---|
| compat/math-decomposable | independent − sas | + | +0.000 [+0.000, +0.000] | 10 | inconclusive |
| compat/math-decomposable | centralized − sas | + | +0.139 [+0.069, +0.200] | 10 | reproduced |
| compat/math-decomposable | decentralized − sas | + | +0.031 [+0.000, +0.085] | 10 | inconclusive |
| compat/math-decomposable | hybrid − sas | + | +0.123 [+0.046, +0.200] | 10 | reproduced |
| compat/math-sequential | independent − sas | - | -0.275 [-0.550, -0.075] | 10 | reproduced |
| compat/math-sequential | centralized − sas | - | -0.150 [-0.417, +0.067] | 10 | inconclusive |
| compat/math-sequential | decentralized − sas | - | -0.150 [-0.417, +0.075] | 10 | inconclusive |
| compat/math-sequential | hybrid − sas | - | -0.008 [-0.283, +0.225] | 10 | inconclusive |

Sources:
- Kim et al. 2026, Towards a Science of Scaling Agent Systems, Sec. 4: on decomposable tasks (Finance-Agent) every multi-agent architecture beats the single agent (+57% to +81%); on sequential ones (PlanCraft) every one is worse (-39% to -70%)
