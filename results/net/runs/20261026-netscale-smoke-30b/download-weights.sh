#!/bin/bash
set -euo pipefail
cd /scratch/bdong/worldseeds/code/0406489-20261026-netscale-smoke-30b
export WS_ROOT=$PWD WS_STORE=/scratch/bdong/worldseeds
source slurm/env.sh
load_modules
source "$AGENT_VENV/bin/activate"
export HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 HF_HUB_DISABLE_PROGRESS_BARS=1
set +e
hf download Qwen/Qwen3-30B-A3B-FP8 --local-dir "$WS_STORE/models/Qwen3-30B-A3B-FP8"
rc=$?
python - "$rc" <<'END'
import sys,pathlib,json,datetime
p=pathlib.Path('/scratch/bdong/worldseeds/results/net/runs/20261026-netscale-smoke-30b/weight-download-status.json');s=json.loads(p.read_text());s.update(state='complete' if sys.argv[1]=='0' else 'failed',exit_code=int(sys.argv[1]),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat());t=p.with_suffix('.tmp');t.write_text(json.dumps(s,indent=2)+'
');t.replace(p)
END
exit "$rc"
