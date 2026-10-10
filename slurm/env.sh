# Shared settings for Nibi (Alliance / Compute Canada). Source this; edit to taste.
# Everything large (venvs, weights, results) goes to $SCRATCH or $PROJECT, not $HOME.

export WS_ROOT="${WS_ROOT:-$HOME/EnviorementalAgent}"          # this repository
export WS_STORE="${WS_STORE:-$SCRATCH/worldseeds}"              # big files
export VLLM_VENV="${VLLM_VENV:-$WS_STORE/venv-vllm}"            # server env (vLLM + torch)
export AGENT_VENV="${AGENT_VENV:-$WS_STORE/venv-agent}"         # client env (openai-agents)
export HF_HOME="${HF_HOME:-$WS_STORE/hf}"

# Free open-weight model served by vLLM. Good options on one H100-80GB:
#   Qwen/Qwen3-8B            (default; fast, solid tool calling)
#   Qwen/Qwen3-14B
#   Qwen/Qwen3-30B-A3B-FP8    (MoE; strong + fast)
#   Qwen/Qwen3-32B-FP8
#   Qwen/Qwen2.5-7B-Instruct  (older, 32k context, also uses the hermes parser)
# Qwen3-32B in bf16 needs TP=2 (two GPUs).
export MODEL_ID="${MODEL_ID:-Qwen/Qwen3-8B}"
export MODEL_DIR="${MODEL_DIR:-$WS_STORE/models/$(basename "$MODEL_ID")}"
export SERVED_NAME="${SERVED_NAME:-$(basename "$MODEL_ID" | tr '[:upper:]' '[:lower:]')}"
export TP="${TP:-1}"
export MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
# Extra vLLM flags, e.g. "--reasoning-parser qwen3" (if WS_THINKING=1) or YaRN for longer context:
#   --hf-overrides '{"rope_scaling":{"rope_type":"yarn","factor":2.0,"original_max_position_embeddings":32768}}'
export EXTRA_VLLM_ARGS="${EXTRA_VLLM_ARGS:-}"

# "venv" (pip-installed vLLM) or "apptainer" (official vllm/vllm-openai image)
export SERVER_MODE="${SERVER_MODE:-venv}"
export VLLM_SIF="${VLLM_SIF:-$WS_STORE/vllm-openai.sif}"

load_modules() {
  module load StdEnv/2023 python/3.11 gcc cuda/12.6 2>/dev/null || module load python/3.11
  module load opencv/4.13.0
}
