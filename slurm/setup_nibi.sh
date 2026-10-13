#!/bin/bash
# One-time setup. Run on a Nibi LOGIN node (it has internet; compute nodes may not):
#     cd ~/EnviorementalAgent && bash slurm/setup_nibi.sh
set -euo pipefail
source "$(dirname "$0")/env.sh"
load_modules
mkdir -p "$WS_STORE/models" "$HF_HOME"

# ---------------------------------------------------------------- 1. agent (client) env
if [ ! -d "$AGENT_VENV" ]; then
  virtualenv --no-download "$AGENT_VENV" 2>/dev/null || python -m venv "$AGENT_VENV"
fi
source "$AGENT_VENV/bin/activate"
pip install --upgrade pip
pip install -r "$WS_ROOT/requirements.txt"
pip install "huggingface_hub[cli]"
python -c "import agents, openai; print('openai-agents OK', agents.__version__ if hasattr(agents,'__version__') else '')"
(cd "$WS_ROOT" && python -m pytest -q tests)   # CPU tests, no GPU/LLM needed
deactivate

# ---------------------------------------------------------------- 1b. agent frameworks (each in its own env)
# AutoGen (and Magentic-One): the framework designs of netagents/frameworks run in this env.
if [ ! -d "$AUTOGEN_VENV" ]; then
  virtualenv --no-download "$AUTOGEN_VENV" 2>/dev/null || python -m venv "$AUTOGEN_VENV"
fi
"$AUTOGEN_VENV/bin/pip" install -q "autogen-agentchat==0.7.5" "autogen-ext[openai]==0.7.5" sympy rdkit
"$AUTOGEN_VENV/bin/python" -c "import autogen_agentchat; print('AutoGen', autogen_agentchat.__version__)"

# ---------------------------------------------------------------- 2. vLLM (server) env
if [ "$SERVER_MODE" = "apptainer" ]; then
  module load apptainer 2>/dev/null || true
  [ -f "$VLLM_SIF" ] || apptainer pull "$VLLM_SIF" docker://vllm/vllm-openai:latest
else
  if [ ! -d "$VLLM_VENV" ]; then
    virtualenv --no-download "$VLLM_VENV" 2>/dev/null || python -m venv "$VLLM_VENV"
  fi
  source "$VLLM_VENV/bin/activate"
  pip install --upgrade pip
  # Prefer the Alliance wheelhouse (check with: avail_wheels vllm); fall back to PyPI.
  pip install --no-index vllm || pip install vllm
  python -c "import vllm; print('vLLM', vllm.__version__)"
  deactivate
fi

# ---------------------------------------------------------------- 3. model weights
source "$AGENT_VENV/bin/activate"
if [ ! -f "$MODEL_DIR/config.json" ]; then
  (hf download "$MODEL_ID" --local-dir "$MODEL_DIR" || huggingface-cli download "$MODEL_ID" --local-dir "$MODEL_DIR")
fi
echo "Setup complete. Weights: $MODEL_DIR"
echo "Next: sbatch slurm/net_eval.sh   (set --account in slurm/net_eval.sh first)"
