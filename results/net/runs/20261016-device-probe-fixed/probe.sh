#!/bin/bash
#SBATCH --job-name=net-device-probe-fixed
#SBATCH --account=rrg-hup_gpu
#SBATCH --gpus-per-node=nvidia_h100_80gb_hbm3_1g.10gb:1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=0-00:05
set -euo pipefail
cd /scratch/bdong/worldseeds/code/ccc3077-20261016-nvml
source slurm/env.sh
load_modules
source "$VLLM_VENV/bin/activate"
preload=$(python slurm/nvml_preload.py)
if [ -n "$preload" ]; then export LD_PRELOAD="$preload${LD_PRELOAD:+:$LD_PRELOAD}"; fi
echo "NVML preload: ${preload:-not required}"
export VLLM_LOGGING_LEVEL=DEBUG
export GPU_PROBE_OUT=/scratch/bdong/worldseeds/results/net/runs/20261016-device-probe-fixed/gpu-probe.json
python -u /scratch/bdong/worldseeds/results/net/runs/20261016-device-probe-fixed/probe.py
python - <<'PY'
import json,os
r=json.load(open(os.environ['GPU_PROBE_OUT']))
assert r['torch']['value']['available'] and r['torch']['value']['allocation']==1.0,r['torch']
assert r['nvml']['ok'],r['nvml']
assert r['vllm']['value']['device_type']=='cuda',r['vllm']
print('REAL_GPU_NVML_FIX_PASSED')
PY
