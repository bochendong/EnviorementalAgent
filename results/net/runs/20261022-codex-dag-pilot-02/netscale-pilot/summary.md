# netscale-pilot (Codex gpt-6.1-sol, high)

| design | dag/fixed-g1/n2 | dag/fixed-g1/n1 | dag/fixed-g1/n8 | dag/fixed-g1/n4 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|---|---|---|
| peers | 1.00 (1.00) | 1.00 (1.00) | 1.00 (1.00) | 1.00 (1.00) | 1.00 | 5112 | 0.7 | 1.4 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, fixed-g1 family

| agents | problem | runs | solved | T (rounds) | T_lb | b = T_lb/T | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 16 x 4 | 3 | 1.00 | 135.0 | 130 | 0.96 | 130.0 | 0.96 | 1.00 | 1.00 |
| 2 | 16 x 4 | 3 | 1.00 | 83.7 | 65 | 0.78 | 101.3 | 1.21 | 1.26 | 1.61 |
| 4 | 16 x 4 | 3 | 1.00 | 70.7 | 33 | 0.47 | 54.0 | 0.76 | 0.79 | 1.91 |
| 8 | 16 x 4 | 3 | 1.00 | 33.7 | 17 | 0.50 | 30.0 | 0.89 | 0.93 | 4.01 |

Universal Scalability Law fit to the speed-ups: sigma = 0.170, kappa = 0.0000 (RMSE 0.41); no peak (kappa = 0).

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 65 | 0 | 5 | 0 | 65 | 0 | 0.0 | 0.0 | 1.00 |
| 2 | 66 | 0 | 31 | 4 | 66 | 0 | 1.0 | 0.7 | 1.00 |
| 4 | 70 | 70 | 64 | 12 | 67 | 0 | 4.7 | 2.0 | 1.00 |
| 8 | 65 | 0 | 109 | 30 | 65 | 0 | 0.0 | 0.0 | 1.00 |

T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on any team's rounds; b: efficiency against it. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 12 | 0 | 0.0 | 0 | 65.7 | apply 66, submit 66, tasks 18, send 18, inbox 16 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 0.0 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
