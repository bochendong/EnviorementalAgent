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
SOURCE = STORE / 'code/05fc8d4-20261027-netscale-smoke-30b-tool-retry'
COMMIT = '05fc8d44b39fd4ce72bc850f92a6c796b5107faa'
RUN = '20261027-netscale-smoke-30b-tool-retry'
ROOT = STORE / 'results/net/runs' / RUN
MANIFEST = STORE / 'results/net/submissions/20261027-netscale-smoke-30b-tool-retry.json'
MANIFEST.parent.mkdir(parents=True, exist_ok=True)
lock = open(MANIFEST.with_suffix('.lock'), 'a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
os.chdir(SOURCE)
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
assert not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()
model_dir=STORE / 'models/Qwen3-30B-A3B-FP8'
index=json.loads((model_dir / 'model.safetensors.index.json').read_text())
assert all((model_dir / x).is_file() and (model_dir / x).stat().st_size>0 for x in set(index['weight_map'].values()))


def save(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(path)


params = dict(ACCOUNT='rrg-hup_gpu', CPU_ACCOUNT='def-hup-ab_cpu', GPU_ACCOUNT='rrg-hup_gpu',
              STAGE='netscale-smoke', RUN=RUN, TIME='0-06:00', PACK='1', NETSCALE_DESIGNS='peers',
              GPU_RESOURCE='h100:1', GPU_CPUS='4', GPU_MEM='64G', GPU_DEPENDENCY='',
              CUDA_MODULE='cuda/12.9', WS_TIMEOUT='900', WS_THINKING='1', WS_TOOL_CHOICE='required', WS_MAX_TOKENS='3072',
              WS_TEMPERATURE='0.6', WS_TOP_P='0.95', WS_TOP_K='20',
              MODEL_ID='Qwen/Qwen3-30B-A3B-FP8', MODEL_DIR=str(STORE / 'models/Qwen3-30B-A3B-FP8'), SERVED_NAME='qwen3-30b-a3b-fp8', TP='1', SERVER_MODE='venv', EXTRA_VLLM_ARGS='--kv-cache-dtype fp8',
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
                    verification={'nibi_focused_tests_passed': 24, 'suite_shape_verified': True},
                    trace_coverage='Both smoke cases have one seed; both save environment events and retained member conversations (2 traces).',
                    scope='One authorized Qwen3-30B-A3B-FP8 smoke retry, n1 and n8 seed100, fixed settings, bounded retries only for invalid responses. No automatic reruns or scheduled monitoring.')
    save(MANIFEST, manifest)
manifest['weights'] = json.loads((STORE / 'results/net/runs/20261026-netscale-smoke-30b/weight-download-status.json').read_text())
manifest['retry_of_gpu_job'] = '25069829'
manifest['change'] = 'Validate tool-call response and JSON object arguments; retry malformed replies at most twice, log usage for each returned response. Model, task, prompts, seed, resources, CUDA12.9 and sampling settings unchanged; retries add inference calls when needed.'
import xml.etree.ElementTree as ET
tests = ET.parse(ROOT / 'tests-nibi.xml').find('.//testsuite')
assert tests is not None and int(tests.attrib['tests']) == 24 and int(tests.attrib['failures']) == int(tests.attrib['errors']) == 0
assert manifest['weights']['state']=='complete'
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
