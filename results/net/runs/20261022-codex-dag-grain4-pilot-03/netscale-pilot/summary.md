# netscale-pilot (Codex gpt-6.1-sol, high)

| design | dag/fixed-g4/n2 | dag/fixed-g4/n1 | dag/fixed-g4/n4 | dag/fixed-g4/n8 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|---|---|---|
| peers | 1.00 (1.00) | 1.00 (1.00) | 1.00 (1.00) | 1.00 (1.00) | 1.00 | 12488 | 0.3 | 1.7 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, fixed-g4 family

| agents | problem | runs | solved | T (rounds) | T per seed | sharing | T_lb | b = T_lb/T | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 16 x 4 | 3 | 1.00 | 330.0 | 330 330 330 | none 3 | 325 | 0.98 | 325.0 | 0.98 | 1.00 | 1.00 |
| 2 | 16 x 4 | 3 | 1.00 | 188.0 | 199 180 185 | batch 3 | 163 | 0.87 | 173.0 | 0.92 | 0.93 | 1.76 |
| 4 | 16 x 4 | 3 | 1.00 | 106.0 | 100 99 119 | batch 3 | 82 | 0.77 | 93.0 | 0.88 | 0.89 | 3.11 |
| 8 | 16 x 4 | 3 | 1.00 | 64.3 | 62 59 72 | batch 2, store 1 | 41 | 0.64 | 53.0 | 0.82 | 0.84 | 5.13 |

Universal Scalability Law fit to the speed-ups: sigma = 0.080, kappa = 0.0001 (RMSE 0.07); the speed-up peaks near N* = 90.4.

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 260 | 0 | 5 | 0 | 65 | 0 | 0.0 | 0.0 | 1.00 |
| 2 | 264 | 0 | 37 | 9 | 66 | 0 | 4.0 | 0.7 | 1.00 |
| 4 | 263 | 0 | 72 | 24 | 66 | 0 | 2.7 | 0.7 | 1.00 |
| 8 | 260 | 41 | 105 | 43 | 65 | 0 | 0.0 | 0.0 | 1.00 |

T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on any team's rounds; b: efficiency against it. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 12 | 0 | 0.0 | 0 | 65.3 | apply 262, submit 65, wait 19, send 19, tasks 18 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 0.0 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
