"""Audit an aborted cost pilot from saved CLI receipts and host observations.

No inference. Native run_one only saves its formal trace after returning, so an
aborted run has no final row or full trace. Host observations below are deduplicated
from original saved member conversations, not a fabricated terminal result.
"""
from collections import Counter
from pathlib import Path
import gzip
import hashlib
import json
import re
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    with tempfile.TemporaryDirectory(prefix='luna-aborted-audit-') as tmp:
        src = ROOT / 'source-f9c27c1.tar.gz'
        assert hashlib.sha256(src.read_bytes()).hexdigest() == '8447793145727b30eb98c6e5fe34aa61d5c6f91a21d86bf79c5f520f89b190e7'
        with tarfile.open(src) as archive:
            archive.extractall(tmp, filter='data')
        sys.path.insert(0, tmp)
        from netagents.codex_cli_model import audit as transport_audit
        from worldseeds.net.providers.dag import gen, hidden
        out = ROOT / 'columns'
        cfg = json.loads((out / 'config.json').read_text())
        assert (cfg['model'], cfg['reasoning_effort'], cfg['sizes'], cfg['seeds'], cfg['grains']) == ('gpt-6-luna', 'high', [32], [100], [4])
        assert cfg['git_commit'] == 'f9c27c15b5223a9cd8706ce35a8e2503491f70a5'
        assert cfg['design'] == 'peers-columns'
        ep = out / 'episodes/peers-columns-fixed-g4-n32-seed100'
        good, failed = Counter(), Counter()
        success_count = 0
        no_receipt, invalid, failed_receipts = [], [], []
        calls, observations = {}, {}
        for directory in sorted((ep / 'calls').glob('*/*')):
            if not directory.is_dir():
                continue
            log = []
            if (directory / 'events.jsonl').exists():
                for line in (directory / 'events.jsonl').read_text().splitlines():
                    try:
                        log.append(json.loads(line))
                    except ValueError:
                        pass  # killed CLI may leave one partial line; retain original
            receipts = [e['usage'] for e in log if e.get('type') == 'turn.completed']
            metadata = directory / 'metadata.json'
            if metadata.exists():
                receipt = transport_audit(log)
                assert len(receipts) == 1
                assert json.loads(metadata.read_text())['usage'] == receipt
                good.update(receipt)
                success_count += 1
            else:
                for receipt in receipts:
                    failed.update(receipt)
                if receipts:
                    failed_receipts.append(str(directory.relative_to(ROOT)))
                else:
                    no_receipt.append(str(directory.relative_to(ROOT)))
            for e in log:
                item = e.get('item', {})
                if item.get('type') not in (None, 'reasoning', 'agent_message'):
                    invalid.append({'path': str(directory.relative_to(ROOT)), 'event_type': e.get('type'),
                                    'type': item['type'], 'server': item.get('server'), 'tool': item.get('tool')})
            prompt = directory / 'prompt.txt'
            if not prompt.exists():
                continue
            data = json.loads(prompt.read_text().split('\n', 1)[1])
            for item in data['conversation']:
                if not isinstance(item, dict) or 'call_id' not in item:
                    continue
                dest = calls if item.get('type') == 'function_call' else observations if item.get('type') == 'function_call_output' else None
                if dest is not None:
                    cid = item['call_id']
                    assert cid not in dest or dest[cid] == item
                    dest[cid] = item
        events, unreadable_observations = [], []
        for cid, item in observations.items():
            assert cid in calls
            match = re.fullmatch(r'call_(a\d+)_(\d+)_[0-9a-f]+', cid)
            assert match
            call = calls[cid]
            try:
                obs = json.loads(item['output'])
            except ValueError as error:
                unreadable_observations.append({'call_id': cid, 'op': call['name'], 'error': str(error), 'note': 'Original saved tool output was truncated; not reconstructed or rewritten.'})
                continue
            events.append({'call_id': cid, 'agent': match[1], 'decision_index': int(match[2]),
                           'op': call['name'], 'args': json.loads(call['arguments']), 'obs': obs})
        # Budgets are per member; free operations may repeat a budget value.
        # Decision indices preserve each member's chronology, but cannot replace
        # the missing global trace after tool-validation errors or aborted turns.
        has_budget = False
        events.sort(key=lambda e: (e['decision_index'], int(e['agent'][1:])))
        tasks = {t['id']: t for t in gen(100, 16, 4, grain=4)}
        chains = {}
        for tid, task in tasks.items():
            xs = [task['start']]
            for _ in range(4):
                xs.append(hidden(100, tid, xs[-1], task['salt']))
            chains[tid] = xs
        accepted, hops, store = {}, {k: {} for k in tasks}, {}
        ops, apply_pairs, rejected = Counter(), Counter(), Counter()
        violations, wrong_inputs, missing, early, evidence = [], [], [], [], {}
        for i, e in enumerate(events):
            op, args, obs = e['op'], e['args'], e['obs']
            ops[op] += 1
            if op in ('apply', 'submit'):
                tid = args.get('task', '')
                owner = 'a0' if tid == 'FINAL' else 'a' + tid.rsplit('.', 1)[-1]
                if owner != e['agent']:
                    violations.append(e)
            if op == 'put' and obs.get('ok'):
                store[args['key']] = args['value']
            if op == 'apply' and obs.get('ok'):
                tid = args['task']
                apply_pairs[(tid, obs['x'])] += 1
                xs = chains[tid]
                matches = [k for k in range(4) if (obs['x'], obs['f(x)']) == (xs[k], xs[k + 1])]
                if not matches:
                    wrong_inputs.append(e)
                else:
                    k = matches[0]
                    if k == 0 or k - 1 in hops[tid]:
                        hops[tid].setdefault(k, {'observation_index': i, 'agent': e['agent'], 'input': obs['x'], 'output': obs['f(x)']})
                    if has_budget and any(p not in accepted for p in tasks[tid]['deps']):
                        early.append(e)
            if op == 'submit':
                if not obs.get('ok'):
                    rejected[obs.get('error', 'unknown')] += 1
                    continue
                tid = args['task']
                value = args.get('artifact')
                if value in (None, ''):
                    value = store[args.get('store_key') or args.get('key')]
                assert re.fullmatch(r'-?\d+', str(value).strip())
                assert int(value) == int(tasks[tid]['answer'])
                assert tid not in accepted
                if has_budget:
                    assert all(p in accepted for p in tasks[tid]['deps'])
                if len(hops[tid]) != 4:
                    missing.append(tid)
                accepted[tid] = int(value)
                evidence[tid] = {'agent': e['agent'], 'chain': hops[tid], 'observation_index': i}
        progress = json.loads((ep / 'progress.json').read_text())
        all_known = good + failed
        for c in (good, failed, all_known):
            c['total_tokens'] = c['input_tokens'] + c['output_tokens']
        usage = {'successful_requests': success_count, 'successful_usage': dict(good), 'failed_receipted_usage': dict(failed),
                 'all_receipted_usage_totals': dict(all_known), 'attempts_without_receipt': no_receipt,
                 'failed_attempts_with_receipts': failed_receipts,
                 'counting': 'Input+output. Cached input and reasoning output are subsets. Each saved original attempt once. Failed and killed requests without receipts unknown. No historical/development/chat usage.'}
        report = {'status': 'stopped_invalid_protocol', 'scientifically_valid_completed_run': False, 'completed_T': None,
                  'model': cfg['model'], 'seed': 100, 'expected_tasks': 65, 'observed_accepted_tasks': len(accepted),
                  'final_accepted': 'FINAL' in accepted, 'observed_native_operations_with_outputs': len(events),
                  'progress_operation_count': sum(progress['operations'].values()), 'observed_ops': dict(ops),
                  'global_order_verified_by_budget': has_budget, 'accepted_evidence': evidence,
                  'unreadable_saved_observations': unreadable_observations,
                  'accepted_nodes_without_full_ordered_chain': missing, 'wrong_input_applies': wrong_inputs,
                  'duplicate_applies': sum(v - 1 for v in apply_pairs.values()), 'rejected_submissions': dict(rejected),
                  'valid_applies_before_parent_acceptance': early, 'column_execution_violations': violations,
                  'forbidden_cli_events': invalid, 'context_trims': None, 'overflows': None,
                  'limits': ['Aborted before run_one returned: no formal row/full native trace/member terminal reports. Host observations reconstructed from saved conversations and may omit final unobserved outputs.',
                             'This is invalid/aborted exploratory cost evidence, not a completed prediction test or a normal Luna cost benchmark.',
                             'Global parent-acceptance chronology cannot be fully checked without the terminal native trace. Ordered chain evidence uses saved per-member decision order.',
                             'Context trim/overflow terminal counters unavailable. Shared rounded subscription percent does not isolate experiment cost.']}
        with gzip.open(out / 'reconstructed-host-observations.jsonl.gz', 'wt') as f:
            for e in events:
                f.write(json.dumps(e) + '\n')
        save(out / 'usage.json', usage)
        save(out / 'audit.json', report)
        print(json.dumps({'accepted_tasks': len(accepted), 'chain_missing': missing, 'known_tokens': all_known['total_tokens'],
                          'success_requests': success_count, 'failed_known_tokens': failed['total_tokens'], 'unknown_attempts': len(no_receipt),
                          'observed_ops': dict(ops), 'budget_order': has_budget, 'column_violations': len(violations),
                          'duplicate_applies': report['duplicate_applies'], 'wrong_inputs': len(wrong_inputs), 'rejections': sum(rejected.values())}, indent=2))


if __name__ == '__main__':
    main()
