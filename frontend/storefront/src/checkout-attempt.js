// Session-scoped durable intent: ambiguity must never silently create a new key.
import {CheckoutError,validateConfirmation} from './live-api.js';
const MAX_AGE_MS=24*60*60*1000;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function validItems(items){return Array.isArray(items)&&items.length>0&&items.length<=50&&items.every(item=>item&&Object.keys(item).every(key=>['sku_id','quantity'].includes(key))&&uuid.test(item.sku_id)&&Number.isSafeInteger(item.quantity)&&item.quantity>=1&&item.quantity<=20)&&new Set(items.map(item=>item.sku_id)).size===items.length;}
function validPayload(payload,details){
  if(!payload||!validItems(payload.items))return false;
  if(!details)return Object.keys(payload).every(key=>key==='items');
  const customer=payload.customer,address=payload.address;
  const bounded=(value,min,max)=>typeof value==='string'&&value.length>=min&&value.length<=max;
  return Object.keys(payload).every(key=>['customer','address','items','note','payment_method','whatsapp_updates_opt_in'].includes(key))&&customer&&Object.keys(customer).every(key=>['name','phone','email'].includes(key))&&bounded(customer.name,2,100)&&bounded(customer.phone,10,20)&&(customer.email===null||bounded(customer.email,0,254))&&address&&Object.keys(address).every(key=>['line1','line2','city','state','postal_code','country'].includes(key))&&bounded(address.line1,3,200)&&bounded(address.line2,0,200)&&bounded(address.city,2,100)&&bounded(address.state,2,100)&&/^[1-9][0-9]{5}$/.test(address.postal_code)&&address.country==='IN'&&bounded(payload.note,0,2000)&&['cod','razorpay'].includes(payload.payment_method)&&typeof payload.whatsapp_updates_opt_in==='boolean';
}
export class CheckoutAttempt {
  constructor({slug,storage,keyFactory=()=>crypto.randomUUID(),now=()=>Date.now(),origin=globalThis.location?.origin||'https://store.invalid'}){
    this.storage=storage;this.storageKey=`munimjee.checkout.v1:${slug}`;this.keyFactory=keyFactory;this.current=null;this.storageUnavailable=false;this.slug=slug;this.now=now;this.origin=origin;
    try{
      const raw=storage.getItem(this.storageKey);
      if(raw){
        if(raw.length>32768)throw new Error('Saved attempt too large');
        const data=JSON.parse(raw);
        if(data.version!==1||data.slug!==slug||!['pending','uncertain','confirmed','rejected','expired'].includes(data.state)||!uuid.test(data.key)||!validPayload(data.payload,['pending','uncertain'].includes(data.state))||!Number.isSafeInteger(data.createdAt)||data.createdAt<=0||data.createdAt>now()+60000)throw new Error('Invalid saved attempt');
        if(data.state==='confirmed')data.confirmation=validateConfirmation(data.confirmation,origin,slug);
        this.current=data.state==='pending'?{...data,state:'uncertain'}:data;
        if(now()-data.createdAt>MAX_AGE_MS&&data.state!=='confirmed'){
          // Expiry removes PII but retains a locked tombstone; never silently POST a new key.
          this.current={...data,state:'expired',payload:{items:data.payload.items}};this.persist();
        }
      }
    }catch{this.storageUnavailable=true;}
  }
  get locked(){return this.storageUnavailable||['pending','uncertain','confirmed','expired'].includes(this.current?.state);}
  persist(){
    try{const raw=JSON.stringify(this.current);if(raw.length>32768)throw new Error('Attempt too large');this.storage.setItem(this.storageKey,raw);}
    catch{this.storageUnavailable=true;throw new CheckoutError('Session storage is unavailable. Checkout cannot safely continue.',{definitive:true,code:'storage_unavailable'});}
  }
  expireIfNeeded(){
    if(this.current&&this.current.state!=='confirmed'&&this.now()-this.current.createdAt>MAX_AGE_MS){this.current={...this.current,state:'expired',payload:{items:this.current.payload.items}};this.persist();}
  }
  async submit(api,payload){
    this.expireIfNeeded();
    if(this.storageUnavailable||this.current?.state==='expired')throw new CheckoutError('This attempt cannot safely continue. Contact the boutique to check its result.');
    if(this.current?.state==='pending')throw new CheckoutError('This checkout attempt is already being checked.');
    if(this.current?.state==='confirmed')return this.current.confirmation;
    if(this.current?.state==='uncertain'){
      if(JSON.stringify(this.current.payload)!==JSON.stringify(payload))throw new CheckoutError('Keep the same details while the previous attempt is checked.');
    }else{
      if(!validPayload(payload,true))throw new CheckoutError('Checkout details are invalid.',{definitive:true});
      const key=this.keyFactory();if(!uuid.test(key))throw new CheckoutError('Checkout could not safely create an attempt.');
      this.current={version:1,slug:this.slug,key,payload:structuredClone(payload),state:'pending',createdAt:this.now()};
    }
    this.current.state='pending';this.persist(); // Must succeed before POST.
    let confirmation;
    try{confirmation=validateConfirmation(await api.checkout(this.current.payload,this.current.key),this.origin,this.slug);}
    catch(error){this.current.state=error instanceof CheckoutError&&error.definitive?'rejected':'uncertain';if(this.current.state==='rejected')this.current.payload={items:this.current.payload.items};this.expireIfNeeded();this.persist();throw error;}
    this.current={...this.current,state:'confirmed',confirmation,payload:{items:this.current.payload.items}};
    // If final storage fails, previous persisted pending intent remains locked after reload.
    // Do not relabel an acknowledged order as rejected or enable a new key.
    try{this.persist();}catch{/* In-memory confirmation remains authoritative. */}
    return confirmation;
  }
  clearRejected(){if(this.current?.state!=='rejected')throw new Error('An unresolved attempt cannot be discarded.');try{this.storage.removeItem(this.storageKey);}catch{this.storageUnavailable=true;throw new Error('Session storage is unavailable.');}this.current=null;}
}
