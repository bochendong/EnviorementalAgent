#!/bin/bash
# Submits the paper's experiments to Slurm (run on a Nibi login node, from the repository) and lays out
# one directory per run. Every job writes into it; nothing else needs to be copied.
#
#   ACCOUNT=def-yourpi bash slurm/run_all.sh                  # stage 1: baselines, fidelity, compatibility
#   ACCOUNT=def-yourpi RUN=20261013-qwen3-8b STAGE=2 bash slurm/run_all.sh    # stage 2 into the same run
#   ACCOUNT=def-yourpi DRY=1 STAGE=all bash slurm/run_all.sh  # print the jobs, submit nothing, write nothing
#
# Running it again with the same RUN and STAGE resumes: evaluation jobs skip the runs already in their
# runs.jsonl, and baselines and fidelity are skipped once their results exist.
#
# Stages (the compatibility track comes first: designs whose published finding reproduces are the ones
# compared on the network track):
#   focus  the paper's main 2x2 (netagents/testset.py FOCUS): sas, centralized, decentralized on math with
#          decomposable vs sequential tasks and shared vs split tools; one packed job (PACK=1)
#   load   when is splitting the work worth it? CodeWorld of 4, 8, 12 modules, tools shared or split among
#          four (LOAD_DESIGNS, default sas centralized decentralized); one packed job
#   smoke  first of all, ~10 GPU minutes: the server starts and answers every kind of request; one sas
#          and one centralized run go through without model errors (netagents/smoke.py)
#   check  before the real runs: fidelity (is our harness as good as plain chat?) and calibration (are the
#          presets in the range where designs can differ, for this model? CALIBRATION_DESIGNS, default
#          "sas reflexion centralized debate", on easy and medium presets and the compat cases, dev seeds)
#   1    baselines (scripted teams, CPU), fidelity (debate on GSM8K), compat-framework, compat-network
#   2    test, hard, heldout, scaling, topology, robustness (the network track)
#   3    org, faults, report, guidance, memory (mechanisms modelled on El Agente Q; network track)
#   all  1, 2 and 3
# Other settings: MODEL_ID (slurm/env.sh), DESIGNS (default: every ported design), FRAMEWORKS=1 (also
# AutoGen, Magentic-One, CAMEL on compat-framework and test), TIME (per job, default 1-00:00), SEEDS (only
# the first N seeds of each case, for a quick pass), N (GSM8K questions, default 100).
# GPU_RESOURCE, GPU_CPUS and GPU_MEM select the GPU allocation; defaults target Qwen3-8B on a 40 GB MIG.
# Override these for larger models, e.g. GPU_RESOURCE=h100:1 GPU_CPUS=8 GPU_MEM=64G.
#
# Layout ($WS_STORE/results/net/runs/$RUN/):
#   README.md                 index: every experiment, its status and its main table (netagents/report.py)
#   plan.tsv                  experiment, design, Slurm job id, what was run
#   commit.txt, env.txt       the code (commit and local changes) and the settings of the run
#   logs/                     Slurm logs and vLLM server logs
#   baselines/                scripted reference teams: baselines.md, baselines.json
#   fidelity/debate.json      official vs ported debate on GSM8K, with the paper's numbers
#   compat-framework/         compatibility track, messages through the framework
#     <design>/runs.jsonl     one job per design (resubmitting a job resumes it)
#     summary.md              all designs (written when the last design's job ends)
#     hypotheses.json         the published findings: reproduced / contradicted / inconclusive
#   compat-network/           the same cases, messages through the environment's network
#   test/ hard/ heldout/ scaling/ topology/ robustness/    the network track, same layout
set -euo pipefail
cd "$(dirname "$0")/.."
source slurm/env.sh

: "${ACCOUNT:?set ACCOUNT to your Slurm account, e.g. ACCOUNT=def-yourpi}"
CPU_ACCOUNT="${CPU_ACCOUNT:-$ACCOUNT}"
GPU_ACCOUNT="${GPU_ACCOUNT:-$ACCOUNT}"
GPU_RESOURCE="${GPU_RESOURCE:-nvidia_h100_80gb_hbm3_3g.40gb:1}"
GPU_CPUS="${GPU_CPUS:-4}"
GPU_MEM="${GPU_MEM:-32G}"
STAGE="${STAGE:-1}"
RUN="${RUN:-$(date +%Y%m%d)-$SERVED_NAME}"
RUN_DIR="$WS_STORE/results/net/runs/$RUN"
TIME="${TIME:-1-00:00}"
DESIGNS="${DESIGNS:-react reflexion sas independent centralized decentralized hybrid debate moa blackboard}"
FRAMEWORK_DESIGNS="autogen-roundrobin autogen-selector magentic-one camel-roleplay"
DRY="${DRY:-0}"

