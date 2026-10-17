"""Submit exactly the two authorized fidelity settings, with a shared lock and durable job IDs."""
import csv
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

STORE = Path('/scratch/bdong/worldseeds')
SOURCE = STORE / 'code/5fd9f30-20261017-fidelity'
COMMIT = 'b8813d2562d557874cf6d6a624a0656b99d263d8'
MANIFEST = STORE / 'results/net/submissions/20261017-fidelity-comparison.json'
MANIFEST.parent.mkdir(parents=True, exist_ok=True)
lock = open(MANIFEST.with_suffix('.lock'), 'a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
os.chdir(SOURCE)
sys.path.insert(0, str(SOURCE))
from netagents.fidelity import DEBATE, GSM8K, fetch, gsm8k


def save(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
assert not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()
base = dict(ACCOUNT='def-hup-ab_cpu', GPU_ACCOUNT='rrg-hup_gpu', STAGE='fidelity', N='50',
            GPU_RESOURCE='h100:1', GPU_CPUS='4', GPU_MEM='32G', MODEL_ID='Qwen/Qwen3-8B',
            MAX_MODEL_LEN='65536', WS_CONTEXT_TOKENS='39321', WS_CHARS_PER_TOKEN='1.5',
            NETAGENTS_PARALLEL='8', WS_STORE=str(STORE), WS_ROOT=str(SOURCE), PYTHONUNBUFFERED='1',
            WS_TEMPERATURE='0.6', WS_TOP_P='0.95', WS_TOP_K='20', TIME='0-08:00')
settings = [('A', '20261017-fid-think', dict(WS_THINKING='1', WS_TOOL_CHOICE='required', WS_MAX_TOKENS='8192')),
            ('B', '20261017-fid-nothink', dict(WS_THINKING='0', WS_TOOL_CHOICE='auto', WS_MAX_TOKENS='2048'))]
if MANIFEST.exists():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['source_commit'] == COMMIT
else:
    manifest = {'comparison': '20261017-fidelity', 'source_commit': COMMIT, 'source': str(SOURCE),
                'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'stage': 'submitting', 'jobs': [], 'expected_gpu_jobs': 2,
                'expected_questions_per_arm': 50,
                'arms': ['official-single', 'official-debate', 'port-single', 'port-debate'],
                'smoke_rerun': False, 'calibration_submitted': False,
                'scope': 'Two fidelity jobs only. No calibration, smoke rerun, or automatic retries.'}
    save(MANIFEST, manifest)

# Fetch both inputs before either submission. Every compute worker reuses these exact cached files.
for label, run, override in settings:
    root = STORE / 'results/net/runs' / run
    cache = root / 'fidelity/cache'
    cache.mkdir(parents=True, exist_ok=True)
    fetch(DEBATE, str(cache / 'debate'))
    fetch(GSM8K, str(cache))
    questions = gsm8k(50, str(cache))
    params = {**base, **override, 'RUN': run}
    provenance = {'label': label, 'source_commit': COMMIT, 'source': str(SOURCE), 'settings': params,
                  'questions_sha256': hashlib.sha256(json.dumps(questions, sort_keys=True).encode()).hexdigest(),
                  'gsm8k_sha256': hashlib.sha256((cache / 'test.jsonl').read_bytes()).hexdigest(),
                  'authors_code_sha256': hashlib.sha256((cache / 'debate/gen_gsm.py').read_bytes()).hexdigest()}
    save(root / 'experiment-settings.json', provenance)

for label, run, override in settings:
    if any(job['run'] == run for job in manifest['jobs']):
        print('Already recorded', run, flush=True)
        continue
    root = STORE / 'results/net/runs' / run
    plan = root / 'plan.tsv'
    existing = []
    if plan.exists():
        with plan.open() as f:
            existing = [row for row in csv.DictReader(f, delimiter='\t') if row['experiment'] == 'fidelity']
    assert len(existing) <= 1, 'Multiple fidelity jobs in existing plan; stop for audit'
    # If a prior submission was interrupted before its plan row was written, adopt its queued job.
    if not existing:
        jobs = subprocess.check_output(['squeue', '-u', os.environ['USER'], '-h', '-n', 'net-fidelity', '-o', '%i'], text=True)
        for job_id in jobs.split():
            details = subprocess.check_output(['scontrol', 'show', 'job', job_id, '-o'], text=True)
            if 'StdOut=' + str(root / 'logs') + '/' in details:
                existing.append({'job': job_id, 'command': 'Recovered from Slurm StdOut path'})
    assert len(existing) <= 1, 'Multiple matching queued jobs; stop for audit'
    output = ''
    if not existing:
        result = subprocess.run(['bash', 'slurm/run_all.sh'], env={**os.environ, **base, **override, 'RUN': run},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = result.stdout
        (root / 'submission-output.txt').write_text(output)
        print(output, flush=True)
        with plan.open() as f:
            existing = [row for row in csv.DictReader(f, delimiter='\t') if row['experiment'] == 'fidelity']
        assert result.returncode == 0 and len(existing) == 1, 'Submission incomplete; inspect plan before retrying'
    job_id = existing[0]['job'].split(';')[0]
    assert job_id.isdigit(), job_id
    job = {'label': label, 'run': run, 'job_id': job_id, 'results': str(root),
           'settings': {**base, **override, 'RUN': run},
           'recorded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    manifest['jobs'].append(job)
    save(MANIFEST, manifest)
    save(root / 'submission.json', {'source_commit': COMMIT, **job})
    print('RECORDED', label, job_id, flush=True)

assert len(manifest['jobs']) == 2
manifest['stage'] = 'submitted'
save(MANIFEST, manifest)
print(json.dumps(manifest, indent=2), flush=True)
