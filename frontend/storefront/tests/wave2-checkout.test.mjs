// Independent financial-intent checks. Every API and storage adapter is synthetic.
import test from 'node:test';
import assert from 'node:assert/strict';
import {CheckoutAttempt} from '../src/checkout-attempt.js';
import {CheckoutError,createStorefrontApi,validateConfirmation} from '../src/live-api.js';

const origin='https://store.example.test';
const key1='10000000-0000-4000-8000-000000000001';
const key2='10000000-0000-4000-8000-000000000002';
const sku='20000000-0000-4000-8000-000000000001';
const orderId='30000000-0000-4000-8000-000000000001';
const now=Date.UTC(2026,9,18,0,0,0);
const payload=()=>({customer:{name:'Synthetic Buyer',phone:'9876543210',email:null},address:{line1:'12 Synthetic Street',line2:'',city:'Jaipur',state:'Rajasthan',postal_code:'302001',country:'IN'},items:[{sku_id:sku,quantity:1}],note:'',payment_method:'cod',whatsapp_updates_opt_in:false});
const confirmation=()=>({orderId,currency:'INR',subtotalMinor:129900,shippingMinor:5000,totalMinor:134900,paymentStatus:'pending',fulfillmentStatus:'pending',paymentUrl:null,statusUrl:`/api/v1/storefronts/synthetic/orders/${orderId}`});

class MemoryStorage{
 constructor(){this.entries=new Map();this.writes=0;this.failWrite=0;}
 getItem(key){return this.entries.get(key)??null;}
 setItem(key,value){this.writes++;if(this.writes===this.failWrite)throw new Error('Synthetic storage fault');this.entries.set(key,value);}
 removeItem(key){this.entries.delete(key);}
}
const attempt=(storage,extra={})=>new CheckoutAttempt({slug:'synthetic',storage,keyFactory:()=>key1,now:()=>now,origin,...extra});

test('ambiguous POST then reload retries the same payload and key exactly once',async()=>{
 const storage=new MemoryStorage(),calls=[];let fail=true;
 const api={checkout:async(body,key)=>{calls.push({body:structuredClone(body),key});if(fail){fail=false;throw new Error('Synthetic network ambiguity');}return confirmation();}};
 const first=attempt(storage);
 await assert.rejects(first.submit(api,payload()));
 assert.equal(first.current.state,'uncertain');
 const reloaded=attempt(storage,{keyFactory:()=>{throw new Error('A fresh key is forbidden');}});
 assert.equal(reloaded.locked,true);
 await reloaded.submit(api,payload());
 assert.equal(calls.length,2);assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1].key,key1);
 assert.equal(reloaded.current.state,'confirmed');
 assert.ok(!storage.getItem(reloaded.storageKey).includes('Synthetic Buyer'));
});

test('pending duplicate submit and changed uncertain basket never cause a new send',async()=>{
 const storage=new MemoryStorage();let reject;const calls=[];
 const api={checkout:(body,key)=>{calls.push(key);return new Promise((resolve,fail)=>{reject=fail;});}};
 const current=attempt(storage),pending=current.submit(api,payload());
 await assert.rejects(current.submit(api,payload()));
 reject(new Error('Synthetic timeout'));await assert.rejects(pending);
 const changed=payload();changed.items[0].quantity=2;
 await assert.rejects(current.submit(api,changed));
 assert.deepEqual(calls,[key1]);assert.equal(current.current.state,'uncertain');
});

test('storage failure before POST sends nothing; post-acknowledgement failure cannot become rejected',async()=>{
 const before=new MemoryStorage();before.failWrite=1;let sends=0;
 const api={checkout:async()=>{sends++;return confirmation();}};
 await assert.rejects(attempt(before).submit(api,payload()));assert.equal(sends,0);
 const after=new MemoryStorage();after.failWrite=2;const current=attempt(after);
 assert.deepEqual(await current.submit(api,payload()),confirmation());
 assert.equal(current.current.state,'confirmed');assert.equal(sends,1);
 await current.submit(api,payload()).catch(()=>{});assert.equal(sends,1);
 const reloaded=attempt(after,{keyFactory:()=>{throw new Error('No fresh key after acknowledged send');}});
 assert.equal(reloaded.current.key,key1);assert.equal(reloaded.locked,true);
});

test('only a definitive rejection permits a fresh corrected request key',async()=>{
 const storage=new MemoryStorage();let sequence=0;const keys=[key1,key2],calls=[];
 const current=attempt(storage,{keyFactory:()=>keys[sequence++]});
 const api={checkout:async(body,key)=>{calls.push({body,key});if(calls.length===1)throw new CheckoutError('Synthetic stock conflict',{definitive:true,code:'stock_conflict'});return confirmation();}};
 await assert.rejects(current.submit(api,payload()));assert.equal(current.current.state,'rejected');
 const corrected=payload();corrected.address.line1='99 Corrected Synthetic Street';
 await current.submit(api,corrected);
 assert.equal(calls[1].key,key2);assert.equal(calls[1].body.address.line1,corrected.address.line1);
});

