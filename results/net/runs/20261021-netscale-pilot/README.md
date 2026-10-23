# Run 20261021-netscale-pilot

`commit.txt`:

```
commit ad95c039c11239ff029e5d36eaaa8b6102ef5677  (HEAD)
submitted 2026-10-21T02:28:03-04:00
```

`env.txt`:

```
# 2026-10-21T02:28:03-04:00, stage netscale-pilot
ACCOUNT=rrg-hup_gpu
CPU_ACCOUNT=def-hup-ab_cpu
GPU_ACCOUNT=rrg-hup_gpu
GPU_RESOURCE=h100:1
GPU_CPUS=4
GPU_MEM=32G
GPU_DEPENDENCY=
MODEL_ID=Qwen/Qwen3-8B
SERVED_NAME=qwen3-8b
TP=1
MAX_MODEL_LEN=65536
EXTRA_VLLM_ARGS=
SERVER_MODE=venv
DESIGNS=react reflexion sas independent centralized decentralized hybrid debate moa blackboard
FRAMEWORKS=
SEEDS=3
N=
TIME=0-12:00
NETSCALE_DESIGNS=peers
WS_THINKING=1
```

## netscale-pilot

agent-network scaling, pilot: 1-8 identical agents on one DAG problem, against the scripted reference

Jobs: peers `24729787`, summary `24729788`

Runs per design: peers 10

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

