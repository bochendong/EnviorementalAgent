# Sourced by GPU job scripts (net_llm.sh): starts a vLLM OpenAI-compatible server for
# $MODEL_DIR on the job's GPU, waits until it answers, and exports WS_BASE_URL / WS_MODEL for the client.
# Expects slurm/env.sh to be sourced and modules loaded. The server is killed when the job script exits.
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1   # weights were downloaded by setup_nibi.sh
export VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
PORT=$((20000 + ${SLURM_JOB_ID:-0} % 20000))
JOB=${SLURM_JOB_ID:-local}
SERVER_LOG="${SERVER_LOG:-${LOG_DIR:-logs}/vllm-$JOB.log}"
# Compile caches (torch.compile, Inductor, Triton) per job on node-local disk: jobs that start together
# and share one cache in $HOME read each other's half-written files ("compile cache" errors at start-up).
CACHE_BASE="${SLURM_TMPDIR:-/tmp/vllm-$USER-$JOB}"
export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-$CACHE_BASE/vllm-cache}"
export TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-$CACHE_BASE/inductor-cache}"
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-$CACHE_BASE/triton-cache}"
mkdir -p "$VLLM_CACHE_ROOT" "$TORCHINDUCTOR_CACHE_DIR" "$TRITON_CACHE_DIR"

VLLM_ARGS=(--host 127.0.0.1 --port "$PORT" --served-model-name "$SERVED_NAME"
           --tensor-parallel-size "$TP" --max-model-len "$MAX_MODEL_LEN"
           --gpu-memory-utilization 0.90 --max-num-seqs 64
           --enable-auto-tool-choice --tool-call-parser hermes --enable-prefix-caching)
[ -n "${REASONING_PARSER:-}" ] && VLLM_ARGS+=(--reasoning-parser "$REASONING_PARSER")
if [ "$MAX_MODEL_LEN" -gt "${NATIVE_LEN:-32768}" ]; then  # YaRN beyond the trained context
  FACTOR=$(awk "BEGIN{print $MAX_MODEL_LEN / ${NATIVE_LEN:-32768}}")
  VLLM_ARGS+=(--hf-overrides "{\"rope_scaling\":{\"rope_type\":\"yarn\",\"factor\":$FACTOR,\"original_max_position_embeddings\":${NATIVE_LEN:-32768}}}")
fi
# shellcheck disable=SC2206
EXTRA=($EXTRA_VLLM_ARGS)

if [ "$SERVER_MODE" = "apptainer" ]; then
  module load apptainer 2>/dev/null || true
  apptainer exec --nv -B "$WS_STORE" -B "$CACHE_BASE" "$VLLM_SIF" \
    vllm serve "$MODEL_DIR" "${VLLM_ARGS[@]}" "${EXTRA[@]}" > "$SERVER_LOG" 2>&1 &
else
  source "$VLLM_VENV/bin/activate"
  # nvidia-smi and torch may work while this Python's loader cannot find NVML. Load only the
  # driver library explicitly; adding all of /usr/lib64 would mix system and module libraries.
  vllm_nvml_preload=$(python slurm/nvml_preload.py)
  vllm_driver_env=()
  if [ -n "$vllm_nvml_preload" ]; then
    vllm_driver_env+=("LD_PRELOAD=$vllm_nvml_preload${LD_PRELOAD:+:$LD_PRELOAD}")
  fi
  if ! env "${vllm_driver_env[@]}" python -u - > "$SERVER_LOG" 2>&1 <<'PY'
import json
import os
import shutil
import subprocess
import torch
from vllm.utils.import_utils import import_pynvml

print(json.dumps({"phase": "GPU preflight", "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                  "torch": torch.__version__, "cuda_build": torch.version.cuda,
                  "cuda_module": os.environ.get("CUDA_MODULE"), "cuda_home": os.environ.get("CUDA_HOME"),
                  "nvcc": shutil.which("nvcc"),
                  "nvcc_version": subprocess.check_output(["nvcc", "--version"], text=True) if shutil.which("nvcc") else None,
                  "cuda_available": torch.cuda.is_available(), "device_count": torch.cuda.device_count(),
                  "nvml_preload": os.environ.get("LD_PRELOAD", "")}), flush=True)
if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
    raise RuntimeError("Allocated GPU is unavailable to PyTorch; check the Slurm allocation and driver")
nvml = import_pynvml()
nvml.nvmlInit()
try:
    print("NVML driver:", nvml.nvmlSystemGetDriverVersion(), flush=True)
finally:
    nvml.nvmlShutdown()
from vllm.platforms import current_platform
if not current_platform.is_cuda():
    raise RuntimeError(f"vLLM did not select CUDA: {type(current_platform).__name__}")
print("GPU preflight passed:", torch.cuda.get_device_name(0), flush=True)
PY
  then
    echo "GPU preflight failed (log: $SERVER_LOG)"
    cat "$SERVER_LOG"
    exit 1
  fi
  env "${vllm_driver_env[@]}" vllm serve "$MODEL_DIR" "${VLLM_ARGS[@]}" "${EXTRA[@]}" >> "$SERVER_LOG" 2>&1 &
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