test('expired unresolved storage erases address details while retaining a locked tombstone',async()=>{
 const storage=new MemoryStorage();
 storage.setItem('munimjee.checkout.v1:synthetic',JSON.stringify({version:1,slug:'synthetic',key:key1,createdAt:now-25*60*60*1000,state:'uncertain',payload:payload()}));
 const current=attempt(storage);
 assert.equal(current.locked,true);
 assert.ok(!storage.getItem(current.storageKey).includes('Synthetic Buyer'));
 let sends=0;await assert.rejects(current.submit({checkout:async()=>{sends++;}},payload()));assert.equal(sends,0);
});

test('an already open uncertain attempt expires before a later retry without reload',async()=>{
 const storage=new MemoryStorage();let clock=now,sends=0;
 storage.setItem('munimjee.checkout.v1:synthetic',JSON.stringify({version:1,slug:'synthetic',key:key1,createdAt:now,state:'uncertain',payload:payload()}));
 const current=attempt(storage,{now:()=>clock});
 clock+=25*60*60*1000;
 await assert.rejects(current.submit({checkout:async()=>{sends++;return confirmation();}},payload()));
 assert.equal(sends,0);assert.equal(current.locked,true);
 assert.ok(!storage.getItem(current.storageKey).includes('Synthetic Buyer'));
});

for(const state of ['paid','success','replayed','__proto__'])test(`unrecognized stored attempt state ${state} cannot send`,async()=>{
 const storage=new MemoryStorage();
 storage.setItem('munimjee.checkout.v1:synthetic',JSON.stringify({version:1,slug:'synthetic',key:key1,createdAt:now,state,payload:payload()}));
 const current=attempt(storage);let sends=0;
 await assert.rejects(current.submit({checkout:async()=>{sends++;return confirmation();}},payload()));
 assert.equal(sends,0);assert.equal(current.locked,true);
});

test('forged persisted confirmation cannot restore a script URL or bypass result validation',async()=>{
 const storage=new MemoryStorage(),forged={...confirmation(),paymentUrl:'javascript:alert(1)',totalMinor:1};
 storage.setItem('munimjee.checkout.v1:synthetic',JSON.stringify({version:1,slug:'synthetic',key:key1,createdAt:now,state:'confirmed',payload:{items:payload().items},confirmation:forged}));
 const current=attempt(storage);let restored;
 try{restored=await current.submit({checkout:async()=>{throw new Error('Saved confirmations must not send');}},payload());}catch{}
 assert.notEqual(restored?.paymentUrl,'javascript:alert(1)');
 assert.notEqual(restored?.totalMinor,1);
 assert.equal(current.locked,true);
});

test('order URLs require an exact order path boundary and reject injected schemes',()=>{
 const base=`/api/v1/storefronts/synthetic/orders/${orderId}`;
 const result=validateConfirmation({...confirmation(),statusUrl:base+'-foreign',paymentUrl:'javascript:alert(1)'},origin,'synthetic');
 assert.equal(result.statusUrl,null);assert.equal(result.paymentUrl,null);
 const foreign=validateConfirmation({...confirmation(),statusUrl:`/api/v1/storefronts/foreign/orders/${orderId}`,paymentUrl:`/api/v1/storefronts/synthetic/orders/${key2}/payment`},origin,'synthetic');
 assert.equal(foreign.statusUrl,null);assert.equal(foreign.paymentUrl,null);
});

const codec={decodeStore:value=>value,decodeProducts:value=>value,encodeCheckout:(body,key)=>({...body,idempotency_key:key}),decodeCreatedOrder:value=>value,decodeCheckoutError:()=>null};
test('malformed created-order totals and server errors stay uncertain with no automatic retry',async()=>{
 for(const status of [201,403,404,503]){
  let sends=0;
  const api=createStorefrontApi({slug:'synthetic',origin,contract:codec,fetchImpl:async()=>{sends++;return {status,ok:status===201,json:async()=>({...confirmation(),totalMinor:1})};}});
  await assert.rejects(api.checkout(payload(),key1),error=>error instanceof CheckoutError&&error.definitive===false);
  assert.equal(sends,1);
 }
});

test('checkout capability never activates from a missing or preview contract',()=>{
 assert.equal(createStorefrontApi({slug:'synthetic',origin,contract:null}),null);
 assert.equal(createStorefrontApi({slug:'synthetic',origin,contract:{contract_version:'catalogue.v1',checkout_enabled:true}}),null);
});

for(const stage of ['response','body'])test(`checkout ${stage} deadline aborts one attempt without automatic resend`,{timeout:1000},async()=>{
 let sends=0,aborted=false;
 const api=createStorefrontApi({slug:'synthetic',origin,contract:codec,timeoutMs:10,fetchImpl:async(path,{signal})=>{
  sends++;
  const stalled=()=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{aborted=true;reject(new Error('Synthetic abort'));},{once:true}));
  if(stage==='response')return stalled();
  return {status:201,ok:true,json:stalled};
 }});
 await assert.rejects(api.checkout(payload(),key1),error=>error instanceof CheckoutError&&!error.definitive);
 assert.equal(aborted,true);assert.equal(sends,1);
});
