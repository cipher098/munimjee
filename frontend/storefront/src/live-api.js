// A named operational capability. Fixture/preview code never imports this module.
export class CheckoutError extends Error {
  constructor(message,{definitive=false,code='uncertain'}={}){super(message);this.definitive=definitive;this.code=code;}
}
export function sameOriginPath(value,origin,{prefix='/'}={}){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\')) return null;
  const parsed=new URL(value,origin);
  return parsed.origin===origin&&(prefix==='/'||parsed.pathname===prefix||parsed.pathname.startsWith(prefix.endsWith('/')?prefix:prefix+'/'))&&!parsed.search&&!parsed.hash&&!parsed.username&&!parsed.password?parsed.pathname+parsed.search:null;
}
export function validateConfirmation(order,origin,slug){
  const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if(!order||!uuid.test(order.orderId)||order.currency!=='INR'||![order.subtotalMinor,order.shippingMinor,order.totalMinor].every(n=>Number.isSafeInteger(n)&&n>=0)||order.totalMinor!==order.subtotalMinor+order.shippingMinor||!['pending','paid','collected','review_required'].includes(order.paymentStatus)||!['pending','confirmed','packed','shipped','delivered'].includes(order.fulfillmentStatus)) throw new CheckoutError('The checkout response could not be verified.');
  const base=`/api/v1/storefronts/${encodeURIComponent(slug)}/orders/${order.orderId}`;
  return {orderId:order.orderId,currency:'INR',subtotalMinor:order.subtotalMinor,shippingMinor:order.shippingMinor,totalMinor:order.totalMinor,paymentStatus:order.paymentStatus,fulfillmentStatus:order.fulfillmentStatus,paymentUrl:sameOriginPath(order.paymentUrl,origin,{prefix:base+'/'}),statusUrl:sameOriginPath(order.statusUrl,origin,{prefix:base})};
}
export function createStorefrontApi({slug,contract,fetchImpl=globalThis.fetch,origin=globalThis.location?.origin,timeoutMs=15000}){
  if(!/^[a-z0-9][a-z0-9-]{0,62}$/.test(slug)) throw new Error('Invalid storefront slug.');
  if(!contract||typeof contract.decodeStore!=='function'||typeof contract.decodeProducts!=='function'||typeof contract.decodeCreatedOrder!=='function'||typeof contract.encodeCheckout!=='function') return null;
  const base=`/api/v1/storefronts/${encodeURIComponent(slug)}`;
  async function request(path,options={}){
    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),Math.min(Math.max(timeoutMs,1),30000));
    try{const response=await fetchImpl(path,{...options,signal:controller.signal,credentials:'same-origin',redirect:'error',cache:'no-store'});const data=await response.json();return {response,data};}
    finally{clearTimeout(timeout);}
  }
  async function read(path,decode){const {response,data}=await request(path,{headers:{Accept:'application/json'}});if(!response.ok)throw new Error(response.status===404?'This collection is unavailable.':'The collection could not be loaded.');return decode(data);}
  return {
    readStore:()=>read(base,contract.decodeStore),
    readProducts:()=>read(base+'/products',contract.decodeProducts),
    async checkout(payload,key){
      let body;try{body=contract.encodeCheckout(payload,key);}catch{throw new CheckoutError('Checkout details could not be validated.',{definitive:true,code:'invalid_details'});}
      let response,data;
      try{({response,data}=await request(base+'/checkout',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify(body)}));}
      catch{throw new CheckoutError('We could not confirm the result. Check the same attempt again.');}
      if(response.status!==201){
        const known=contract.decodeCheckoutError?.(response.status,data);
        throw new CheckoutError(known?.message||'We could not confirm this checkout attempt.',{definitive:known?.definitive===true,code:known?.code});
      }
      return validateConfirmation(contract.decodeCreatedOrder(data),origin,slug);
    },
  };
}
