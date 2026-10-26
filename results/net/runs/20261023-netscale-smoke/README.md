# Run 20261023-netscale-smoke

`commit.txt`:

```
commit 0b8335b768aa6782492efc6f4260dd254739cc0b  (HEAD)
submitted 2026-10-23T16:00:39-04:00
```

`env.txt`:

```
# 2026-10-23T16:00:39-04:00, stage netscale-smoke
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
SEEDS=1
N=
TIME=0-02:00
NETSCALE_DESIGNS=peers
WS_THINKING=1
WS_MAX_TOKENS=3072
WS_CONTEXT_TOKENS=39321
NETAGENTS_PARALLEL=2
```

## netscale-smoke



Jobs: peers `24880344`, summary `24880348`

Runs per design: peers 1

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

