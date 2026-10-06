#!/bin/bash
#SBATCH --job-name=worldseeds
#SBATCH --account=def-CHANGE_ME
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=0-12:00
#SBATCH --output=logs/%x-%j.out
#
# Starts a vLLM OpenAI-compatible server for a free Qwen model on the allocated GPU,
# waits for it, then runs one experiment against it. All arguments are forwarded to
# scripts/run_experiment.py, e.g.
#   sbatch slurm/serve_and_run.sh --protocol compgen --conditions none retrieval seed oracle \
#          --universes 0 1 2 --views zoom flat --out $SCRATCH/worldseeds/results/compgen
# Override the model per job:  MODEL_ID=Qwen/Qwen3-30B-A3B-FP8 sbatch slurm/serve_and_run.sh ...
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source slurm/env.sh
load_modules
mkdir -p logs

export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1   # weights were downloaded by setup_nibi.sh
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
PORT=$((20000 + ${SLURM_JOB_ID:-0} % 20000))
JOB=${SLURM_JOB_ID:-local}
SERVER_LOG="logs/vllm-$JOB.log"

VLLM_ARGS=(--host 127.0.0.1 --port "$PORT" --served-model-name "$SERVED_NAME"
           --tensor-parallel-size "$TP" --max-model-len "$MAX_MODEL_LEN"
           --gpu-memory-utilization 0.90 --max-num-seqs 64
           --enable-auto-tool-choice --tool-call-parser hermes --enable-prefix-caching)
# shellcheck disable=SC2206
EXTRA=($EXTRA_VLLM_ARGS)

if [ "$SERVER_MODE" = "apptainer" ]; then
  module load apptainer 2>/dev/null || true
  apptainer exec --nv -B "$WS_STORE" "$VLLM_SIF" \
    vllm serve "$MODEL_DIR" "${VLLM_ARGS[@]}" "${EXTRA[@]}" > "$SERVER_LOG" 2>&1 &
else
  source "$VLLM_VENV/bin/activate"
  vllm serve "$MODEL_DIR" "${VLLM_ARGS[@]}" "${EXTRA[@]}" > "$SERVER_LOG" 2>&1 &
  deactivate
fi
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

echo "waiting for vLLM on port $PORT (log: $SERVER_LOG)"
for i in $(seq 1 180); do
  if curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null; then echo "server up after $((i*10))s"; break; fi
  if ! kill -0 $SERVER_PID 2>/dev/null; then echo "vLLM died:"; tail -50 "$SERVER_LOG"; exit 1; fi
  sleep 10
done
curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null || { echo "vLLM did not start"; tail -50 "$SERVER_LOG"; exit 1; }

source "$AGENT_VENV/bin/activate"
export WS_BASE_URL="http://127.0.0.1:$PORT/v1" WS_MODEL="$SERVED_NAME" WS_API_KEY=EMPTY
python scripts/run_experiment.py "$@"
OUT_DIR=results/run
ARGS=("$@")
for ((i = 0; i < ${#ARGS[@]}; i++)); do
  if [ "${ARGS[$i]}" = "--out" ]; then OUT_DIR="${ARGS[$((i + 1))]}"; fi
done
python scripts/analyze.py "$OUT_DIR" || true
