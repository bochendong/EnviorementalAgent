# netscale-pilot (qwen3-8b)

| design | dag/fixed/n1 | dag/fixed/n2 | dag/fixed/n4 | dag/fixed/n8 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|---|---|---|
| peers | 0.00 (0.00) | 0.00 (0.18) | 0.00 (0.06) | 0.00 (0.05) | 0.08 | 9086 | 26.3 | 2.5 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, fixed family

| agents | problem | runs | solved | T (rounds) | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|
| 1 | 16 x 4 | 3 | 0.00 | - | 129.0 | - | - | - |
| 2 | 16 x 4 | 3 | 0.00 | - | 160.0 | - | - | - |
| 4 | 16 x 4 | 3 | 0.00 | - | 88.0 | - | - | - |
| 8 | 16 x 4 | 1 | 0.00 | - | 52.0 | - | - | - |

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.0 | 0.00 |
| 2 | 557 | 228 | 37 | 0 | 79 | 0 | 8.3 | 67.7 | 0.75 |
| 4 | 719 | 0 | 17 | 0 | 23 | 0 | 0.0 | 19.7 | 0.39 |
| 8 | 880 | 1 | 27 | 0 | 4 | 0 | 0.0 | 1.0 | 0.33 |

T: lockstep rounds until the final task was accepted, over solved runs. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 10 | 10 | 0.5 | 0 | 31.2 | sequence 439, get 58, submit 31, evaluate 16, rsolve 14 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 0.5 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
