# netscale-pilot (Codex gpt-6.1-sol, high)

| design | dag/fixed-g4/n32 | mean completion | tokens (k) | wrong subm. | dup. work |
|---|---|---|---|---|---|
| peers | 1.00 (1.00) | 1.00 | 30272 | 0.0 | 0.0 |

Each cell: share of seeds solved (share of tasks done).

## Network scale

### peers, fixed-g4 family

| agents | problem | runs | solved | T (rounds) | T per seed | sharing | T_lb | b = T_lb/T | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 32 | 16 x 4 | 3 | 1.00 | 38.0 | 39 38 37 | broadcast 3 | 25 | 0.66 | 31.0 | 0.82 | - | - |

Bulk synchronous reading: T = T_lb + S x L, S = depth + 1 supersteps (layers and the final task). The team's overhead per superstep L (median over runs of 2 or more agents, 3 runs): 2.6 rounds (quartiles 2.4-2.8); the scripted reference's: 1.2.

Predicted from that L (to be checked by runs not yet made): N = 16: 38 rounds.

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 32 | 260 | 167 | 500 | 224 | 65 | 0 | 0.0 | 0.0 | 1.00 |

T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on any team's rounds; b: efficiency against it. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.

## Diagnostics

| design | runs | runs with LLM errors | context trims | peak context (k tok.) | submissions | most used operations |
|---|---|---|---|---|---|---|
| peers | 3 | 0 | 0.0 | 0 | 65.0 | apply 260, inbox 226, wait 224, send 157, tasks 117 |

Operations: mean calls per run.

## Where submitted answers came from

| design | submissions with no source | from an unshared teammate result | from a faulty result | checks | report score |
|---|---|---|---|---|---|
| peers | 0.0 | 0.0 | 0.0 | 0.0 | - |

Means per run. A value with no source was guessed or assumed: it appears in no tool result, message, post or store entry the submitter saw, nor in any teammate's results.
