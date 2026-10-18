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
  if(!order||!uuid.test(order.orderId)||order.currency!=='INR'||![order.subtotalMinor,order.shippingMinor,order.totalMinor].every(n=>Number.isSafeInteger(n)&&n>=0)||order.totalMinor!==order.subtotalMinor+order.shippingMinor||!['pending','paid','collected','review_required','cancelled','expired'].includes(order.paymentStatus)||!['pending','confirmed','packed','shipped','delivered','cancelled'].includes(order.fulfillmentStatus)) throw new CheckoutError('The checkout response could not be verified.');
  if(order.paymentMethod!==undefined&&!['cod','razorpay'].includes(order.paymentMethod))throw new CheckoutError('The payment method could not be verified.');
  if(order.accessToken!==undefined&&(typeof order.accessToken!=='string'||order.accessToken.length>4096||!/^[a-f0-9]{64}$/.test(order.accessToken)))throw new CheckoutError('The order access could not be verified.');
  const base=`/api/v1/storefronts/${encodeURIComponent(slug)}/orders/${order.orderId}`;
  return {orderId:order.orderId,currency:'INR',subtotalMinor:order.subtotalMinor,shippingMinor:order.shippingMinor,totalMinor:order.totalMinor,paymentStatus:order.paymentStatus,fulfillmentStatus:order.fulfillmentStatus,paymentUrl:sameOriginPath(order.paymentUrl,origin,{prefix:base+'/'}),statusUrl:sameOriginPath(order.statusUrl,origin,{prefix:base}),...(order.accessToken!==undefined?{accessToken:order.accessToken}:{}),...(order.paymentMethod!==undefined?{paymentMethod:order.paymentMethod}:{})};
}
export function createStorefrontApi({slug,contract,fetchImpl=globalThis.fetch,origin=globalThis.location?.origin,timeoutMs=15000,activityProof=()=>null}){
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
    async readProducts(){
      if(!contract.paginatedProducts)return read(base+'/products',contract.decodeProducts);
      const products=[],productIds=new Set(),skuIds=new Set();let expected=null,readCount=0;
      for(let page=1;page<=10;page++){
        const data=await read(base+`/products?page=${page}&page_size=100`,contract.decodeProducts);
        if(expected===null)expected=data.total;
        if(data.total!==expected||expected>1000||data.page!==page)throw new Error('The collection changed. Refresh the page before editing your bag.');
        for(const product of data.products){
          if(productIds.has(product.product_id)||product.skus.some(sku=>skuIds.has(sku.sku_id)))throw new Error('The collection changed. Refresh the page before editing your bag.');
          productIds.add(product.product_id);for(const sku of product.skus)skuIds.add(sku.sku_id);
        }
        products.push(...data.products);readCount+=data.itemCount;
        if(readCount===expected)return {products};
        if(!data.itemCount||readCount>expected)break;
      }
      throw new Error('The complete collection could not be verified.');
    },
    async readOrder(order){
      const known=validateConfirmation(order,origin,slug);
      if(!known.accessToken||typeof contract.decodeOrderStatus!=='function')throw new Error('Order access is unavailable in this browser session.');
      const {response,data}=await request(base+`/orders/${known.orderId}`,{headers:{Accept:'application/json',Authorization:`Bearer ${known.accessToken}`}});
      if(!response.ok)throw new Error('Order status could not be checked. Keep your order reference and try again later.');
      try{return validateConfirmation(contract.decodeOrderStatus(data,{slug,orderId:known.orderId,accessToken:known.accessToken}),origin,slug);}catch{throw new Error('The order status response could not be verified.');}
    },
    async checkout(payload,key){
      let body;try{body=contract.encodeCheckout(payload,key);}catch{throw new CheckoutError('Checkout details could not be validated.',{definitive:true,code:'invalid_details'});}
      let response,data,proof=null;
      try{proof=activityProof(body.activity_context_id);}catch{/* Measurement is optional. */}
      try{({response,data}=await request(base+'/checkout',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json',...(typeof proof==='string'?{'X-Activity-Context':`Bearer ${proof}`}:{})},body:JSON.stringify(body)}));}
      catch{throw new CheckoutError('We could not confirm the result. Check the same attempt again.');}
      if(response.status!==201&&!(response.status===200&&contract.acceptsReplay===true)){
        const known=contract.decodeCheckoutError?.(response.status,data);
        throw new CheckoutError(known?.message||'We could not confirm this checkout attempt.',{definitive:known?.definitive===true,code:known?.code});
      }
      try{return validateConfirmation(contract.decodeCreatedOrder(data,{payload:body,key,slug}),origin,slug);}catch{throw new CheckoutError('The checkout response could not be verified. Keep the same attempt to check its result.');}
    },
  };
}