case "$STAGE" in
  smoke) EXPERIMENTS="smoke" ;;
  focus) EXPERIMENTS="focus" ;;
  load) EXPERIMENTS="load" ;;
  check) EXPERIMENTS="fidelity calibration" ;;
  1) EXPERIMENTS="baselines fidelity compat-framework compat-network" ;;
  2) EXPERIMENTS="test hard heldout scaling topology robustness" ;;
  3) EXPERIMENTS="org faults report guidance memory" ;;
  all) EXPERIMENTS="baselines fidelity compat-framework compat-network test hard heldout scaling topology robustness org faults report guidance memory" ;;
  *) EXPERIMENTS="$STAGE" ;;  # or name experiments directly: STAGE="compat-framework test"
esac

if [ "$DRY" = 1 ]; then
  PLAN=$(mktemp)
else
  mkdir -p "$RUN_DIR/logs"
  PLAN="$RUN_DIR/plan.tsv"
  [ -f "$PLAN" ] || printf "experiment\tdesign\tjob\tcommand\n" > "$PLAN"
  { echo "commit $(git rev-parse HEAD)  ($(git rev-parse --abbrev-ref HEAD))"; echo "submitted $(date -Is)";
  git status --short | sed 's/^/changed /'; } >> "$RUN_DIR/commit.txt"
{ echo "# $(date -Is), stage $STAGE"; for v in ACCOUNT CPU_ACCOUNT GPU_ACCOUNT GPU_RESOURCE GPU_CPUS GPU_MEM GPU_DEPENDENCY MODEL_ID SERVED_NAME TP MAX_MODEL_LEN EXTRA_VLLM_ARGS SERVER_MODE \
  DESIGNS FRAMEWORKS SEEDS N TIME; do echo "$v=${!v:-}"; done; } >> "$RUN_DIR/env.txt"
fi

N0=$(wc -l < "$PLAN")
submit() {  # submit <experiment> <design> <sbatch args...>; prints the job id
  local exp=$1 design=$2; shift 2
  local id account="$GPU_ACCOUNT"
  if [ "$exp" = baselines ] || [ "$design" = summary ]; then account="$CPU_ACCOUNT"; fi
  local common=(--account="$account" --parsable)
  if [ "$exp" != baselines ] && [ "$design" != summary ]; then
    common+=(--gpus-per-node="$GPU_RESOURCE" --cpus-per-task="$GPU_CPUS" --mem="$GPU_MEM")
  fi
  if [ "$exp" != baselines ] && [ "$design" != summary ] && [ -n "${GPU_DEPENDENCY:-}" ]; then
    common+=(--dependency="afterok:$GPU_DEPENDENCY")
  fi
  if [ "$DRY" = 1 ]; then
    id="dry$RANDOM"; echo "sbatch ${common[*]} $*" >&2
  else
    id=$(sbatch "${common[@]}" "$@")
  fi
  printf "%s\t%s\t%s\t%s\n" "$exp" "$design" "$id" "$*" >> "$PLAN"
  echo "$id"
}

for exp in $EXPERIMENTS; do
  out="$RUN_DIR/$exp"
  [ "$DRY" = 1 ] || mkdir -p "$out"
  case "$exp" in
    baselines)
      [ -f "$out/baselines.md" ] && { echo "skip $exp: $out/baselines.md exists"; continue; }
      submit "$exp" scripted --job-name=net-baselines --cpus-per-task=4 --mem=16G --time=0-06:00 \
        --output="$RUN_DIR/logs/%x-%j.out" --export=ALL \
        --wrap="source slurm/env.sh && load_modules && source \$AGENT_VENV/bin/activate && python -m netagents.baselines --seeds 10 --out $out" >/dev/null
      continue ;;
    smoke)
      submit "$exp" smoke --job-name=net-smoke --time=0-00:45 --output="$RUN_DIR/logs/%x-%j.out" \
        --export=ALL,OUT="$out",LOG_DIR="$RUN_DIR/logs" slurm/net_smoke.sh >/dev/null
      continue ;;
    fidelity)
      [ -f "$out/debate.json" ] && { echo "skip $exp: $out/debate.json exists"; continue; }
      # Compute nodes may have no internet: fetch the benchmark and authors' code on the login node.
      if [ "$DRY" != 1 ]; then
        "$AGENT_VENV/bin/python" - "$out" <<'PY'
