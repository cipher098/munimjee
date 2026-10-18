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
test('native identity transitions erase private seller drafts and preserve customer checkout recovery',async()=>{
  for(const path of ['/api/v1/auth/login','/api/v1/auth/signup','/api/v1/auth/invitations/accept','/api/v1/auth/logout','/api/v1/auth/logout-all']){
    const entries=new Map([['munimjee.v1.catalogue-draft:user:business','private-command'],['munimjee.v1.parcel-link:user:business:order:session','private-parcel-command'],['munimjee.v1.gateway-intent:user:business:session','private-gateway-marker'],['munimjee.v1.assistance-command:user:business:session','private-assistance-command'],['munimjee.v1.import-command:user:business:session','private-import-command'],['checkout:shop','customer-intent']]);
    const storage={get length(){return entries.size;},key:index=>[...entries.keys()][index],removeItem:key=>entries.delete(key)};
    const context={window:{sessionStorage:storage},fetch:async()=>({ok:true,json:async()=>({csrf_token:'new-bound-csrf'})})};
    vm.runInNewContext(source,context);
    await context.window.V1.api(path,{method:'POST'});
    assert.equal(entries.has('munimjee.v1.catalogue-draft:user:business'),false,path);
    assert.equal(entries.has('munimjee.v1.parcel-link:user:business:order:session'),false,path);
    for(const prefix of ['munimjee.v1.gateway-intent:','munimjee.v1.assistance-command:','munimjee.v1.import-command:'])assert.equal([...entries.keys()].some(key=>key.startsWith(prefix)),false,path);
    assert.equal(entries.get('checkout:shop'),'customer-intent');
    assert.equal(context.window.V1.csrf,'new-bound-csrf');
  }
});
test('expired native identity clears private commands and old CSRF while ordinary reads retain them',async()=>{
  const entries=new Map(['catalogue-draft','parcel-link','gateway-intent','assistance-command','import-command'].map(name=>['munimjee.v1.'+name+':user:business','private-command']));
  const responses=[{ok:true,data:{csrf_token:'bound'}},{ok:true,data:null},{ok:false,status:401,data:{}}];
  const context={window:{sessionStorage:{get length(){return entries.size;},key:index=>[...entries.keys()][index],removeItem:key=>entries.delete(key)}},fetch:async()=>{const r=responses.shift();return {...r,json:async()=>r.data};}};
  vm.runInNewContext(source,context);
  await context.window.V1.session();
  await context.window.V1.api('/api/v1/businesses/own/catalogue/storefront');
  assert.equal(entries.size,5);
  await assert.rejects(context.window.V1.session(),error=>error.status===401);
  assert.equal(entries.size,0);
  assert.equal(context.window.V1.csrf,null);
});
test('restricted storage cannot prevent a successful native logout',async()=>{
  const window={};Object.defineProperty(window,'sessionStorage',{get(){throw new Error('storage blocked');}});
  const context={window,fetch:async()=>({ok:true,json:async()=>({logged_out:true})})};
  vm.runInNewContext(source,context);
  assert.equal((await context.window.V1.api('/api/v1/auth/logout',{method:'POST'})).logged_out,true);
});
test('only typed server error codes permit explicit recovery classification',async()=>{
  for(const detail of ['ordinary conflict',null,{code:1,message:[]},{code:'parcel_preview_expired_or_invalid',message:'Scan the label again.'}]){
    const context={window:{},fetch:async()=>({ok:false,status:409,json:async()=>({detail})})};
    vm.runInNewContext(source,context);
    await assert.rejects(context.window.V1.api('/conflict'),error=>{
      assert.equal(error.status,409);
      assert.equal(error.code,typeof detail?.code==='string'?detail.code:null);
      if(typeof detail?.message==='string')assert.equal(error.message,detail.message);
      return true;
    });
  }
});
