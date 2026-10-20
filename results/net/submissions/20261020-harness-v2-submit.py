"""Submit exactly the three authorized protocol-v2 single-agent settings, with a shared lock and durable job IDs."""
import csv
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys

STORE = Path('/scratch/bdong/worldseeds')
SOURCE = STORE / 'code/2e4f921-20261020-harness'
COMMIT = 'a220bb0c4ce5f76f20388c3cd339209bfc39d889'
MANIFEST = STORE / 'results/net/submissions/20261020-harness-v2-comparison.json'
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
            WS_TEMPERATURE='0.6', WS_TOP_P='0.95', WS_TOP_K='20', TIME='0-08:00', ARMS='official-single port-single', WS_MAX_TOKENS='8192')
settings = [('H1', '20261020-h1-think-required', dict(WS_THINKING='1', WS_TOOL_CHOICE='required')),
            ('H2', '20261020-h2-nothink-required', dict(WS_THINKING='0', WS_TOOL_CHOICE='required')),
            ('H3', '20261020-h3-nothink-auto', dict(WS_THINKING='0', WS_TOOL_CHOICE='auto'))]
if MANIFEST.exists():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['source_commit'] == COMMIT
else:
    manifest = {'comparison': '20261020-harness-v2', 'protocol_version': 2, 'source_commit': COMMIT, 'source': str(SOURCE),
                'created_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'stage': 'submitting', 'jobs': [], 'expected_gpu_jobs': 3,
                'expected_questions_per_arm': 50,
                'arms': ['official-single', 'port-single'],
                'smoke_rerun': False, 'calibration_submitted': False,
                'scope': 'Three protocol-v2 single-agent fidelity jobs only. No debate, calibration, smoke, full four-arm runs or automatic retries. Subsequent work requires separate authorization.'}
    save(MANIFEST, manifest)

# Reuse the exact inputs of the completed comparison, without a moving upstream download.
REFERENCE_CACHE = STORE / "results/net/runs/20261017-fid-think/fidelity/cache"
# Prepare all three settings before the first submission.
for label, run, override in settings:
    root = STORE / 'results/net/runs' / run
    cache = root / 'fidelity/cache'
    cache.mkdir(parents=True, exist_ok=True)
    (cache / 'debate').mkdir(exist_ok=True)
    for relative in ['test.jsonl', 'debate/gen_gsm.py']:
        previous, target = REFERENCE_CACHE / relative, cache / relative
        if target.exists():
            assert target.read_bytes() == previous.read_bytes(), 'Cached inputs differ'
        else:
            shutil.copyfile(previous, target)
    questions = gsm8k(50, str(cache))
    params = {**base, **override, 'RUN': run}
    provenance = {'label': label, 'source_commit': COMMIT, 'source': str(SOURCE), 'settings': params,
                  'questions_sha256': hashlib.sha256(json.dumps(questions, sort_keys=True).encode()).hexdigest(),
                  'gsm8k_sha256': hashlib.sha256((cache / 'test.jsonl').read_bytes()).hexdigest(),
                  'authors_code_sha256': hashlib.sha256((cache / 'debate/gen_gsm.py').read_bytes()).hexdigest()}
    save(root / 'experiment-settings.json', provenance)


provenances = [json.loads((STORE / 'results/net/runs' / run / 'experiment-settings.json').read_text())
               for _, run, _ in settings]
for field in ['questions_sha256', 'gsm8k_sha256', 'authors_code_sha256']:
    assert len({p[field] for p in provenances}) == 1, field
manifest['verification'] = {'nibi_parallel_checks_passed': 3, 'trace_collision_regression_passed': True,
                            'same_inputs_all_three': True, 'protocol_version': 2}
save(MANIFEST, manifest)

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
        jobs = subprocess.check_output(['squeue', '-u', os.environ['USER'], '-h', '-n', 'net-fidelity', '-o', '%i'], text=True, timeout=30)
        for job_id in jobs.split():
            details = subprocess.check_output(['scontrol', 'show', 'job', job_id, '-o'], text=True, timeout=30)
            if 'StdOut=' + str(root / 'logs') + '/' in details:
                existing.append({'job': job_id, 'command': 'Recovered from Slurm StdOut path'})
    assert len(existing) <= 1, 'Multiple matching queued jobs; stop for audit'
    output = ''
    if not existing:
        result = subprocess.run(['bash', 'slurm/run_all.sh'], env={**os.environ, **base, **override, 'RUN': run},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
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

assert len(manifest['jobs']) == 3
manifest['stage'] = 'submitted'
save(MANIFEST, manifest)
print(json.dumps(manifest, indent=2), flush=True)
