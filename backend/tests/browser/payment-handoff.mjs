/* Real native/catalogue/order/session API + owned browser module. SDK/provider fake. */
import {chromium,expect} from '../../../frontend/storefront/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';
const base='http://127.0.0.1:8157',browser=await chromium.launch({headless:true});
let checks=0;const external=[],pageErrors=[];
const context=await browser.newContext({viewport:{width:390,height:844}});
await context.route('**/*',route=>{if(route.request().url().startsWith(base+'/'))return route.continue();external.push(route.request().url());return route.abort();});
const page=await context.newPage();page.on('pageerror',e=>pageErrors.push(e.message));page.setDefaultTimeout(10000);
async function ready(){for(let n=0;n<50;n++){try{await page.goto(base+'/v1');return;}catch(error){if(n===49)throw error;await new Promise(resolve=>setTimeout(resolve,200));}}}
async function count(){return (await(await page.request.get(base+'/__payment_test/counts')).json()).provider_posts;}
try{
 await ready();await page.locator('#access-form [name=business_name]').fill('Synthetic Payment Boutique');await page.getByLabel('Email',{exact:true}).fill(`payment-${crypto.randomUUID()}@example.com`);await page.getByLabel(/^Password/).fill('synthetic-payment-password');await page.getByRole('button',{name:'Create account',exact:true}).click();await page.getByRole('heading',{name:'Synthetic Payment Boutique',exact:true}).waitFor();checks++;
 const session=await(await page.request.get(base+'/api/v1/auth/session')).json(),bid=session.businesses[0].id,slug='payment-'+crypto.randomUUID().slice(0,8),prefix=`/api/v1/businesses/${bid}/catalogue`,headers={Origin:base,'X-CSRF-Token':session.csrf_token};
 async function write(path,data,method='post'){const response=await page.request[method](base+path,{headers,data});assert.ok(response.ok(),`${response.status()} ${await response.text()}`);return response.json();}
 const configuration=await write(`/api/v1/businesses/${bid}/payments/razorpay`,{key_id:'rzp_test_synthetic',key_secret:'synthetic-key',webhook_secret:'synthetic-webhook-key',mode:'test',enabled:true},'put');assert.equal(configuration.connection_verification,'not_performed');assert.equal(await count(),0);checks++;
 await write(prefix+'/storefront',{name:'Synthetic Payment Boutique',slug,description:'Synthetic payment tests only.',shipping_fee:5000,currency:'INR',cod_enabled:true,published:true,shipping_policy:'Synthetic policy.',return_policy:'Synthetic policy.'},'put');
 const product=await write(prefix+'/products',{idempotency_key:crypto.randomUUID(),seller_reviewed:true,name:'Synthetic Dress',description:'Human-reviewed synthetic dress.',photo_urls:[],skus:[{options:{Size:'M'},price_minor:129900,currency:'INR',stock_available:8,active:true}]});
 await write(prefix+`/products/${product.product.product_id}/activate`,{seller_reviewed:true,expected_mapping_revision:product.mapping_revision,expected_legacy_fingerprint:product.legacy_fingerprint});await write(prefix+'/checkout-policy',{checkout_enabled:true},'put');checks++;
 async function order(){const data=await write(`/api/v1/storefronts/${slug}/checkout`,{idempotency_key:crypto.randomUUID(),customer:{name:'Synthetic Buyer',phone:'+919876543210'},address:{line1:'Synthetic Street',city:'Bengaluru',state:'Karnataka',postal_code:'560001'},items:[{sku_id:product.skus[0].sku_id,quantity:1}],payment_method:'razorpay'});return {orderId:data.id,paymentMethod:data.payment_method,currency:data.currency,subtotalMinor:data.subtotal,shippingMinor:data.shipping_fee,totalMinor:data.total,paymentStatus:data.payment_status,fulfillmentStatus:data.fulfillment_status,statusUrl:`/api/v1/storefronts/${slug}/orders/${data.id}`,paymentUrl:null,accessToken:data.access_token};}
 async function mount(order,action='capture'){
  await page.goto(base+'/__payment_test');await page.evaluate(async({order,slug,action})=>{
   const {createPaymentHandoff}=await import('/payment-test-assets/payment-handoff.js');
   window.sdkOptions=[];window.openCount=0;
   class SyntheticSdk{
    constructor(options){this.options=options;window.sdkOptions.push(options);}on(){}
    async open(){window.openCount++;if(action==='interrupt')return;if(action==='dismiss')return this.options.modal.ondismiss();
     const gateway=this.options.order_id,payment='pay_'+gateway.slice(6),key=await crypto.subtle.importKey('raw',new TextEncoder().encode('synthetic-key'),{name:'HMAC',hash:'SHA-256'},false,['sign']);
     const signature=[...new Uint8Array(await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(gateway+'|'+payment)))].map(v=>v.toString(16).padStart(2,'0')).join('');
     this.options.handler({razorpay_order_id:gateway,razorpay_payment_id:payment,razorpay_signature:signature});
    }
   }
   window.order=order;window.handoff=createPaymentHandoff({slug,origin:location.origin,storage:sessionStorage,sdkLoader:()=>SyntheticSdk});
   document.querySelector('#open').onclick=()=>window.handoff.open(order,state=>{document.querySelector('#result').textContent=state.payment_status;}).then(()=>{window.outcome='done';}).catch(error=>{window.outcome=error.code;document.querySelector('#result').textContent=error.code;});
  },{order,slug,action});
 }
 const first=await order(),before=await count();await mount(first);await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('paid');assert.equal(await count(),before+1);assert.equal(await page.evaluate(()=>window.openCount),1);assert.equal(await page.evaluate(()=>JSON.stringify(window.sdkOptions).includes('session_token')),false);assert.equal(await page.evaluate(()=>JSON.stringify([...Object.keys(sessionStorage)].map(k=>sessionStorage.getItem(k))).includes('public_checkout_session')),false);checks+=4;
 // POST verification commits, response is dropped. Reload only reads paid; no SDK or provider POST.
 const second=await order();await mount(second);let dropped=false;
 await page.route('**/checkout-session/verify',async route=>{if(dropped)return route.continue();dropped=true;const actual=await route.fetch();assert.equal(actual.status(),200);return route.abort('failed');});
 await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('transport_unknown');const secondCount=await count();assert.equal(await page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.startsWith('munimjee.payment.v1:')).length),1);checks++;
 await page.unroute('**/checkout-session/verify');await mount(second);await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('paid');assert.equal(await page.evaluate(()=>window.openCount),0);assert.equal(await count(),secondCount);assert.equal(await page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.startsWith('munimjee.payment.v1:')).length),0);checks+=3;
 // Verification never reaches server: same signed callback is retried after reload.
 const third=await order();await mount(third);let evidence;
 await page.route('**/checkout-session/verify',route=>{evidence=route.request().postData();return route.abort('failed');});await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('transport_unknown');const thirdCount=await count();checks++;
 await page.unroute('**/checkout-session/verify');let replay;await page.route('**/checkout-session/verify',route=>{replay=route.request().postData();return route.continue();});await mount(third);await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('paid');assert.equal(replay,evidence);assert.equal(await page.evaluate(()=>window.openCount),0);assert.equal(await count(),thirdCount);checks+=3;await page.unroute('**/checkout-session/verify');
 // Interrupted window cannot reopen after reload. Status check remains read-only.
 const fourth=await order();await mount(fourth,'interrupt');await page.getByRole('button',{name:'Open test checkout'}).click();await expect.poll(()=>page.evaluate(()=>window.openCount)).toBe(1);const fourthCount=await count();await mount(fourth);await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('window_unknown');assert.equal(await page.evaluate(()=>window.openCount),0);assert.equal(await count(),fourthCount);checks+=2;
 // Provider committed but response lost: same pending order is kept, no second POST.
 const fifth=await order();await page.request.post(base+'/__payment_test/drop-next-provider-response');await mount(fifth);await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('server_rejected');const fifthCount=await count();await mount(fifth);await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('reconciliation_required');assert.equal(await count(),fifthCount);assert.equal(await page.evaluate(()=>window.openCount),0);checks+=2;
 // Provider session is ready but the HTTP session response is lost before SDK open.
 const sixth=await order();await mount(sixth);let sessionDropped=false;
 await page.route('**/checkout-session',async route=>{if(route.request().method()!=='POST'||sessionDropped)return route.continue();sessionDropped=true;const actual=await route.fetch();assert.equal(actual.status(),200);return route.abort('failed');});
 await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('transport_unknown');assert.equal(await page.evaluate(()=>window.openCount),0);const sixthCount=await count();checks++;
 await page.unroute('**/checkout-session');await mount(sixth);await page.getByRole('button',{name:'Open test checkout'}).click();await expect(page.locator('#result')).toHaveText('paid');assert.equal(await count(),sixthCount);assert.equal(await page.evaluate(()=>window.openCount),1);checks++;
 const total=await(await page.request.get(base+`/api/v1/businesses/${bid}/orders`)).json();assert.equal(total.total,6);assert.deepEqual(external,[]);assert.deepEqual(pageErrors,[]);checks++;
 console.log(`PASS ${checks} actual Chromium checks: native signup, capability-guarded synthetic gateway configuration, reviewed SKU activation, actual online orders, owned module with fake SDK/provider, captured verification, lost response/reload, exact callback replay, interrupted window block, unknown provider attempt. No live provider requests; shared customer shell composition is separate.`);
}finally{await browser.close();}
