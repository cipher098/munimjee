"""Independent saved-evidence integrity checks. No app import, DB, Docker or network.

These tests verify scope coverage and provenance of historical evidence. They do
not rerun product journeys and must never be reported as product acceptance.
Run: python3 -m unittest discover -s backend/tests -p test_v1_release_audit_evidence.py -v
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / 'artifacts/v1/release-audit'
APP = 'dd36b0dab568684d6c8ee6c66d47e27a76b9fca4'
BACKEND = '257b2733e5f7f61e2d3d9ed971a55a5f7a96fd94'


def read(path):
    return json.loads((ROOT / path).read_text())


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def xml_counts(path):
    doc = ET.parse(ROOT / path).getroot()
    cases = list(doc.iter('testcase'))
    return {'tests': len(cases),
            'passed': sum(t.find('skipped') is None and t.find('failure') is None and t.find('error') is None for t in cases),
            'skipped': sum(t.find('skipped') is not None for t in cases),
            'failed': sum(t.find('failure') is not None for t in cases),
            'errors': sum(t.find('error') is not None for t in cases)}


class SavedEvidenceAudit(unittest.TestCase):
    def test_scope_covers_every_agreed_outcome_acceptance_gate_and_migration(self):
        matrix = read('artifacts/v1/release-audit/acceptance-matrix.json')
        plan = (ROOT / 'go-live-plan.md').read_text()
        expected_outcomes = set(re.findall(r'^\| (V\d{2}) \|', plan, re.M))
        expected_gates = set(re.findall(r'^\| (G\d) ', plan, re.M))
        section = plan.split('### Actual product acceptance matrix', 1)[1].split('Agent browser testing', 1)[0]
        expected_acceptance = [line.split('|')[1].strip() for line in section.splitlines()
                               if line.startswith('| ') and not line.startswith(('| Test ', '| ---'))]
        rows = matrix['rows']
        self.assertEqual(expected_outcomes, {r['id'] for r in rows if r['group'] == 'outcome'})
        self.assertEqual(expected_gates, {r['id'] for r in rows if r['group'] == 'gate'})
        self.assertEqual(expected_acceptance, [r['requirement'] for r in rows if r['group'] == 'acceptance'])
        self.assertEqual({f'M{i:02}' for i in range(1, 11)}, {r['id'] for r in rows if r['group'] == 'migration_rollback'})
        self.assertEqual(len(rows), len({r['id'] for r in rows}))
        self.assertFalse(matrix['release_ready'])
        self.assertTrue(matrix['counts_overlap_and_must_not_be_summed'])
        for row in rows:
            self.assertTrue(row['remaining'], row['id'])
            self.assertFalse(row['acceptance_complete'], row['id'])
            self.assertTrue(row['source_refs'], row['id'])
            self.assertTrue(row['evidence_refs'], row['id'])
            self.assertTrue(row.get('test_refs') or row.get('test_gap'), row['id'])
            self.assertTrue(set(row['dispositions']) <= set(matrix['disposition_definitions']), row['id'])

    def test_exact_references_exist_at_the_audited_application_and_hash(self):
        matrix = read('artifacts/v1/release-audit/acceptance-matrix.json')
        for key, ref in matrix['references'].items():
            path = ref['path']
            self.assertFalse(Path(path).is_absolute(), key)
            self.assertNotIn('..', Path(path).parts, key)
            # Historical source stays pinned when release composition changes current files.
            if ref['kind'] == 'saved_evidence':
                # The matrix explicitly records this historical artifact snapshot.
                # Current status/docs may advance without rewriting that evidence.
                snapshot = ref['saved_artifact_snapshot']
                self.assertRegex(snapshot, r'^[0-9a-f]{40}$', key)
                body = git('show', f'{snapshot}:{path}')
            else:
                body = git('show', f"{ref['source_commit']}:{path}")
            self.assertEqual(digest(body), ref['sha256'], key)
            if ref['anchor']:
                self.assertIn(ref['anchor'], body.decode().splitlines()[ref['line'] - 1], key)
        for row in matrix['rows']:
            for key in row['source_refs'] + row['evidence_refs'] + row.get('test_refs', []):
                self.assertIn(key, matrix['references'], row['id'])

    def test_full_saved_xml_and_console_count_and_skip_categories(self):
        path = 'artifacts/v1/integration/wave4/full.xml'
        self.assertEqual(xml_counts(path), {'tests': 1425, 'passed': 1417, 'skipped': 8, 'failed': 0, 'errors': 0})
        console = (ROOT / 'artifacts/v1/integration/wave4/full.txt').read_text()
        self.assertRegex(console, r'1417 passed, 8 skipped.*541\.55s')
        cases = ET.parse(ROOT / path).getroot().iter('testcase')
        skips = [t.find('skipped').attrib['message'] for t in cases if t.find('skipped') is not None]
        self.assertEqual(sum('cassette' in x.lower() for x in skips), 5)
        self.assertEqual(sum('TEST_REDIS_URL' in x for x in skips), 3)
        self.assertEqual(git('diff', BACKEND, APP, '--', 'backend/app', 'backend/alembic'), b'')
        # Test/browser changes do exist; never broaden the empty app/migration claim.
        self.assertNotEqual(git('diff', BACKEND, APP, '--', 'backend/tests'), b'')

    def test_final_gate_and_native_source_hashes_match_actual_blobs(self):
        gates = read('artifacts/v1/integration/wave4/final-gates.json')
        self.assertEqual(gates['application_source'], APP)
        self.assertEqual(gates['backend_full_source'], BACKEND)
        self.assertEqual(gates['actual_migration_head'], '0050_v1_assistance')
        self.assertEqual(gates['mounted_browser_checks'], {
            'assistance': 37, 'independent_payment_settings': 36, 'native_import_allocation': 47,
            'persisted_all_three_themes_and_COD': 29, 'independent_native_recovery': 30, 'parcel_review': 20})
        records = [(gates['source_sha256'], APP)]
        native = read('artifacts/v1/integration/wave4/native-mounted-browser.txt')
        self.assertEqual((native['checks'], native['physical_device'], native['external_requests']), (29, False, []))
        records.append((native['source_hashes'], native['source_head']))
        payment = read('artifacts/v1/integration/wave4/payment-settings-mounted-review.json')
        self.assertEqual((payment['native_browser_checks'], payment['actual_page_route_count'], payment['fixture_fallback_used']), (36, 1, False))
        records.append((payment['source_sha256'], payment['source_head']))
        recovery = read('artifacts/v1/integration/wave4/native-recovery-mounted-source.json')
        self.assertEqual((recovery['actual_migration_head'], recovery['checks']), ('0050_v1_assistance', 30))
        records.append((recovery['hashes'], recovery['source_commit']))
        for hashes, commit in records:
            for path, expected in hashes.items():
                # Product source and a later evidence-only screenshot harness have separate commits.
                actual_commit = '47b1b83103ef7c7728ec350c4cc415d27f235ca2' if path == 'backend/tests/browser/import_workspace_native.mjs' else commit
                self.assertEqual(digest(git('show', f'{actual_commit}:{path}')), expected, path)
                # Current source may legitimately change after this frozen historical audit.
                # Its acceptance must be refreshed separately, never inferred from this record.
        # Explicitly verify printed stale 0049 label remains historical, not migrated evidence.
        self.assertIn('0049', (ROOT / 'artifacts/v1/integration/wave4/native-recovery-mounted.txt').read_text())
        self.assertEqual(recovery['actual_migration_head'], '0050_v1_assistance')

    def test_saved_runtime_manifest_matches_286_source_files_without_rebuilding_image(self):
        manifest = read('artifacts/v1/runtime-package/wave4-final-manifest.json')
        self.assertEqual(manifest['source_revision'], APP)
        self.assertEqual(len(manifest['files']), 286)
        self.assertEqual(sum(p.startswith('backend/static/') for p in manifest['files']), 51)
        self.assertEqual(sum(p.startswith('storefront-src/') for p in manifest['files']), 13)
        for name, expected in manifest['files'].items():
            self.assertFalse(any(p.lower() in {'tests', 'uploads', 'keys', 'node_modules', 'artifacts', '.git', '.venv'} or p.startswith('.env') for p in Path(name).parts), name)
            source = ('deploy/v1/Dockerfile' if name == 'Dockerfile' else
                      'frontend/storefront/src/' + Path(name).name if name.startswith('storefront-src/') else name)
            if name == 'requirements.txt':
                lines = git('show', f'{APP}:backend/requirements.txt').decode().splitlines()
                lines = [line for line in lines if line.strip() and not line.startswith('#') and
                         re.match(r'([A-Za-z0-9_-]+)', line)[1].lower() not in {'pytest', 'pytest-asyncio', 'vcrpy'}]
                body = ('\n'.join(lines) + '\n').encode()
            else:
                body = git('show', f'{APP}:{source}')
            self.assertEqual(digest(body), expected, name)
        image = read('artifacts/v1/runtime-package/wave4-final-image-verification.json')
        self.assertEqual((image['source_revision'], image['architecture'], image['user']), (APP, 'arm64', '10001:10001'))
        self.assertFalse(image['deployment'])
        self.assertEqual(image['offline_modes_passed'], 3)

    def test_every_referenced_saved_test_is_present_and_passed_in_historical_xml(self):
        matrix = read('artifacts/v1/release-audit/acceptance-matrix.json')
        cases = list(ET.parse(ROOT / 'artifacts/v1/integration/wave4/full.xml').getroot().iter('testcase'))
        for ref in matrix['references'].values():
            if ref['kind'] != 'test':
                continue
            matches = [t for t in cases if t.attrib['classname'] == 'tests.' + Path(ref['path']).stem and
                       t.attrib['name'].split('[')[0] == ref['test_name']]
            self.assertTrue(matches, ref['test_name'])
            for case in matches:
                self.assertIsNone(case.find('skipped'), ref['test_name'])
                self.assertIsNone(case.find('failure'), ref['test_name'])
                self.assertIsNone(case.find('error'), ref['test_name'])


if __name__ == '__main__':
    unittest.main()