import os
import sys
from netagents.fidelity import DEBATE, GSM8K, fetch
cache = os.path.join(sys.argv[1], "cache")
fetch(DEBATE, os.path.join(cache, "debate"))
fetch(GSM8K, cache)
PY
      fi
      submit "$exp" debate --job-name=net-fidelity --time=0-08:00 --output="$RUN_DIR/logs/%x-%j.out" \
        --export=ALL,OUT="$out",N="${N:-100}",LOG_DIR="$RUN_DIR/logs" slurm/net_fidelity.sh >/dev/null
      continue ;;
    compat-framework) suite=compat; route=case ;;
    compat-network) suite=compat; route=network ;;
    *) suite=$exp; route=case ;;
  esac
  designs="$DESIGNS"
  [ "$exp" = calibration ] && designs="${CALIBRATION_DESIGNS:-sas reflexion centralized debate}"
  [ "$exp" = focus ] && designs="${FOCUS_DESIGNS:-sas centralized decentralized}"
  [ "$exp" = load ] && designs="${LOAD_DESIGNS:-sas centralized decentralized}"
  pack="${PACK:-$({ [ "$exp" = focus ] || [ "$exp" = load ]; } && echo 1 || echo 0)}"
  if [ "${FRAMEWORKS:-0}" = 1 ] && { [ "$exp" = compat-framework ] || [ "$exp" = test ]; }; then
    designs="$designs $FRAMEWORK_DESIGNS"
  fi
  if [ "$exp" = compat-network ]; then  # single agents send nothing; sas stays as the findings' baseline
    designs=$(for d in $designs; do case $d in react|reflexion|autogen-*|magentic-one|camel-*) ;; *) echo "$d";; esac; done)
  fi
  ids=()
  if [ "$pack" = 1 ]; then  # one job for every design: one server start-up and one place in the queue
    d=$(echo $designs | tr ' ' '-')
    ids+=("$(submit "$exp" "$d" --job-name="net-$exp" --time="$TIME" --output="$RUN_DIR/logs/%x-%j.out" \
      --export=ALL,SUITE="$suite",DESIGNS="$designs",ROUTE="$route",OUT="$out/all",LOG_DIR="$RUN_DIR/logs",SEEDS="${SEEDS:-}" \
      slurm/net_eval.sh)")
    designs=""
  fi
  for d in $designs; do
    ids+=("$(submit "$exp" "$d" --job-name="net-$exp-$d" --time="$TIME" --output="$RUN_DIR/logs/%x-%j.out" \
      --export=ALL,SUITE="$suite",DESIGNS="$d",ROUTE="$route",OUT="$out/$d",LOG_DIR="$RUN_DIR/logs",SEEDS="${SEEDS:-}" \
      slurm/net_eval.sh)")
  done
  dep=$(IFS=:; echo "${ids[*]}")
  submit "$exp" summary --job-name="net-$exp-summary" --dependency="afterany:$dep" \
    --output="$RUN_DIR/logs/%x-%j.out" --export=ALL,DIR="$out" slurm/net_summary.sh >/dev/null
done

[ "$DRY" = 1 ] || ( source "$AGENT_VENV/bin/activate" 2>/dev/null; python -m netagents.report "$RUN_DIR" >/dev/null 2>&1 ) || true
echo "run:   $RUN"
echo "dir:   $RUN_DIR"
echo "jobs:  $(($(wc -l < "$PLAN") - N0)) submitted$([ "$DRY" = 1 ] && echo " (dry run: nothing was submitted)")"
echo "watch: squeue -u \$USER;  index: python -m netagents.report $RUN_DIR"
echo "later: ACCOUNT=$ACCOUNT RUN=$RUN STAGE=2 bash slurm/run_all.sh"
