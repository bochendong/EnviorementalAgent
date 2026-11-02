# Run 20261027-screen-gpt-oss-120b

`commit.txt`:

```
commit e37e95821508345298bff794db595258ce643316  (HEAD)
submitted 2026-10-27T22:20:25-04:00
```

`env.txt`:

```
# 2026-10-27T22:20:27-04:00, stage netscale-screen
ACCOUNT=rrg-hup_gpu
CPU_ACCOUNT=def-hup-ab_cpu
GPU_ACCOUNT=rrg-hup_gpu
GPU_RESOURCE=h100:1
GPU_CPUS=4
GPU_MEM=64G
GPU_DEPENDENCY=
MODEL_ID=openai/gpt-oss-120b
SERVED_NAME=gpt-oss-120b
TP=1
MAX_MODEL_LEN=65536
NATIVE_LEN=131072
TOOL_PARSER=openai
REASONING_PARSER=openai_gptoss
EXTRA_VLLM_ARGS=--kv-cache-dtype auto
SERVER_MODE=venv
CUDA_MODULE=cuda/12.9
DESIGNS=react reflexion sas independent centralized decentralized hybrid debate moa blackboard
FRAMEWORKS=
SEEDS=
N=
TIME=1-00:00
NETSCALE_DESIGNS=
WS_THINKING=1
WS_MAX_TOKENS=
WS_CONTEXT_TOKENS=39321
NETAGENTS_PARALLEL=
```

## netscale-screen



Jobs: peers `25163604`, summary `25163605`

Runs per design: peers 2

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

