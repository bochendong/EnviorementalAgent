# netscale-smoke (qwen3-8b)

| design | dag/fixed-g1/n8 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|
| peers | 0.00 (0.81) | 0.81 | 12644 | 289.0 | 153.0 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, fixed-g1 family

| agents | problem | runs | solved | T (rounds) | T per seed | sharing | T_lb | b = T_lb/T | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 16 x 4 | 1 | 0.00 | - | x | batch 1 | 17 | - | 26.0 | - | - | - |

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 8 | 347 | 18 | 181 | 0 | 342 | 0 | 153.0 | 289.0 | 1.00 |

T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on any team's rounds; b: efficiency against it. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 1 | 0 | 305.0 | 39 | 342.0 | apply 347, submit 342, tasks 140, send 20, get 17 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 0.0 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
