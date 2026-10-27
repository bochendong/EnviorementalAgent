# netscale-smoke (qwen3-30b-a3b-fp8)

| design | dag/fixed-g1/n1 | dag/fixed-g1/n8 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|---|
| peers | 0.00 (0.12) | 0.00 (0.25) | 0.18 | 0 | 60.0 | 31.5 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, fixed-g1 family

| agents | problem | runs | solved | T (rounds) | T per seed | sharing | T_lb | b = T_lb/T | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 16 x 4 | 1 | 0.00 | - | x | none 1 | 130 | - | 130.0 | - | - | - |
| 8 | 16 x 4 | 1 | 0.00 | - | x | batch 1 | 17 | - | 26.0 | - | - | - |

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 14 | 0 | 4 | 0 | 36 | 0 | 0.0 | 28.0 | 1.00 |
| 8 | 121 | 0 | 67 | 0 | 108 | 1 | 63.0 | 92.0 | 0.47 |

T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on any team's rounds; b: efficiency against it. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 2 | 2 | 0.0 | 14 | 72.0 | submit 72, apply 68, tasks 33, status 2, inbox 0 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 3.0 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
