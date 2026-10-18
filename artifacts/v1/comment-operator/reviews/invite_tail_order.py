"""Exact route/session-helper AST proof. No application import, DB or network.

This executes current source functions with a synthetic session-stage revocation;
it proves call ordering, not actual PostgreSQL rollback semantics.
"""
import argparse,ast,asyncio,hashlib,json
from pathlib import Path
from types import SimpleNamespace as NS

parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('--expect-fixed',action='store_true');args=parser.parse_args()
path=Path(args.source);raw=path.read_bytes();tree=ast.parse(raw)
functions=[]
for node in tree.body:
    if isinstance(node,ast.AsyncFunctionDef) and node.name in {'start_session','accept_invitation'}:
        node.decorator_list=[];node.returns=None
        for arg in [*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs]:arg.annotation=None
        node.args.defaults=[ast.Constant(None) if isinstance(value,ast.Call) else value for value in node.args.defaults]
        functions.append(node)
class Denied(Exception):pass
class IntegrityError(Exception):pass
class DB:
    commits=0
    staged=False
    async def commit(self):self.commits+=1;trace.append('commit')
    async def flush(self):trace.append('flush')
    async def rollback(self):trace.append('rollback')
trace=[];db=DB()
async def accept(db,body):trace.append('domain_initial_authority_passed');db.staged=True;return NS(id='synthetic-user')
async def guard(db,token):trace.append('final_owner_denied');raise Denied('owner revoked during later session staging')
async def issue(db,user):trace.append('session_stage_owner_revoked');return 'synthetic-token','synthetic-csrf',None
async def revoke(*args):trace.append('browser_session_staged')
async def view(*args):return {'synthetic':True}
env={'domain':NS(accept_invitation=accept,reauthorize_invitation_owner=guard),'check_login_origin':lambda *args:None,
 'revoke_browser_session':revoke,'issue_session':issue,'actor_view':view,'Actor':lambda *args:NS(),
 'set_native_cookies':lambda *args:trace.append('cookies_staged'),'IntegrityError':IntegrityError,
 'HTTPException':Denied}
exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),str(path),'exec'),env)
async def run():
    try:await env['accept_invitation'](NS(token='synthetic'),NS(),NS(headers={}),db)
    except Denied:trace.append('denied_response')
asyncio.run(run())
result={'source_sha256':hashlib.sha256(raw).hexdigest(),'exact_functions':['start_session','accept_invitation'],
 'trace':trace,'commits_before_denied_response':db.commits,'proof':'source call-order only; no PostgreSQL/provider'}
print(json.dumps(result,indent=2))
assert db.commits==(0 if args.expect_fixed else 1),result
