import test from 'node:test';
import assert from 'node:assert/strict';
import {createPaymentHandoff,loadRazorpaySdk} from '../src/payment-handoff.js';

const id='11111111-1111-4111-8111-111111111111',slug='synthetic-store',origin='http://127.0.0.1:8157';
const base=`/api/v1/storefronts/${slug}/orders/${id}`;
const order={orderId:id,paymentMethod:'razorpay',currency:'INR',subtotalMinor:1000,shippingMinor:0,totalMinor:1000,paymentStatus:'pending',fulfillmentStatus:'pending',statusUrl:base,paymentUrl:null,accessToken:'a'.repeat(64)};
const callback={razorpay_order_id:'order_synthetic',razorpay_payment_id:'pay_synthetic',razorpay_signature:'b'.repeat(64)};
const state=(changes={})=>({contract_version:'checkout-state.v1',order_id:id,amount_minor:1000,currency:'INR',payment_status:'pending',fulfillment_status:'pending',attempt_state:'ready',expires_at:new Date(Date.now()+1200000).toISOString(),retry_allowed:true,...changes});
const session=(changes={})=>({contract_version:'checkout-session.v1',order_id:id,provider:'razorpay',provider_order_id:'order_synthetic',key_id:'rzp_test_synthetic',mode:'test',amount_minor:1000,currency:'INR',session_token:'synthetic.payload.signature',expires_at:new Date(Date.now()+890000).toISOString(),merchant_name:'Synthetic merchant',prefill:{name:'Synthetic buyer',contact:'+919876543210',email:''},verify_url:base+'/checkout-session/verify',status_url:base+'/checkout-session',order_status_url:base,...changes});
const storage=()=>{const values=new Map();return {values,getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};
function rig({store=storage(),getState=()=>state(),getSession=()=>session(),verify=()=>state({payment_status:'paid',retry_allowed:false}),action=options=>options.handler(callback),loader}={}){
  const calls=[],options=[];let opens=0;
  class Sdk{constructor(value){options.push(value);this.options=value;}on(){}open(){opens++;queueMicrotask(()=>action(this.options));}}
  const fetchImpl=async(path,init)=>{calls.push({path,init});let data=path.endsWith('/verify')?await verify():init.method==='POST'?await getSession():await getState();return {ok:true,status:200,json:async()=>data};};
  const factory=()=>createPaymentHandoff({slug,origin,storage:store,fetchImpl,sdkLoader:loader||(()=>Sdk)});
  return {factory,store,calls,options,get opens(){return opens;}};
}

test('SDK prepare creates no order/payment request; success requires server verification and allowlisted SDK options',async()=>{
  const r=rig();const handoff=r.factory();await handoff.prepare();assert.equal(r.calls.length,0);
  const events=[];assert.equal((await handoff.open(order,s=>events.push(s))).payment_status,'paid');
  assert.deepEqual(events.map(s=>s.payment_status),['pending','paid']);assert.equal(r.opens,1);
  assert.deepEqual(Object.keys(r.options[0]).sort(),['key','order_id','amount','currency','name','prefill','handler','modal'].sort());
  assert.ok(!JSON.stringify(r.options).includes('synthetic.payload.signature'));
  assert.ok(!JSON.stringify([...r.store.values]).includes('synthetic.payload.signature'));
  assert.equal(r.calls.at(-1).init.headers.Authorization,'Bearer synthetic.payload.signature');
  assert.ok(r.calls.every(c=>c.init.credentials==='omit'&&c.init.redirect==='error'&&c.init.cache==='no-store'));
  assert.equal(r.store.values.size,0);
});

test('committed verification with lost response reloads read-only and never opens or verifies again',async()=>{
  let paid=false;
  const r=rig({getState:()=>state({payment_status:paid?'paid':'pending',retry_allowed:!paid}),verify:()=>{paid=true;throw new Error('Synthetic committed response lost');}});
  await assert.rejects(r.factory().open(order),{code:'transport_unknown'});
  assert.equal(r.store.values.size,1);assert.ok(!JSON.stringify([...r.store.values]).includes('synthetic.payload.signature'));
  const before=r.calls.length;assert.equal((await r.factory().open(order)).payment_status,'paid');
  assert.equal(r.opens,1);assert.equal(r.calls.length,before+1);assert.equal(r.calls.at(-1).init.method,'GET');assert.equal(r.store.values.size,0);
});

test('lost verification before commit retains exact callback for explicit reload retry without reopening SDK',async()=>{
  let failures=1;const r=rig({verify:()=>{if(failures--)throw new Error('Synthetic drop');return state({payment_status:'paid',retry_allowed:false});}});
  await assert.rejects(r.factory().open(order),{code:'transport_unknown'});
  assert.equal((await r.factory().open(order)).payment_status,'paid');assert.equal(r.opens,1);
  const writes=r.calls.filter(c=>c.path.endsWith('/verify'));assert.equal(writes.length,2);assert.equal(writes[0].init.body,writes[1].init.body);
});

test('interrupted open window survives reload and blocks another modal/provider POST',async()=>{
  const r=rig({action:()=>{}});r.factory().open(order).catch(()=>{});
  await new Promise(resolve=>setTimeout(resolve,5));assert.equal(r.opens,1);
  const before=r.calls.length;await assert.rejects(r.factory().open(order),{code:'window_unknown'});
  assert.equal(r.opens,1);assert.equal(r.calls.length,before+1);assert.equal(r.calls.at(-1).init.method,'GET');
});

test('normal dismiss preserves original order and explicitly resumes the same provider identity',async()=>{
  const r=rig({action:options=>options.modal.ondismiss()});const handoff=r.factory();
  assert.equal((await handoff.open(order)).payment_status,'pending');assert.equal(r.store.values.size,0);
  await handoff.open(order);assert.equal(r.opens,2);assert.ok(r.options.every(o=>o.order_id==='order_synthetic'));
  assert.ok(r.calls.every(c=>c.path.startsWith(base+'/checkout-session')));
});

test('unknown/requesting setup allows status only and never creates another payment',async()=>{
  for(const attempt_state of ['unknown','requesting']){
    const r=rig({getState:()=>state({attempt_state,retry_allowed:false})});await assert.rejects(r.factory().open(order),{code:'reconciliation_required'});
    assert.equal(r.opens,0);assert.equal(r.calls.length,1);assert.equal(r.calls[0].init.method,'GET');
  }
});

test('malformed, expired, cross-order and provider-mismatched recovery never silently clears or reopens',async()=>{
  const key='munimjee.payment.v1:'+slug+':'+id;
  for(const raw of ['broken',JSON.stringify({version:1,orderId:id,providerOrderId:'order_synthetic',phase:'callback',callback,createdAt:new Date(Date.now()-86400001).toISOString()}),JSON.stringify({version:1,orderId:'22222222-2222-4222-8222-222222222222',providerOrderId:'order_synthetic',phase:'callback',callback,createdAt:new Date().toISOString()}),JSON.stringify({version:1,orderId:id,providerOrderId:'order_different',phase:'callback',callback:{...callback,razorpay_order_id:'order_different'},createdAt:new Date().toISOString()})]){
    const store=storage();store.setItem(key,raw);const r=rig({store});await assert.rejects(r.factory().open(order),{code:'recovery_invalid'});assert.equal(r.opens,0);assert.equal(store.getItem(key),raw);
  }
});

test('storage unavailable fails before any SDK window and never includes secret/capability in persisted intent',async()=>{
  const store={getItem:()=>null,setItem:()=>{throw new Error('restricted');},removeItem:()=>{}};
  const r=rig({store});await assert.rejects(r.factory().open(order),{code:'storage_unavailable'});assert.equal(r.opens,0);
});

test('malformed session paths/amount/currency/mode cannot reach SDK',async()=>{
  for(const change of [{verify_url:'https://evil.invalid/verify'},{amount_minor:1},{currency:'USD'},{mode:'live'},{session_token:'invalid'},{prefill:{name:'Synthetic'}}]){
    const r=rig({getSession:()=>session(change)});await assert.rejects(r.factory().open(order),{code:'invalid_response'});assert.equal(r.opens,0);
  }
});

test('invalid callback never verifies or marks paid, terminal status cleans malformed journal',async()=>{
  const r=rig({action:options=>options.handler({...callback,razorpay_order_id:'order_foreign'})});await assert.rejects(r.factory().open(order),{code:'invalid_callback'});
  assert.equal(r.calls.filter(c=>c.path.endsWith('/verify')).length,0);assert.equal(r.store.values.size,1);
  const terminal=rig({store:r.store,getState:()=>state({payment_status:'review_required',retry_allowed:false})});
  assert.equal((await terminal.factory().check(order)).payment_status,'review_required');assert.equal(r.store.values.size,0);
});

test('COD and wrong order bearer shape rejected before requests',async()=>{
  const r=rig();await assert.rejects(r.factory().open({...order,paymentMethod:'cod'}),{code:'invalid_order'});assert.equal(r.calls.length,0);
});

test('fixed official SDK loader rejects missing SDK and does not accept a configurable provider URL',async()=>{
  let script;const document={createElement:()=>script={remove(){}},head:{append:()=>queueMicrotask(()=>script.onload())}};
  await assert.rejects(loadRazorpaySdk({document,window:{},timeoutMs:50}),{code:'sdk_unavailable'});
  assert.equal(script.src,'https://checkout.razorpay.com/v1/checkout.js');
});


test('two module instances cannot open competing windows for the same stored order',async()=>{
  const r=rig({action:()=>{}});r.factory().open(order).catch(()=>{});
  await new Promise(resolve=>setTimeout(resolve,5));
  await assert.rejects(r.factory().open(order),{code:'window_unknown'});assert.equal(r.opens,1);
});

test('prepare fails closed on restricted recovery storage before shell creates an online order',async()=>{
  const r=rig({store:{getItem:()=>null,setItem:()=>{throw new Error('restricted');},removeItem:()=>{}}});
  await assert.rejects(r.factory().prepare(),{code:'storage_unavailable'});assert.equal(r.calls.length,0);assert.equal(r.opens,0);
});

test('provider failure while its modal remains open does not unlock another payment window',async()=>{
  let modal,settled=false;const events={};
  class Sdk{constructor(options){modal=options;}on(name,callback){events[name]=callback;}open(){}}
  const r=rig({loader:()=>Sdk}),handoff=r.factory();const pending=handoff.open(order).then(state=>{settled=true;return state;});
  await new Promise(resolve=>setTimeout(resolve,5));events['payment.failed']?.({error:{code:'SYNTHETIC_FAILURE'}});
  assert.equal(settled,false);await assert.rejects(handoff.open(order),{code:'payment_busy'});
  await modal.modal.ondismiss();assert.equal((await pending).payment_status,'pending');
});
