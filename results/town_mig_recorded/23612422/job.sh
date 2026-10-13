#!/bin/bash
#SBATCH --job-name=ws-town-mig-recorded
#SBATCH --account=def-hup-ab_gpu
#SBATCH --gres=gpu:nvidia_h100_80gb_hbm3_3g.40gb:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?submit from repository root}"
source slurm/env.sh
load_modules
mkdir -p logs
export PYTHONUNBUFFERED=1
export MAX_MODEL_LEN=32768
export WS_THINKING=1 WS_TOOL_CHOICE=auto WS_MAX_TOKENS=4096
# Extra flags are appended after the defaults; argparse uses the final value.
export EXTRA_VLLM_ARGS="${EXTRA_VLLM_ARGS:-} --max-num-seqs 4 --reasoning-parser qwen3"
OUT="${OUT:-$WS_STORE/results/town_mig_recorded/$SLURM_JOB_ID}"
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/commit.txt"
git diff > "$OUT/source.patch"
cp slurm/town_mig_pilot.sh "$OUT/job.sh"
python3 - "$OUT" <<'PY'
import sys, pathlib, tarfile, json, hashlib
out = pathlib.Path(sys.argv[1])
paths = sorted(pathlib.Path('worldseeds').rglob('*.py'))
paths += [pathlib.Path(p) for p in ('scripts/run_codeworld.py', 'scripts/report_codeworld_run.py',
                                 'web/codeworld.js', 'slurm/start_vllm.sh', 'slurm/env.sh', 'slurm/town_mig_pilot.sh')]
with tarfile.open(out / 'source.tar.gz', 'w:gz') as tar:
    for p in paths: tar.add(p, arcname=str(p))
(out / 'source-sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, indent=2))
PY
python --version > "$OUT/python-version.txt"
date -u +%FT%TZ > "$OUT/started-utc.txt"
START_SECONDS=$SECONDS
nvidia-smi -L
nvidia-smi -q > "$OUT/gpu-start.txt"
source slurm/start_vllm.sh
printf 'server_ready_seconds=%s\n' "$((SECONDS - START_SECONDS))" | tee "$OUT/timing.txt"
monitor_gpu() {
  while true; do
    date -u +%FT%TZ
    nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv || true
    curl -sf "http://127.0.0.1:$PORT/metrics" | grep -E '^(vllm:gpu_cache_usage_perc|vllm:kv_cache_usage_perc|vllm:num_requests_running)' || true
    sleep 15
  done
}
monitor_gpu > "$OUT/gpu-samples.log" 2>&1 &
MONITOR_PID=$!
cleanup() {
  kill "$MONITOR_PID" "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT
RUN_SECONDS=$SECONDS
set +e
python scripts/run_codeworld.py --policy llm --save-traces --theme town --walk --money --answer-price 0 \
  --goals banquet prize fund --fund 300 --goal-deadline 1 \
  --universes 1 --modules 8 --fns-per-module 6 --capacities 12 --team-sizes 4 \
  --sprints 1 --projects-per-dev 1 --budget 40 --max-turns 160 \
  --variants solo owners --out "$OUT"
RUN_EXIT=$?
set -e
printf 'experiment_seconds=%s\nexit_code=%s\n' "$((SECONDS - RUN_SECONDS))" "$RUN_EXIT" | tee -a "$OUT/timing.txt"
cp "$SERVER_LOG" "$OUT/vllm.log"
python scripts/report_codeworld_run.py "$OUT" || true
if [ "$RUN_EXIT" -eq 0 ]; then
  python scripts/analyze_codeworld.py "$OUT" --costs
fi
exit "$RUN_EXIT"

