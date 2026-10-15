# Shared settings for Nibi (Alliance / Compute Canada). Source this; edit to taste.
# Everything large (venvs, weights, results) goes to $SCRATCH or $PROJECT, not $HOME.

export WS_ROOT="${WS_ROOT:-$HOME/EnviorementalAgent}"          # this repository
export WS_STORE="${WS_STORE:-$SCRATCH/worldseeds}"              # big files
export VLLM_VENV="${VLLM_VENV:-$WS_STORE/venv-vllm}"            # server env (vLLM + torch)
export AGENT_VENV="${AGENT_VENV:-$WS_STORE/venv-agent}"         # client env (openai-agents)
export AUTOGEN_VENV="${AUTOGEN_VENV:-$WS_STORE/venv-autogen}"   # AutoGen, for the framework designs
export NETAGENTS_PY_AUTOGEN="${NETAGENTS_PY_AUTOGEN:-$AUTOGEN_VENV/bin/python}"
export CAMEL_VENV="${CAMEL_VENV:-$WS_STORE/venv-camel}"         # CAMEL, for the framework designs
export NETAGENTS_PY_CAMEL="${NETAGENTS_PY_CAMEL:-$CAMEL_VENV/bin/python}"
export HF_HOME="${HF_HOME:-$WS_STORE/hf}"
export TIKTOKEN_CACHE_DIR="${TIKTOKEN_CACHE_DIR:-$WS_STORE/tiktoken}"

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
# Context window. Qwen3 is trained on 32k; above that start_vllm.sh turns on YaRN (factor MAX_MODEL_LEN/NATIVE_LEN).
export MAX_MODEL_LEN="${MAX_MODEL_LEN:-65536}"
export NATIVE_LEN="${NATIVE_LEN:-32768}"
# Thinking on, with the reasoning kept out of answers and histories (netagents/llm.py explains why).
export WS_THINKING="${WS_THINKING:-1}"
case "$MODEL_ID" in *Qwen3*|*qwen3*) export REASONING_PARSER="${REASONING_PARSER:-qwen3}" ;; esac
export REASONING_PARSER="${REASONING_PARSER:-}"
# History an agent keeps before each turn (estimated tokens): the window less room for tools and output.
export WS_CONTEXT_TOKENS="${WS_CONTEXT_TOKENS:-$((MAX_MODEL_LEN * 6 / 10))}"
# Other vLLM flags, if any:
export EXTRA_VLLM_ARGS="${EXTRA_VLLM_ARGS:-}"

# "venv" (pip-installed vLLM) or "apptainer" (official vllm/vllm-openai image)
export SERVER_MODE="${SERVER_MODE:-venv}"
export VLLM_SIF="${VLLM_SIF:-$WS_STORE/vllm-openai.sif}"

load_modules() {
  module load StdEnv/2023 python/3.11 gcc cuda/12.6 2>/dev/null || module load python/3.11
  module load opencv/4.13.0
  module load "${RDKIT_MODULE:-rdkit/2025.09.4}"
}
