# netscale-pilot (Codex gpt-6.1-sol, high)

| design | dag/fixed/n2 | dag/fixed/n1 | dag/fixed/n8 | dag/fixed/n4 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|---|---|---|
| peers | 1.00 (1.00) | 1.00 (1.00) | 1.00 (1.00) | 1.00 (1.00) | 1.00 | 4545 | 3.2 | 0.4 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, fixed family

| agents | problem | runs | solved | T (rounds) | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|
| 1 | 16 x 4 | 3 | 1.00 | 81.7 | 129.0 | 1.58 | 1.00 | 1.00 |
| 2 | 16 x 4 | 3 | 1.00 | 76.3 | 160.0 | 2.10 | 1.33 | 1.07 |
| 4 | 16 x 4 | 3 | 1.00 | 51.0 | 88.0 | 1.73 | 1.09 | 1.60 |
| 8 | 16 x 4 | 3 | 1.00 | 38.0 | 52.0 | 1.37 | 0.87 | 2.15 |

Universal Scalability Law fit to the speed-ups: sigma = 0.435, kappa = 0.0000 (RMSE 0.20); no peak (kappa = 0).

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 0 | 5 | 0 | 66 | 0 | 0.0 | 1.3 | 1.00 |
| 2 | 49 | 0 | 32 | 5 | 67 | 0 | 0.0 | 2.0 | 1.00 |
| 4 | 63 | 0 | 69 | 4 | 68 | 0 | 0.3 | 2.7 | 1.00 |
| 8 | 62 | 7 | 155 | 8 | 72 | 0 | 1.3 | 7.0 | 1.00 |

T: lockstep rounds until the final task was accepted, over solved runs. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 12 | 0 | 0.0 | 0 | 68.2 | submit 68, evaluate 45, tasks 26, inbox 21, send 18 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 30.0 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
