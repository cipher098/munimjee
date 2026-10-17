// Public payment capability stays in this closure, never storage or SDK options.
import {validateConfirmation} from './live-api.js';

const SDK_URL='https://checkout.razorpay.com/v1/checkout.js';
const JOURNAL_PREFIX='munimjee.payment.v1:';
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PROVIDER=/^order_[A-Za-z0-9]{1,94}$/;
const PAYMENT=/^pay_[A-Za-z0-9]{1,96}$/;
const PAYMENT_STATES=['pending','paid','collected','review_required','cancelled','expired'];
const FULFILLMENT_STATES=['pending','confirmed','packed','shipped','delivered','cancelled'];
export class PaymentHandoffError extends Error {
  constructor(message,code='payment_unknown'){super(message);this.code=code;}
}
const fail=(message,code)=>{throw new PaymentHandoffError(message,code);};
const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
const date=value=>typeof value==='string'&&/T.*(?:Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value));
const callbackValid=value=>exact(value,['razorpay_order_id','razorpay_payment_id','razorpay_signature'])&&PROVIDER.test(value.razorpay_order_id)&&PAYMENT.test(value.razorpay_payment_id)&&/^[a-f0-9]{64}$/.test(value.razorpay_signature);

export function loadRazorpaySdk({document=globalThis.document,window=globalThis.window,timeoutMs=15000}={}){
  if(typeof window?.Razorpay==='function')return Promise.resolve(window.Razorpay);
  if(!document||!window)return Promise.reject(new PaymentHandoffError('Online payment could not be loaded. Try again before placing an order.','sdk_unavailable'));
  return new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src=SDK_URL;script.async=true;script.referrerPolicy='no-referrer';
    const finish=error=>{clearTimeout(timer);script.onload=null;script.onerror=null;if(error){script.remove();reject(new PaymentHandoffError('Online payment could not be loaded. Try again before placing an order.','sdk_unavailable'));}else resolve(window.Razorpay);};
    const timer=setTimeout(()=>finish(true),Math.min(Math.max(timeoutMs,1),30000));
    script.onload=()=>finish(typeof window.Razorpay!=='function');script.onerror=()=>finish(true);document.head.append(script);
  });
}

