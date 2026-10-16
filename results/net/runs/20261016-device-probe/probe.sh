#!/bin/bash
#SBATCH --job-name=net-device-probe
#SBATCH --account=rrg-hup_gpu
#SBATCH --gpus-per-node=nvidia_h100_80gb_hbm3_1g.10gb:1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=0-00:05
set -euo pipefail
cd /scratch/bdong/worldseeds/code/e2f91e3-20261015-smoke
source slurm/env.sh
load_modules
source "$VLLM_VENV/bin/activate"
export VLLM_LOGGING_LEVEL=DEBUG
export GPU_PROBE_OUT=/scratch/bdong/worldseeds/results/net/runs/20261016-device-probe/gpu-probe.json
python -u gpu_probe.py
