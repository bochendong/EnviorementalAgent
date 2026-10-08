#!/bin/bash
# Context as pictures: a vision-language model sees its current view and its memory canvas as images
# (--context image), against the same model reading the canvas as text and a plain transcript.
#   MODEL_ID=Qwen/Qwen3-VL-8B-Instruct bash slurm/setup_nibi.sh     # once: download the weights
#   bash slurm/submit_vision.sh
#   PILOT=1 bash slurm/submit_vision.sh                             # one universe, few towns
# Needs a vLLM recent enough to serve Qwen3-VL (0.11 or newer). Each request carries a view and up to a
# few canvas pages, so the server allows several images per prompt.
set -euo pipefail
cd "$(dirname "$0")/.."
export MODEL_ID="${MODEL_ID:-Qwen/Qwen3-VL-8B-Instruct}"
if [ -z "${EXTRA_VLLM_ARGS:-}" ]; then
  export EXTRA_VLLM_ARGS='--limit-mm-per-prompt {"image":8}'
fi
source slurm/env.sh
OUT="${OUT:-$WS_STORE/results/$SERVED_NAME/vision}"
UNIVERSES="${UNIVERSES:-1 2}"
NTR=12; NTE=10; TIME=1-00:00
if [ "${PILOT:-0}" = 1 ]; then UNIVERSES=1; NTR=4; NTE=3; TIME=0-06:00; OUT="$OUT/pilot"; fi
for u in $UNIVERSES; do
  for ctx in transcript canvas image; do
    sbatch --job-name="ws-vision-$ctx-u$u" --time="$TIME" slurm/serve_and_run.sh \
      --protocol compgen --conditions none seed --context "$ctx" --universes "$u" --n-train "$NTR" --n-test "$NTE" \
      --env board --max-actions 200 --max-turns 320 --concurrency 16 --save-traces --out "$OUT/$ctx/u$u"
  done
done
echo "submitted. summary: python scripts/analyze.py $OUT --by condition context phase"
