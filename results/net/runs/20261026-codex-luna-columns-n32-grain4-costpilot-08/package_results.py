"""Package the aborted Luna cost pilot; never run inference or modify raw calls."""
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'columns'
PATTERNS = [rb'sk-(?:proj-)?[A-Za-z0-9_-]{24,}', rb'gh[pousr]_[A-Za-z0-9]{30,}',
            rb'github_pat_[A-Za-z0-9_]{40,}', rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def scan(data, name):
    if name.endswith('.gz'):
        data = gzip.decompress(data)
    assert not any(re.search(p, data) for p in PATTERNS), f'Possible credential in {name}'


def main():
    assert json.loads((ROOT / 'termination.json').read_text())['status'] == 'stopped_invalid_protocol'
    with (ROOT / 'audit-console.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'audit_results.py')], stdout=log, stderr=subprocess.STDOUT, check=True)
    audit = json.loads((OUT / 'audit.json').read_text())
    assert not audit['scientifically_valid_completed_run'] and audit['completed_T'] is None
    assert not audit['accepted_nodes_without_full_ordered_chain']
    # The observed accepted chains all belong to their submitting member, so
    # their ordering can be checked within saved member histories. This does not
    # reconstruct the missing global dependency acceptance timeline.
    for evidence in audit['accepted_evidence'].values():
        assert all(hop['agent'] == evidence['agent'] for hop in evidence['chain'].values())
    raw = OUT / 'episodes'
    archive = OUT / 'codex-calls.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(raw, arcname='episodes')
    archive.with_name(archive.name + '.sha256').write_text(digest(archive.read_bytes()) + '  ' + archive.name + '\n')
    verified, raw_hashes = set(), {}
    with tarfile.open(archive) as tar:
        for member in tar:
            if not member.isfile():
                continue
            data = tar.extractfile(member).read()
            assert data == (OUT / member.name).read_bytes(), member.name
            scan(data, member.name)
            verified.add(member.name)
            raw_hashes[member.name] = {'bytes': len(data), 'sha256': digest(data)}
    assert verified == {str(p.relative_to(OUT)) for p in raw.rglob('*') if p.is_file()}
    save(ROOT / 'raw-call-hashes.json', {'files': raw_hashes, 'count': len(raw_hashes)})
    source = ROOT / 'source-f9c27c1.tar.gz'
    assert digest(source.read_bytes()) == '8447793145727b30eb98c6e5fe34aa61d5c6f91a21d86bf79c5f520f89b190e7'
    with tarfile.open(source) as tar:
        for member in tar:
            if member.isfile():
                scan(tar.extractfile(member).read(), member.name)
    selected = [p for p in ROOT.rglob('*') if p.is_file() and not p.is_relative_to(raw)
                and '__pycache__' not in p.parts and p.name not in ('artifacts.json', 'push-status.json')]
    for p in selected:
        if not p.name.endswith('.tar.gz'):
            scan(p.read_bytes(), str(p.relative_to(ROOT)))
    save(ROOT / 'verification.json', {'status': 'aborted_invalid_pilot_not_completed',
                                     'archive_files_byte_verified': len(verified),
                                     'credential_scan_matches': 0, 'source_archive_hash_verified': True,
                                     'formal_terminal_trace_available': False,
                                     'reconstructed_observation_limitations_preserved': True})
    selected = [p for p in ROOT.rglob('*') if p.is_file() and not p.is_relative_to(raw)
                and '__pycache__' not in p.parts and p.name not in ('artifacts.json', 'push-status.json')]
    files = {str(p.relative_to(ROOT)): {'bytes': p.stat().st_size, 'sha256': digest(p.read_bytes())}
             for p in sorted(selected)}
    save(ROOT / 'artifacts.json', {'status': 'aborted_invalid_pilot_not_completed',
                                  'source_commit': 'f9c27c15b5223a9cd8706ce35a8e2503491f70a5',
                                  'packaged_at_toronto': datetime.now(ZoneInfo('America/Toronto')).isoformat(),
                                  'raw_calls_in_archive': 'columns/codex-calls.tar.gz',
                                  'files': files, 'self_hash': False})
    for name, metadata in files.items():
        assert digest((ROOT / name).read_bytes()) == metadata['sha256']
    print(json.dumps({'selected_files': len(files), 'archive_files_verified': len(verified),
                      'archive_bytes': archive.stat().st_size, 'status': 'aborted_invalid_pilot'}, indent=2))


if __name__ == '__main__':
    main()
