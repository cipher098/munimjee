// Exact committed catalogue.v2 / storefront.v1 / order.v1 boundary.
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const token=/^[a-f0-9]{64}$/;
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const keys=(x,allowed)=>object(x)&&Object.keys(x).every(k=>allowed.includes(k));
const text=(x,min=0,max=10000)=>typeof x==='string'&&x.length>=min&&x.length<=max;
const amount=x=>Number.isSafeInteger(x)&&x>=0&&x<=2000000000;
const fail=()=>{throw new Error('The server response could not be verified.');};
const check=(x)=>{if(!x)fail();};
function publicImage(value){
 if(!text(value,1,2048)||/[\\\x00-\x20]/.test(value))return false;
 try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&!url.search&&!url.hash;}catch{return false;}
}
function options(x){check(object(x)&&Object.keys(x).length<=10&&Object.entries(x).every(([k,v])=>text(k,1,64)&&text(v,1,200)));return {...x};}
function product(x){
 check(keys(x,['contract_version','mode','business_id','product_id','name','description','category_id','photo_urls','readiness','checkout_enabled','skus']));
 check(x.contract_version==='catalogue.v2'&&x.mode==='operational'&&x.readiness==='active'&&UUID.test(x.business_id)&&UUID.test(x.product_id)&&text(x.name,1,200)&&text(x.description)&&typeof x.checkout_enabled==='boolean'&&(x.category_id===null||UUID.test(x.category_id))&&Array.isArray(x.photo_urls)&&x.photo_urls.length<=50&&x.photo_urls.every(url=>text(url,1,2048))&&Array.isArray(x.skus)&&x.skus.length<=500);
 const skus=x.skus.map(s=>{check(keys(s,['sku_id','product_id','options','price_minor','currency','stock_available','active'])&&UUID.test(s.sku_id)&&s.product_id===x.product_id&&s.currency==='INR'&&amount(s.price_minor)&&(s.stock_available===null||amount(s.stock_available))&&s.active===true);return {sku_id:s.sku_id,product_id:s.product_id,options:options(s.options),price_minor:s.price_minor,currency:'INR',stock_available:s.stock_available,active:true};});
 check(new Set(skus.map(s=>s.sku_id)).size===skus.length);
 return {product_id:x.product_id,name:x.name,description:x.description,category_id:x.category_id,photo_urls:x.photo_urls.filter(publicImage),skus};
}
function decodeProducts(x){
 check(keys(x,['items','total','page','page_size'])&&Array.isArray(x.items)&&Number.isSafeInteger(x.total)&&x.total>=0&&Number.isSafeInteger(x.page)&&x.page>=1&&Number.isSafeInteger(x.page_size)&&x.page_size>=1&&x.page_size<=100&&x.items.length<=x.page_size);
 check(new Set(x.items.map(p=>p.business_id)).size<=1);
 const products=x.items.map(product).filter(p=>p.skus.length);
 check(new Set(products.map(p=>p.product_id)).size===products.length&&new Set(products.flatMap(p=>p.skus.map(s=>s.sku_id))).size===products.reduce((n,p)=>n+p.skus.length,0));
 return {products,total:x.total,page:x.page,pageSize:x.page_size,itemCount:x.items.length};
}
function decodeStore(x){
 check(keys(x,['contract_version','name','slug','description','logo_url','contact_email','contact_phone','shipping_policy','return_policy','currency','shipping_fee','cod_enabled','categories','whatsapp_updates_available','payment_options','checkout_enabled']));
 check(x.contract_version==='storefront.v1'&&text(x.name,1,100)&&/^[a-z0-9][a-z0-9-]{0,62}$/.test(x.slug)&&x.currency==='INR'&&amount(x.shipping_fee)&&typeof x.checkout_enabled==='boolean'&&typeof x.cod_enabled==='boolean'&&Array.isArray(x.categories)&&keys(x.payment_options,['cod_enabled','razorpay_enabled','razorpay_mode'])&&typeof x.payment_options.cod_enabled==='boolean'&&typeof x.payment_options.razorpay_enabled==='boolean');
 check(x.categories.every(c=>keys(c,['id','name'])&&UUID.test(c.id)&&text(c.name,1,200)));
 return {slug:x.slug,name:x.name,currency:'INR',shippingMinor:x.shipping_fee,checkoutEnabled:x.checkout_enabled,paymentMethods:x.payment_options.cod_enabled?['cod']:[],categories:x.categories.map(c=>({category_id:c.id,name:c.name}))};
}
function encodeCheckout(payload,key){
 check(UUID.test(key)&&keys(payload,['customer','address','items','note','payment_method','whatsapp_updates_opt_in']));
 const c=payload.customer,a=payload.address;
 check(keys(c,['name','phone','email'])&&text(c.name,2,100)&&text(c.phone,10,20)&&(c.email===null||text(c.email,0,254))&&keys(a,['line1','line2','city','state','postal_code','country'])&&text(a.line1,3,200)&&text(a.line2,0,200)&&text(a.city,2,100)&&text(a.state,2,100)&&/^[1-9][0-9]{5}$/.test(a.postal_code)&&a.country==='IN'&&text(payload.note,0,2000)&&['cod','razorpay'].includes(payload.payment_method)&&typeof payload.whatsapp_updates_opt_in==='boolean');
 check(Array.isArray(payload.items)&&payload.items.length>=1&&payload.items.length<=50&&payload.items.every(i=>keys(i,['sku_id','quantity'])&&UUID.test(i.sku_id)&&Number.isSafeInteger(i.quantity)&&i.quantity>=1&&i.quantity<=20)&&new Set(payload.items.map(i=>i.sku_id)).size===payload.items.length);
 return {idempotency_key:key,customer:{name:c.name,phone:c.phone,email:c.email},address:{line1:a.line1,line2:a.line2,city:a.city,state:a.state,postal_code:a.postal_code,country:'IN'},items:payload.items.map(i=>({sku_id:i.sku_id,quantity:i.quantity})),note:payload.note,payment_method:payload.payment_method,whatsapp_updates_opt_in:payload.whatsapp_updates_opt_in};
}
function decodeOrder(x,{payload,slug,accessToken,orderId,created=true}={}){
 check(keys(x,['contract_version','id','number','access_token','customer','address','note','subtotal','shipping_fee','total','currency','payment_method','payment_status','fulfillment_status','carrier','tracking_number','tracking_url','created_at','updated_at','expires_at','items']));
 check((created?x.contract_version==='order.v1':x.contract_version===undefined||x.contract_version==='order.v1')&&UUID.test(x.id)&&(!orderId||x.id===orderId)&&text(x.number,1,40)&&x.currency==='INR'&&[x.subtotal,x.shipping_fee,x.total].every(amount)&&x.subtotal+x.shipping_fee===x.total&&['cod','razorpay'].includes(x.payment_method)&&['pending','paid','collected','review_required','cancelled','expired'].includes(x.payment_status)&&['pending','confirmed','packed','shipped','delivered','cancelled'].includes(x.fulfillment_status)&&Array.isArray(x.items)&&x.items.length>=1&&x.items.length<=50);
 const items=x.items.map(i=>{check(keys(i,['product_id','sku_id','name','options','currency','quantity','unit_price','line_total','photo_url'])&&UUID.test(i.product_id)&&UUID.test(i.sku_id)&&text(i.name,1,200)&&i.currency==='INR'&&Number.isSafeInteger(i.quantity)&&i.quantity>=1&&i.quantity<=20&&amount(i.unit_price)&&amount(i.line_total)&&i.line_total===i.unit_price*i.quantity);options(i.options);return {sku_id:i.sku_id,quantity:i.quantity,lineTotal:i.line_total};});
 check(new Set(items.map(i=>i.sku_id)).size===items.length&&items.reduce((n,i)=>n+i.lineTotal,0)===x.subtotal);
 if(payload){
  check(payload.items.length===items.length&&payload.items.every(i=>items.some(actual=>i.sku_id===actual.sku_id&&i.quantity===actual.quantity))&&x.payment_method===payload.payment_method);
  const phone=value=>value.replaceAll(' ','').replaceAll('-','').replace(/^\+91/,'');
  check(object(x.customer)&&x.customer.name===payload.customer.name.trim()&&phone(x.customer.phone)===phone(payload.customer.phone)&&object(x.address)&&Object.entries(payload.address).every(([k,v])=>x.address[k]===v.trim()));
 }
 const capability=created?x.access_token:accessToken;check(text(capability,1,4096)&&token.test(capability)&&text(slug,1,63));
 return {orderId:x.id,currency:'INR',subtotalMinor:x.subtotal,shippingMinor:x.shipping_fee,totalMinor:x.total,paymentStatus:x.payment_status,fulfillmentStatus:x.fulfillment_status,paymentUrl:null,statusUrl:`/api/v1/storefronts/${encodeURIComponent(slug)}/orders/${x.id}`,accessToken:capability};
}
export const canonicalContract={decodeStore,decodeProducts,encodeCheckout,decodeCreatedOrder:decodeOrder,decodeOrderStatus:(x,context)=>decodeOrder(x,{...context,created:false}),acceptsReplay:true,paginatedProducts:true,
 decodeCheckoutError(status,data){return status===409&&keys(data,['detail'])&&keys(data.detail,['code','message'])&&data.detail.code==='sku_out_of_stock'&&text(data.detail.message,1,200)?{definitive:true,code:'sku_out_of_stock',message:'This quantity is no longer available. Review your bag and refresh availability.'}:null;}};
