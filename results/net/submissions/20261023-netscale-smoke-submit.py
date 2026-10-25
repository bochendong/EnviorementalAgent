"""Submit one authorized netscale smoke GPU job and its CPU summary, preserving job IDs."""
import csv
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess

STORE = Path('/scratch/bdong/worldseeds')
SOURCE = STORE / 'code/0b8335b-20261023-netscale-smoke'
COMMIT = '0b8335b768aa6782492efc6f4260dd254739cc0b'
RUN = '20261023-netscale-smoke'
ROOT = STORE / 'results/net/runs' / RUN
MANIFEST = STORE / 'results/net/submissions/20261023-netscale-smoke.json'
MANIFEST.parent.mkdir(parents=True, exist_ok=True)
lock = open(MANIFEST.with_suffix('.lock'), 'a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
os.chdir(SOURCE)
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
assert not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()


def save(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(path)


params = dict(ACCOUNT='rrg-hup_gpu', CPU_ACCOUNT='def-hup-ab_cpu', GPU_ACCOUNT='rrg-hup_gpu',
              STAGE='netscale-smoke', RUN=RUN, TIME='0-02:00', PACK='1', NETSCALE_DESIGNS='peers',
              GPU_RESOURCE='h100:1', GPU_CPUS='4', GPU_MEM='32G', GPU_DEPENDENCY='',
              WS_TIMEOUT='900', WS_THINKING='1', WS_TOOL_CHOICE='required', WS_MAX_TOKENS='3072',
              WS_TEMPERATURE='0.6', WS_TOP_P='0.95', WS_TOP_K='20',
              MODEL_ID='Qwen/Qwen3-8B', TP='1', SERVER_MODE='venv', EXTRA_VLLM_ARGS='',
              MAX_MODEL_LEN='65536', WS_CONTEXT_TOKENS='39321', WS_CHARS_PER_TOKEN='1.5',
              WS_ROOT=str(SOURCE), WS_STORE=str(STORE), NETAGENTS_PARALLEL='2',
              NETAGENTS_TRANSCRIPTS='1', PYTHONUNBUFFERED='1', SEEDS='1', DRY='0')
if MANIFEST.exists():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['source_commit'] == COMMIT and manifest['settings'] == params
else:
    manifest = dict(run=RUN, source_commit=COMMIT, source=str(SOURCE), settings=params,
                    created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    expected_gpu_jobs=1, expected_cpu_summary_jobs=1, expected_runs=2,
                    sizes=[1, 8], seeds=[100], problem={'provider': 'dag', 'width': 16, 'depth': 4, 'grain': 1},
                    stage='prepared', jobs=[],
                    verification={'nibi_focused_tests_passed': 4, 'suite_shape_verified': True},
                    trace_coverage='Both smoke cases have one seed; both save environment events and retained member conversations (2 traces).',
                    scope='Submit one smoke GPU job and its CPU summary now. The user conditionally authorized a new pilot (1/2/4/8 agents, grains1/4, 3 seeds;24 runs) only after this smoke passes. Verify both records and zero LLM errors, single-agent success and b near1; do not expand if the gate is ambiguous. No full netscale, automatic retry, or alternate settings. The previously cancelled periodic monitor is not recreated.')
    save(MANIFEST, manifest)
ROOT.mkdir(parents=True, exist_ok=True)
save(ROOT / 'experiment-settings.json', manifest)
plan = ROOT / 'plan.tsv'
rows = []
if plan.exists():
    with plan.open() as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    assert len(rows) <= 2
if not rows:
    # If submission previously returned an unknown outcome, stop instead of duplicating a GPU job.
    queued = subprocess.check_output(['squeue', '-u', os.environ['USER'], '-h', '-n', 'net-netscale-smoke', '-o', '%i'], text=True, timeout=30)
    for jid in queued.split():
        details = subprocess.check_output(['scontrol', 'show', 'job', jid, '-o'], text=True, timeout=30)
        assert 'StdOut=' + str(ROOT / 'logs') + '/' not in details, 'Matching queued job exists without plan; inspect and adopt before retrying'
    manifest['stage'] = 'submitting'
    save(MANIFEST, manifest)
    result = subprocess.run(['bash', 'slurm/run_all.sh'], env={**os.environ, **params},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
    (ROOT / 'submission-output.txt').write_text(result.stdout)
    print(result.stdout, flush=True)
    if plan.exists():
        with plan.open() as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
    manifest['jobs'] = rows
    save(MANIFEST, manifest)
    assert result.returncode == 0, 'Partial submission; inspect recorded plan before any further action'
else:
    print('Existing plan retained; submitting nothing', flush=True)
assert len(rows) == 2 and {r['design'] for r in rows} == {'peers', 'summary'}, rows
assert all(r['experiment'] == 'netscale-smoke' and r['job'].isdigit() for r in rows)
manifest['jobs'] = rows
manifest['stage'] = 'submitted'
manifest['recorded_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
save(MANIFEST, manifest)
save(ROOT / 'submission.json', manifest)
print(json.dumps(manifest, indent=2), flush=True)
