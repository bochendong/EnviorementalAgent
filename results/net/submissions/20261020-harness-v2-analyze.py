"""Verify saved v2 outcomes and distinguish numeric errors from submission-routing failures."""
import collections
import decimal
import gzip
import hashlib
import json
import pathlib
import random
import re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPS = 20000


def paired_interval(a, b):
    differences = [int(x) - int(y) for x, y in zip(a, b)]
    rng = random.Random(1)
    draws = sorted(sum(rng.choice(differences) for _ in differences) / len(differences)
                   for _ in range(REPS))
    return [draws[int(.025 * REPS)], draws[int(.975 * REPS)]]


def numeric_match(artifact, reference):
    # Only a literal numeric artifact is evidence here; do not reinterpret a formula's last digit.
    text = str(artifact).strip()
    boxed = re.fullmatch(r'\\boxed\{([^{}]+)\}', text)
    text = (boxed[1] if boxed else text).replace(',', '').replace('$', '').rstrip('.')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
        return False
    return decimal.Decimal(text) == decimal.Decimal(reference)


def main():
    manifest = json.loads((HERE / '20261020-harness-v2-comparison.json').read_text())
    accounting = json.loads((HERE / '20261020-harness-v2-final-accounting.json').read_text())
    rows = {row.split('|')[0]: row.split('|') for row in accounting['sacct']['stdout'].splitlines()}
    summary = {'comparison': manifest['comparison'], 'source_commit': manifest['source_commit'],
               'protocol_version': 2, 'checked_at_toronto': accounting['checked_at_toronto'],
               'bootstrap': {'paired': True, 'replicates': REPS, 'seed': 1, 'method': 'percentile'},
               'jobs': [], 'raw_file_sha256': {}}
    question_sets, port_scores = [], []
    for job in manifest['jobs']:
        directory = ROOT / 'results/net/runs' / job['run']
        report = json.loads((directory / 'fidelity/debate.json').read_text())
        progress = json.loads((directory / 'fidelity/progress.json').read_text())
        diagnoses = json.loads((directory / 'fidelity/diagnosis-port-single.json').read_text())
        assert report['protocol_version'] == progress['identity']['version'] == 2
        assert report['n'] == len(diagnoses) == 50 and report['parallel'] == 8
        assert manifest['source_commit'] in (directory / 'commit.txt').read_text()
        question_sets.append(progress['identity']['questions'])
        arms = {}
        for arm in ['official-single', 'port-single']:
            records = progress['records'][arm]
            assert set(records) == {str(i) for i in range(50)}
            scores = [records[str(i)]['correct'] for i in range(50)]
            assert scores == report['per_question'][arm]
            assert sum(scores) / 50 == report['accuracy'][arm]
            assert sum(x['output_tokens'] for x in records.values()) == report['cost'][arm]['output_tokens']
            assert round(progress['seconds'][arm], 1) == report['cost'][arm]['seconds']
            arms[arm] = {'completed': 50, 'correct': sum(scores), **report['cost'][arm]}
        trace_dir = directory / 'fidelity/traces/port-single'
        assert {p.name for p in trace_dir.glob('*.gz')} == {f'q{i}.jsonl.gz' for i in range(50)}
        categories, evidence = collections.Counter(), collections.Counter()
        derived = []
        for i, diagnosis in enumerate(diagnoses):
            assert diagnosis['question'] == i
            assert diagnosis['reference'] == question_sets[-1][i]['answer']
            assert diagnosis == {'question': i, 'reference': diagnosis['reference'],
                                 **progress['records']['port-single'][str(i)]['diagnosis']}
            path = trace_dir / f'q{i}.jsonl.gz'
            with gzip.open(path, 'rt') as stream:
                events = [json.loads(line) for line in stream]
            members = next(e for e in events if e.get('kind') == 'transcripts')['members']
            assert members and all(value and 'history' in value for value in members.values())
            ops = [e for e in events if e.get('kind') == 'op']
            assert dict(collections.Counter(e['op'] for e in ops)) == diagnosis['ops']
            subs = diagnosis['submissions']
            assert len(subs) == sum(e['op'] == 'submit' for e in ops)
            solved = report['per_question']['port-single'][i]
            assert solved == diagnosis['outcome'].startswith('solved')
            if solved:
                category = 'solved'
            elif not subs:
                category = 'never_submitted'
            elif any(s['error'] == 'not equal to the answer' for s in subs):
                category = 'scored_wrong_value'
            elif all(s['error'].startswith('no key') for s in subs):
                category = 'blocked_by_missing_store_key'
            else:
                category = 'other_submission_failure'
            categories[category] += 1
            outputs = [text for member in members.values() for text in member.get('outputs', [])]
            if not solved:
                evidence['failed_with_zero_environment_ops'] += not bool(ops)
                evidence['failed_with_textual_observation'] += any('Observation:' in text for text in outputs)
                evidence['failed_with_invalid_store_key'] += any(s['error'].startswith('no key') for s in subs)
                evidence['failed_with_correct_numeric_artifact'] += any(
                    numeric_match(s['artifact'], diagnosis['reference']) for s in subs)
            evidence['accepted_normalised_submissions'] += sum(bool(s['ok'] and s['normalised']) for s in subs)
            derived.append({'question': i, 'reference': diagnosis['reference'], 'stage': category,
                            'original_outcome': diagnosis['outcome'],
                            'correct_numeric_artifact_submitted': any(
                                numeric_match(s['artifact'], diagnosis['reference']) for s in subs),
                            'actual_environment_operations': len(ops),
                            'trace': str(path.relative_to(ROOT))})
        row = rows[job['job_id']]
        assert row[1:3] == ['COMPLETED', '0:0']
        a, b = report['per_question']['port-single'], report['per_question']['official-single']
        port_scores.append(a)
        logs = {p.name: p.read_text(errors='replace') for p in (directory / 'logs').glob('*')}
        result = {**{k: job[k] for k in ['label', 'job_id', 'run']}, 'state': row[1], 'exit_code': row[2],
                  'elapsed': row[3], 'elapsed_seconds': int(row[4]), 'gpu_hours': int(row[4]) / 3600,
                  'start_toronto': row[5] + '-04:00', 'end_toronto': row[6] + '-04:00',
                  'node': row[7], 'allocated_tres': row[8], 'arms': arms,
                  'accuracy': report['accuracy'], 'harness_gap': (sum(a) - sum(b)) / 50,
                  'harness_gap_95_recomputed': paired_interval(a, b),
                  'original_outcomes': dict(collections.Counter(x['outcome'] for x in diagnoses)),
                  'failure_stages': dict(categories), 'trace_evidence': dict(evidence),
                  'verified_readable_traces': 50, 'per_question_failure_stage': derived,
                  'llm_errors_recorded': sum(x['llm_errors'] for x in diagnoses),
                  'async_cleanup_error_occurrences': sum(t.count('RuntimeError: Event loop is closed') for t in logs.values()),
                  'vllm_tool_parser_error_events': sum(t.count('Error in extracting tool call from response.') for t in logs.values())}
        (directory / 'final-status.json').write_text(json.dumps(result, indent=2) + '\n')
        for path in [*sorted((directory / 'fidelity').rglob('*')), *sorted((directory / 'logs').glob('*'))]:
            if path.is_file() and 'cache' not in path.parts:
                summary['raw_file_sha256'][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        summary['jobs'].append(result)
    assert question_sets[0] == question_sets[1] == question_sets[2]
    summary['same_questions_all_three'] = True
    summary['total_h100_gpu_hours'] = sum(j['gpu_hours'] for j in summary['jobs'])
    summary['port_pairwise'] = {
        'H1_minus_H2': {'difference': (sum(port_scores[0]) - sum(port_scores[1])) / 50,
                         'ci95': paired_interval(port_scores[0], port_scores[1])},
        'H2_minus_H3': {'difference': (sum(port_scores[1]) - sum(port_scores[2])) / 50,
                         'ci95': paired_interval(port_scores[1], port_scores[2])}}
    (HERE / '20261020-harness-v2-final-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({j['label']: {k: j[k] for k in ['accuracy', 'failure_stages', 'trace_evidence',
                                                    'harness_gap_95_recomputed', 'gpu_hours']}
                      for j in summary['jobs']}, indent=2))


if __name__ == '__main__':
    main()
