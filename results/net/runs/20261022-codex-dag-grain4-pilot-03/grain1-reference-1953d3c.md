Grain 1 observations: source cb69623. References and sharing labels: source 1953d3c. Original files are unchanged.

## Network scale

### peers, fixed-g1 family

| agents | problem | runs | solved | T (rounds) | T per seed | sharing | T_lb | b = T_lb/T | T_ref | a = T_ref/T | eta = a(N)/a(1) | speed-up |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 16 x 4 | 3 | 1.00 | 135.0 | 135 135 135 | none 3 | 130 | 0.96 | 130.0 | 0.96 | 1.00 | 1.00 |
| 2 | 16 x 4 | 3 | 1.00 | 83.7 | 80 83 88 | batch 3 | 65 | 0.78 | 74.0 | 0.88 | 0.92 | 1.61 |
| 4 | 16 x 4 | 3 | 1.00 | 70.7 | 81 55 76 | store 2, batch 1 | 33 | 0.47 | 42.0 | 0.59 | 0.62 | 1.91 |
| 8 | 16 x 4 | 3 | 1.00 | 33.7 | 34 33 34 | batch 3 | 17 | 0.50 | 26.0 | 0.77 | 0.80 | 4.01 |

Universal Scalability Law fit to the speed-ups: sigma = 0.170, kappa = 0.0000 (RMSE 0.41); no peak (kappa = 0).

Where the team's actions went (mean per run):

| agents | compute | store | coordination | wait | submit | other | duplicated computations | wrong submissions | rounds acted / rounds (mean over agents) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 65 | 0 | 5 | 0 | 65 | 0 | 0.0 | 0.0 | 1.00 |
| 2 | 66 | 0 | 31 | 4 | 66 | 0 | 1.0 | 0.7 | 1.00 |
| 4 | 70 | 70 | 64 | 12 | 67 | 0 | 4.7 | 2.0 | 1.00 |
| 8 | 65 | 0 | 109 | 30 | 65 | 0 | 0.0 | 0.0 | 1.00 |

T: lockstep rounds until the final task was accepted, over solved runs. T_lb: the lower bound on any team's rounds; b: efficiency against it. T_ref: the scripted team of the same size on the same problems (netagents/scaling.py). a: closeness to the reference; eta: coordination efficiency, a relative to the single agent's; speed-up: T(1)/T(N), same problem.
