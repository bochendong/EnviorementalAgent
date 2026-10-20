"""Reproduce the completed A/B comparison from saved checkpoints; no model calls."""
import collections
import hashlib
import json
import pathlib
import random
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
ARMS = ('official-single', 'official-debate', 'port-single', 'port-debate')
REPS, SEED = 20000, 1


def interval(a, b):
    differences = [int(x) - int(y) for x, y in zip(a, b)]
    rng = random.Random(SEED)
    samples = sorted(sum(rng.choice(differences) for _ in differences) / len(differences)
                     for _ in range(REPS))
    return [samples[int(.025 * REPS)], samples[int(.975 * REPS)]]


def main():
    manifest = json.loads((HERE / '20261017-fidelity-comparison.json').read_text())
    accounting = json.loads((HERE / '20261017-fidelity-final-accounting.json').read_text())
    output = {'comparison': manifest['comparison'], 'source_commit': manifest['source_commit'],
              'checked_at_toronto': accounting['checked_at_toronto'],
              'bootstrap': {'paired': True, 'replicates': REPS, 'seed': SEED,
                            'method': 'percentile; sorted samples at indices 500 and 19500'},
              'jobs': [], 'raw_file_sha256': {}}
    identities = []
    for job in manifest['jobs']:
        directory = ROOT / 'results/net/runs' / job['run']
        progress = json.loads((directory / 'fidelity/progress.json').read_text())
        report = json.loads((directory / 'fidelity/debate.json').read_text())
        assert len(progress['identity']['questions']) == report['n'] == 50
        assert report['parallel'] == 8
        assert manifest['source_commit'] in (directory / 'commit.txt').read_text()
        identities.append(progress['identity']['questions'])
        arms = {}
        for arm in ARMS:
            records = progress['records'][arm]
            assert set(records) == {str(i) for i in range(50)}, (job['label'], arm)
            scores = [records[str(i)]['correct'] for i in range(50)]
            assert all(isinstance(value, bool) for value in scores)
            assert scores == report['per_question'][arm]
            assert sum(scores) / 50 == report['accuracy'][arm]
            assert sum(r['output_tokens'] for r in records.values()) == report['cost'][arm]['output_tokens']
            assert round(progress['seconds'][arm], 1) == report['cost'][arm]['seconds']
            assert sum(r['seconds'] for r in records.values()) == report['cost'][arm]['question_seconds']
            arms[arm] = {'completed': 50, 'correct': sum(scores),
                         'accuracy': sum(scores) / 50, **report['cost'][arm]}
        rows = accounting[job['job_id']]['sacct']['stdout'].strip().splitlines()
        row = next(line.split('|') for line in rows if line.split('|')[0] == job['job_id'])
        assert row[1:3] == ['COMPLETED', '0:0']
        a, b = report['per_question']['port-single'], report['per_question']['official-single']
        log = (directory / 'logs' / ('net-fidelity-' + job['job_id'] + '.out')).read_text()
        vllm = (directory / 'logs' / ('vllm-' + job['job_id'] + '.log')).read_text()
        result = {'label': job['label'], 'job_id': job['job_id'], 'run': job['run'],
                  'settings': progress['identity']['settings'], 'state': row[1], 'exit_code': row[2],
                  'elapsed': row[3], 'elapsed_seconds': int(row[4]),
                  'start_toronto': row[5] + '-04:00', 'end_toronto': row[6] + '-04:00',
                  'node': row[7], 'allocated_tres': row[8], 'gpu_hours': int(row[4]) / 3600,
                  'all_four_arms_complete_and_consistent': True, 'arms': arms,
                  'port_minus_official_single': {
                      'difference': (sum(a) - sum(b)) / 50, 'paired_bootstrap_95': interval(a, b),
                      'port_only_correct': sum(x and not y for x, y in zip(a, b)),
                      'official_only_correct': sum(y and not x for x, y in zip(a, b))},
                  'official_debate_gain': report['official_gain'],
                  'port_debate_gain': report['port_gain'],
                  'original_gain_only_gate': report['port_gain_within_official_interval'],
                  'recorded_total_output_tokens': sum(v['output_tokens'] for v in arms.values()),
                  'arm_wall_seconds_sum': sum(progress['seconds'].values()),
                  'log_diagnostics': {
                      'async_cleanup_runtimeerror_occurrences': log.count('RuntimeError: Event loop is closed'),
                      'tool_parser_error_events': vllm.count('Error in extracting tool call from response.'),
                      'non_200_logged_completion_http_statuses': dict(collections.Counter(
                          re.findall(r'POST /v1/chat/completions HTTP/1\.1" (?!200)(\d{3})', vllm)))}}
        (directory / 'final-status.json').write_text(json.dumps(result, indent=2) + '\n')
        for path in [directory / 'fidelity/progress.json', directory / 'fidelity/debate.json',
                     *sorted((directory / 'logs').glob('*'))]:
            output['raw_file_sha256'][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        output['jobs'].append(result)
    assert identities[0] == identities[1]
    output['same_50_questions_in_both_settings'] = True
    output['total_h100_gpu_hours'] = sum(j['gpu_hours'] for j in output['jobs'])
    (HERE / '20261017-fidelity-final-summary.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({j['label']: {'accuracy': {a: v['accuracy'] for a, v in j['arms'].items()},
                                  'gap': j['port_minus_official_single'], 'gpu_hours': j['gpu_hours']}
                      for j in output['jobs']}, indent=2))


if __name__ == '__main__':
    main()
