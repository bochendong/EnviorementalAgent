# netscale-screen (gpt-oss-120b)

| design | dag/fixed-g4/n1 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|
| peers | 0.50 (0.75) | 0.75 | 4634 | 13.5 | 0.0 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, fixed-g4 family

| agents | problem | runs | solved | T (rounds) | T per seed | sharing | T_lb | b = T_lb/T | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 16 x 4 | 2 | 0.50 | 421.0 | x 421 | none 2 | 325 | 0.77 | 325.0 | 0.77 | 1.00 | 1.00 |

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 336 | 0 | 25 | 0 | 62 | 0 | 0.0 | 13.5 | 1.00 |

T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on any team's rounds; b: efficiency against it. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 2 | 0 | 352.0 | 39 | 62.0 | apply 336, submit 62, tasks 25 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 0.0 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
