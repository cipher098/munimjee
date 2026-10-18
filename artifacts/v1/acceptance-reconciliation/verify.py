"""Metadata-only verifier: immutable Git blobs/row coverage, never app imports/IO."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[3]
DATA=ROOT/'artifacts/v1/acceptance-reconciliation/reconciliation.json'
def blob(commit,path):return subprocess.check_output(['git','show',commit+':'+path],cwd=ROOT)
def main():
 data=json.loads(DATA.read_text());base=data['reviewed_central_commit']
 historical=json.loads(blob(base,'artifacts/v1/release-audit/acceptance-matrix.json'))
 rows=data['rows'];assert len(rows)==58 and len({r['id'] for r in rows})==58
 assert {r['id'] for r in rows}=={r['id'] for r in historical['rows']}
 assert len([r for r in rows if r['id'].startswith('V')])==13
 assert len([r for r in rows if r['id'].startswith('A')])==23
 assert len(data['original_plan_journeys'])==23 and len(data['supplement15_reconciliation'])==15
 assert data['release_ready'] is False and data['counts_must_not_be_summed'] is True
 assert data['isolated0057']['part_of_reviewed_central'] is False
 inventory=data['scoped_pilot_source_inventory']
 assert hashlib.sha256((ROOT/inventory['path']).read_bytes()).hexdigest()==inventory['sha256']
 for row in rows:
  assert row['classification'] in data['classification_definitions'] and row['references']
  for key in row['references']:assert key in data['references']
 mismatches=[]
 for key,ref in data['references'].items():
  actual=blob(ref['commit'],ref['path'])
  if hashlib.sha256(actual).hexdigest()!=ref['sha256']:mismatches.append(key)
  if ref['anchor']:assert ref['anchor'] in actual.decode(errors='replace').splitlines()[ref['line']-1]
 assert not mismatches
 result={'format':'munimjee.v1.acceptance-reconciliation-verification.v1','reviewed_central_commit':base,'rows':58,'outcomes':13,'journeys':23,'supplement_items':15,'references_checked':len(data['references']),'reference_hash_mismatches':mismatches,'scope':'Metadata/source-evidence integrity only; zero product/DB/browser/provider/container/hostedCI tests or calls.','release_ready':False,'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [DATA,Path(__file__),ROOT/'docs/v1-acceptance-reconciliation.md',ROOT/'artifacts/v1/acceptance-reconciliation/pilot-source-inventory.json']}}
 (DATA.parent/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
