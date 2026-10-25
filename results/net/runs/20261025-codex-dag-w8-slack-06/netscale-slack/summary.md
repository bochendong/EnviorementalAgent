# netscale-pilot (Codex gpt-6.1-sol, high)

| design | dag/w8-g4/n8 | dag/w8-g4/n16 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|---|
| peers | 1.00 (1.00) | 1.00 (1.00) | 1.00 | 8780 | 0.0 | 0.0 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, w8-g4 family

| agents | problem | runs | solved | T (rounds) | T per seed | sharing | T_lb | b = T_lb/T | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 8 x 4 | 3 | 1.00 | 38.7 | 38 40 38 | broadcast 3 | 25 | 0.65 | 33.0 | 0.85 | - | - |
| 16 | 8 x 4 | 3 | 1.00 | 34.7 | 34 35 35 | broadcast 3 | 25 | 0.72 | 31.0 | 0.89 | - | - |

Bulk synchronous reading: T = T_bsp + S x L, T_bsp the fastest layer-by-layer schedule, S = depth + 1 supersteps (layers and the final task). The team's overhead per superstep L (median over runs of 2 or more agents, 6 runs): 2.3 rounds (quartiles 1.9-2.7); the scripted reference's: 1.4.

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 8 | 132 | 0 | 103 | 41 | 33 | 0 | 0.0 | 0.0 | 1.00 |
| 16 | 132 | 3 | 244 | 142 | 33 | 0 | 0.0 | 0.0 | 1.00 |

T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on any team's rounds; b: efficiency against it. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 6 | 0 | 0.0 | 28 | 33.0 | apply 132, wait 92, inbox 88, send 54, submit 33 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 0.0 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
