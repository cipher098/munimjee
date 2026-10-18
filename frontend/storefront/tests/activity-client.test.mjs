import test from 'node:test';
import assert from 'node:assert/strict';
import {createActivityClient} from '../src/activity-client.js';
const first='11111111-1111-4111-8111-111111111111',second='22222222-2222-4222-8222-222222222222',product='33333333-3333-4333-8333-333333333333';
function fixture(changes={}){
  const values=new Map(),calls=[];let stamp=1700000000000,next=0;
  const document={visibilityState:'visible'},navigator={};
  const storage={getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
  const response=()=>({contract_version:'activity-context.v1',state:'ready',context_id:first,expires_at:new Date(stamp+1800000).toISOString(),capability:'memory-only.capability.secret'});
  let handler=async path=>path.endsWith('/contexts')?response():{contract_version:'activity-event.v1',state:'accepted',replayed:false};
  const fetchImpl=async(path,options)=>{calls.push({path,options});const result=await handler(path,options);return{ok:true,text:async()=>JSON.stringify(result)};};
  const args={slug:'test-boutique',origin:'https://shop.example',storage,document,navigator,now:()=>stamp,keyFactory:()=>next++?second:first,fetchImpl,...changes};
  return {values,calls,storage,document,navigator,args,response,client:()=>createActivityClient(args),setHandler:f=>handler=f,advance:ms=>stamp+=ms};
}

test('stores only a bounded command/context/expiry, never capability',async()=>{
  const f=fixture(),client=f.client();assert.equal(await client.start(),first);
  assert.equal(f.calls.length,1);assert.equal(JSON.parse(f.calls[0].options.body).idempotency_key,first);
  const raw=[...f.values.values()][0];assert(!raw.includes('capability'));assert(!raw.includes('secret'));
  assert.equal(client.contextForCheckout(),first);assert.equal(client.proofFor(first),'memory-only.capability.secret');assert.equal(client.proofFor(second),null);
});
test('commit then dropped context response retries exact key after reload',async()=>{
  const f=fixture();let accepted=null;
  f.setHandler(async(path,options)=>{accepted=JSON.parse(options.body).idempotency_key;throw Error('response lost after commit');});
  assert.equal(await f.client().start(),null);assert.equal(accepted,first);
  f.setHandler(async()=>f.response());assert.equal(await f.client().start(),first);
  assert.equal(JSON.parse(f.calls[1].options.body).idempotency_key,accepted);
});
test('reload reacquires memory proof with same context key',async()=>{
  const f=fixture();assert.equal(await f.client().start(),first);
  const loaded=f.client();assert.equal(loaded.contextForCheckout(),null);assert.equal(await loaded.start(),first);
  assert.equal(f.calls.length,2);assert.equal(f.calls[0].options.body,f.calls[1].options.body);
});
test('concurrent visible hooks share one context request and dedup events server-side',async()=>{
  const f=fixture(),client=f.client();await Promise.all([client.start(),client.start(),client.checkoutOpened()]);
  assert.equal(f.calls.filter(x=>x.path.endsWith('/contexts')).length,1);
  assert.equal(f.calls.filter(x=>x.path.endsWith('/events')).length,1);
  assert.equal(f.calls[1].options.headers.Authorization,'Bearer memory-only.capability.secret');
});
for(const preference of ['GPC','DNT','hidden'])test(`${preference} prevents every optional POST`,async()=>{
  const f=fixture();if(preference==='GPC')f.navigator.globalPrivacyControl=true;if(preference==='DNT')f.navigator.doNotTrack='1';if(preference==='hidden')f.document.visibilityState='hidden';
  const client=f.client();assert.equal(await client.start(),null);assert.equal(await client.productView(product),false);assert.equal(f.calls.length,0);
});
test('unavailable storage fails closed for measurement',async()=>{
  const f=fixture({storage:{getItem:()=>null,setItem:()=>{throw Error('restricted')}}});
  assert.equal(await f.client().start(),null);assert.equal(f.calls.length,0);
});
test('silent storage write failure also prevents POST',async()=>{
  const f=fixture({storage:{getItem:()=>null,setItem:()=>{}}});assert.equal(await f.client().start(),null);assert.equal(f.calls.length,0);
});
for(const raw of ['{','null','{"capability":"secret"}', 'x'.repeat(1025)])test('malformed storage does not mint a fresh context: '+raw.slice(0,12),async()=>{
  const f=fixture();f.storage.setItem('munimjee.activity.v1:https://shop.example:test-boutique',raw);
  assert.equal(await f.client().start(),null);assert.equal(f.calls.length,0);
});
test('foreign origin/context envelope is withheld',async()=>{
  const f=fixture();await f.client().start();const key=[...f.values.keys()][0],row=JSON.parse(f.values.get(key));row.origin='https://foreign.test';f.values.set(key,JSON.stringify(row));
  const before=f.calls.length;assert.equal(await f.client().start(),null);assert.equal(f.calls.length,before);
});
test('malformed but successful ACK never provides a checkout context',async()=>{
  const f=fixture();f.setHandler(async()=>({...f.response(),context_id:'wrong'}));const client=f.client();assert.equal(await client.start(),null);assert.equal(client.contextForCheckout(),null);
});
test('wrong context ID on reacquire does not replace persisted identity',async()=>{
  const f=fixture();await f.client().start();f.setHandler(async()=>({...f.response(),context_id:second}));const client=f.client();assert.equal(await client.start(),null);assert.equal(client.proofFor(second),null);
  assert.equal(JSON.parse([...f.values.values()][0]).context_id,first);
});
test('expiry can start a new browsing context but never proof for frozen old intent',async()=>{
  const f=fixture(),client=f.client();await client.start();const frozen=client.contextForCheckout();f.advance(1800001);
  assert.equal(client.proofFor(frozen),null);f.setHandler(async()=>({...f.response(),context_id:second}));await client.start();assert.equal(client.contextForCheckout(),second);assert.equal(client.proofFor(frozen),null);
});
test('measurement transport failures return optional null/false',async()=>{
  const f=fixture();f.setHandler(async()=>{throw Error('network blocked')});const client=f.client();assert.equal(await client.start(),null);assert.equal(await client.checkoutOpened(),false);
});
test('disposal or a newly enabled privacy preference removes access to proof',async()=>{
  const f=fixture(),client=f.client();await client.start();f.navigator.globalPrivacyControl=true;assert.equal(client.proofFor(first),null);delete f.navigator.globalPrivacyControl;client.dispose();assert.equal(client.proofFor(first),null);assert.equal(await client.start(),null);
});
test('product view only accepts a literal product UUID',async()=>{
  const f=fixture(),client=f.client();assert.equal(await client.productView('https://private.test?customer=x'),false);assert.equal(f.calls.length,0);assert.equal(await client.productView(product),true);assert.deepEqual(JSON.parse(f.calls[1].options.body),{event_kind:'product_view',product_id:product});
});
test('a definitively expired lost-ACK key permits only a later visible new context',async()=>{
  const f=fixture();f.setHandler(async()=>{throw Error('accepted context response lost')});await f.client().start();
  f.setHandler(async()=>({contract_version:'activity-context.v1',state:'expired',context_id:null,expires_at:null,capability:null}));
  const loaded=f.client();assert.equal(await loaded.start(),null);assert.equal(f.calls.length,2);assert.equal(f.values.size,0);
  f.setHandler(async()=>({...f.response(),context_id:second}));assert.equal(await loaded.start(),second);assert.equal(JSON.parse(f.calls[2].options.body).idempotency_key,second);
});
test('malformed expiry acknowledgement cannot discard an uncertain key',async()=>{
  const f=fixture();f.setHandler(async()=>({contract_version:'activity-context.v1',state:'expired',context_id:first,expires_at:null,capability:null}));
  const client=f.client();assert.equal(await client.start(),null);assert.equal(await client.start(),null);assert.equal(f.calls[0].options.body,f.calls[1].options.body);
});