export function createPaymentHandoff({slug,origin=globalThis.location?.origin,storage=globalThis.sessionStorage,fetchImpl=globalThis.fetch,sdkLoader=loadRazorpaySdk,timeoutMs=15000}={}){
  if(!/^[a-z0-9][a-z0-9-]{0,62}$/.test(slug)||new URL(origin).origin!==origin)throw new Error('Invalid payment storefront.');
  let sdkPromise=null,busy=false;
  const base=`/api/v1/storefronts/${encodeURIComponent(slug)}/orders/`;
  const key=order=>JOURNAL_PREFIX+slug+':'+order.orderId;
  function known(order){
    const value=validateConfirmation(order,origin,slug);
    if(!UUID.test(value.orderId)||order.paymentMethod!=='razorpay'||!value.accessToken||value.totalMinor<100)fail('This order is not available for online payment.','invalid_order');
    return value;
  }
  function persist(order,value){
    try{const raw=JSON.stringify(value);storage.setItem(key(order),raw);if(storage.getItem(key(order))!==raw)throw new Error();}
    catch{fail('Payment recovery could not be saved in this browser. Keep your order reference and contact the store.','storage_unavailable');}
  }
  function remove(order){try{storage.removeItem(key(order));}catch{/* Terminal server state remains authoritative even with restricted storage. */}}
  function journal(order){
    let raw;try{raw=storage.getItem(key(order));}catch{fail('Payment recovery is unavailable in this browser. Keep your order reference.','storage_unavailable');}
    if(raw===null)return null;
    try{
      if(raw.length>2048)throw new Error();const value=JSON.parse(raw);
      if(!exact(value,['version','orderId','providerOrderId','phase','callback','createdAt'])||value.version!==1||value.orderId!==order.orderId||!PROVIDER.test(value.providerOrderId)||!['open','callback'].includes(value.phase)||!date(value.createdAt)||Date.parse(value.createdAt)>Date.now()+5000||Date.now()-Date.parse(value.createdAt)>86400000||(value.phase==='open'?value.callback!==null:!callbackValid(value.callback)||value.callback.razorpay_order_id!==value.providerOrderId))throw new Error();
      return value;
    }catch{fail('A previous payment result could not be verified. Check status and contact the store before paying again.','recovery_invalid');}
  }
  async function request(path,bearer,body){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),Math.min(Math.max(timeoutMs,1),30000));
    try{
      const response=await fetchImpl(path,{method:body===undefined?'GET':'POST',headers:{Accept:'application/json',Authorization:'Bearer '+bearer,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:controller.signal,credentials:'omit',cache:'no-store',redirect:'error'});
      const data=await response.json();if(!response.ok)fail(response.status===409?'Payment setup needs a status check or help from the store. Do not place another order.':'Payment could not be verified. Keep the same order reference.','server_rejected');return data;
    }catch(error){if(error instanceof PaymentHandoffError)throw error;fail('The payment result is unknown. Check this same order before paying again.','transport_unknown');}
    finally{clearTimeout(timer);}
  }
  function validateState(data,order){
    if(!exact(data,['contract_version','order_id','amount_minor','currency','payment_status','fulfillment_status','attempt_state','expires_at','retry_allowed'])||data.contract_version!=='checkout-state.v1'||data.order_id!==order.orderId||data.amount_minor!==order.totalMinor||data.currency!=='INR'||!PAYMENT_STATES.includes(data.payment_status)||!FULFILLMENT_STATES.includes(data.fulfillment_status)||!['not_started','requesting','unknown','ready'].includes(data.attempt_state)||(data.expires_at!==null&&!date(data.expires_at))||typeof data.retry_allowed!=='boolean')fail('The payment status response could not be verified.','invalid_response');
    return data;
  }
  function validateSession(data,order){
    const path=base+order.orderId+'/checkout-session';
    if(!exact(data,['contract_version','order_id','provider','provider_order_id','key_id','mode','amount_minor','currency','session_token','expires_at','merchant_name','prefill','verify_url','status_url','order_status_url'])||data.contract_version!=='checkout-session.v1'||data.order_id!==order.orderId||data.provider!=='razorpay'||!PROVIDER.test(data.provider_order_id)||!['test','live'].includes(data.mode)||typeof data.key_id!=='string'||data.key_id.length>100||!new RegExp('^rzp_'+data.mode+'_[A-Za-z0-9]+$').test(data.key_id)||data.amount_minor!==order.totalMinor||data.currency!=='INR'||typeof data.session_token!=='string'||data.session_token.length>4096||!/^[-_A-Za-z0-9]+\.[-_A-Za-z0-9]+\.[-_A-Za-z0-9]+$/.test(data.session_token)||!date(data.expires_at)||Date.parse(data.expires_at)<=Date.now()||Date.parse(data.expires_at)>Date.now()+905000||typeof data.merchant_name!=='string'||!data.merchant_name.length||data.merchant_name.length>100||!exact(data.prefill,['name','contact','email'])||!Object.entries(data.prefill).every(([k,v])=>typeof v==='string'&&v.length<=({name:100,contact:20,email:254}[k]))||data.status_url!==path||data.verify_url!==path+'/verify'||data.order_status_url!==base+order.orderId)fail('The payment session response could not be verified.','invalid_response');
    return data;
  }
  const terminal=state=>state.payment_status!=='pending'||state.fulfillment_status!=='pending';
  async function check(order){const value=known(order),state=validateState(await request(base+value.orderId+'/checkout-session',value.accessToken),value);if(terminal(state))remove(value);return state;}
  async function prepare(){
    // Check recovery storage before the shell accepts a new online order.
    const probe=JOURNAL_PREFIX+slug+':probe';
    try{storage.setItem(probe,'1');if(storage.getItem(probe)!=='1')throw new Error();storage.removeItem(probe);}
    catch{fail('Payment recovery is unavailable in this browser. Try another browser before placing an order.','storage_unavailable');}
    if(!sdkPromise)sdkPromise=Promise.resolve().then(()=>sdkLoader()).then(Sdk=>{if(typeof Sdk!=='function')fail('Online payment could not be loaded.','sdk_unavailable');return Sdk;}).catch(error=>{sdkPromise=null;throw error;});
    return sdkPromise;
  }
  async function open(order,onState=()=>{}){
    if(busy)fail('A payment window is already active.','payment_busy');busy=true;
    try{
      const value=known(order),state=await check(order);onState(state);if(terminal(state))return state;
      const saved=journal(value);
      if(saved?.phase==='open')fail('A previous payment window was interrupted. Check status or contact the store before paying again.','window_unknown');
      if(!state.retry_allowed){
        if(state.expires_at&&Date.parse(state.expires_at)<=Date.now())fail('This payment reservation expired. Keep your order reference and contact the store.','reservation_expired');
        if(['unknown','requesting'].includes(state.attempt_state))fail('Payment setup needs seller reconciliation. Keep this order reference; do not place another order.','reconciliation_required');
        fail('Online payment cannot resume for this order. Check status or contact the store.','payment_unavailable');
      }
      if(saved?.phase==='callback'){
        const session=validateSession(await request(base+value.orderId+'/checkout-session',value.accessToken,{}),value);
        if(session.provider_order_id!==saved.providerOrderId)fail('The saved payment does not match this order.','recovery_invalid');
        const verified=validateState(await request(session.verify_url,session.session_token,saved.callback),value);onState(verified);if(terminal(verified))remove(value);return verified;
      }
      const Sdk=await prepare();
      const session=validateSession(await request(base+value.orderId+'/checkout-session',value.accessToken,{}),value);
      const savedIntent={version:1,orderId:value.orderId,providerOrderId:session.provider_order_id,phase:'open',callback:null,createdAt:new Date().toISOString()};
      if(journal(value))fail('Another payment window has started for this order. Check its result before paying again.','window_unknown');
      persist(value,savedIntent);
      return await new Promise((resolve,reject)=>{
        let processing=false,finished=false;
        const done=(error,result)=>{if(finished)return;finished=true;if(error)reject(error);else resolve(result);};
        const dismiss=async()=>{if(processing||finished)return;processing=true;try{const status=await check(order);onState(status);remove(value);done(null,status);}catch(error){done(error);}};
        const handler=async raw=>{
          if(processing||finished)return;processing=true;
          try{
            // Razorpay may add fields; project only its documented signed triple.
            const evidence={razorpay_order_id:raw?.razorpay_order_id,razorpay_payment_id:raw?.razorpay_payment_id,razorpay_signature:raw?.razorpay_signature};
            if(!callbackValid(evidence)||evidence.razorpay_order_id!==session.provider_order_id)fail('The payment callback could not be verified. Check this order before paying again.','invalid_callback');
            persist(value,{...savedIntent,phase:'callback',callback:evidence});
            const verified=validateState(await request(session.verify_url,session.session_token,evidence),value);onState(verified);if(terminal(verified))remove(value);done(null,verified);
          }catch(error){done(error);}
        };
        try{
          const modal=new Sdk({key:session.key_id,order_id:session.provider_order_id,amount:session.amount_minor,currency:session.currency,name:session.merchant_name,prefill:{...session.prefill},handler,modal:{ondismiss:dismiss}});
          // A payment.failed event can leave Checkout open for provider-managed
          // retry. Only actual modal dismissal or a signed callback settles this window.
          modal.open();
        }catch{done(new PaymentHandoffError('The payment window could not be opened. Check this order before trying again.','window_unknown'));}
      });
    }finally{busy=false;}
  }
  return {prepare,open,check};
}
