import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../../static/v1_client.js',import.meta.url),'utf8');
test('shared native transport preserves a valid absent storefront and can then save it',async()=>{
  const requests=[], responses=[{ok:true,data:null},{ok:true,data:{csrf_token:'bound-csrf'}},{ok:true,data:{slug:'new-shop'}}];
  const context={window:{},fetch:async(path,options)=>{requests.push({path,options});const next=responses.shift();return {ok:next.ok,json:async()=>next.data};}};
  vm.runInNewContext(source,context);
  assert.equal(await context.window.V1.api('/api/v1/businesses/synthetic/catalogue/storefront'),null);
  await context.window.V1.session();
  const result=await context.window.V1.api('/api/v1/businesses/synthetic/catalogue/storefront',{method:'PUT',body:{slug:'new-shop'}});
  assert.equal(result.slug,'new-shop');
  assert.equal(requests[2].options.headers['X-CSRF-Token'],'bound-csrf');
  assert.equal(requests[2].options.credentials,'same-origin');
});
test('null error body produces a recoverable error with its HTTP status',async()=>{
  const context={window:{},fetch:async()=>({ok:false,status:503,json:async()=>null})};
  vm.runInNewContext(source,context);
  await assert.rejects(context.window.V1.api('/unavailable'),error=>error.status===503 && /try again/.test(error.message));
});
