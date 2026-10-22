"""Offline development example; excluded from formal pilot results and model usage.

Use the same free task-graph/start metadata as the scripted reference. Never read
task answer fields. Reuse only outputs actually returned by the public apply tool.
"""
from pathlib import Path
import gzip
import json
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
SNAPSHOT = tempfile.TemporaryDirectory(prefix='dag-bound-audit-')
with tarfile.open(ROOT / 'source-cb69623.tar.gz') as source:
    source.extractall(SNAPSHOT.name, filter='data')
sys.path.insert(0, SNAPSHOT.name)
from netagents.scaling import make_env

env = make_env(16, 4, 1, 1, grain=4)
known, cache, saved = {}, {}, []
for tid, task in env.provider.raw.items():
    x = sum(known[d] for d in task['deps']) % 1000 if task['deps'] else task['start']
    for step in range(4):
        key = (tid, x)
        if key in cache:
            saved.append({'task': tid, 'step': step + 1, 'input': x, 'reused_output': cache[key]})
            x = cache[key]
        else:
            obs = env.step('a0', 'apply', {'task': tid, 'x': x})
            assert obs['ok']
            cache[key] = obs['f(x)']
            x = obs['f(x)']
    assert env.step('a0', 'submit', {'task': tid, 'artifact': str(x)})['ok']
    known[tid] = x

assert env.solved and env.round == 324 and len(saved) == 1
report = {'purpose': 'Development seed 1 only, excluded from formal results. No model inference.',
          'grain': 4, 'claimed_lower_bound': 325,
          'memoized_public_oracle_solver_steps': env.round, 'solved': env.solved,
          'correctly_accepted_tasks': env.metrics()['done'], 'saved_apply_calls': saved,
          'limitation': 'The current verifier accepts matching integers without enforcing grain oracle calls. Repeated inputs can reuse known f(x), so the stated W is a procedural work model, not a strict bound for every strategy.'}
(ROOT / 'development-bound-audit.json').write_text(json.dumps(report, indent=2) + '\n')
with gzip.open(ROOT / 'development-bound-audit.trace.jsonl.gz', 'wt') as stream:
    for event in env.events:
        stream.write(json.dumps(event) + '\n')
print(json.dumps(report, indent=2))
