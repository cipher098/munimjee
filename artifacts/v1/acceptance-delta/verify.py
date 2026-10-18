"""Read-only frozen-source and acceptance-delta integrity verification; no app imports."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(__file__).with_name('inventory.json')

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def verify():
    manifest = json.loads(DATA.read_text())
    frozen = manifest['frozen_source']
    assert git('rev-parse', frozen).decode().strip() == frozen
    assert manifest['release_ready'] is False
    for key, ref in manifest['source_refs'].items():
        path = Path(ref['path'])
        assert not path.is_absolute() and '..' not in path.parts, key
        body = git('show', f"{ref['source_commit']}:{path.as_posix()}")
        assert hashlib.sha256(body).hexdigest() == ref['sha256'], key
        if ref['anchor']:
            assert ref['anchor'] in body.decode().splitlines()[ref['line'] - 1], key
    matrix = json.loads(git('show', f'{frozen}:artifacts/v1/release-audit/acceptance-matrix.json'))
    rows = {r['id'] for r in matrix['rows']}
    assert len(rows) == manifest['historical_rows_unchanged'] == 58
    assert len({item['id'] for item in manifest['items']}) == len(manifest['items'])
    assert set(manifest['coverage']) == rows
    for item in manifest['items']:
        assert item['owner'] and item['acceptance_criteria'] and item['independently_safe_next_work']
        assert item['remaining_external_or_operational_gate'] and item['acceptance_complete'] is False
        assert set(item['source_refs']) <= set(manifest['source_refs'])
        assert set(item['acceptance_rows']) <= rows
    for row in rows:
        assert manifest['coverage'][row] == [i['id'] for i in manifest['items'] if row in i['acceptance_rows']]
        assert manifest['coverage'][row]
    report = manifest['local_report']
    assert report['analytics_short_commit'] == '3556850'
    assert all(report[k] is False for k in ('object_available','source_inspected','fetched','integrated_into_frozen_source'))
    doc = (ROOT/'docs/v1-acceptance-delta.md').read_text()
    for required in ('0053 → 0052', 'document UUID + product_ref', 'actual supported legacy URL inventory', 'not release-ready'):
        assert required in doc, required
    return {'status':'passed', 'frozen_source':frozen, 'checks':{'immutable_source_hashes_and_anchors':len(manifest['source_refs']), 'historical_rows_covered':len(rows), 'bounded_work_items':len(manifest['items']), 'all_acceptance_complete_false':True, 'local_report_separate':True}, 'product_acceptance_executed':False, 'network_db_docker_provider_operations':False}

if __name__ == '__main__':
    print(json.dumps(verify(),indent=2))
