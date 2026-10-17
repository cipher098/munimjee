// Explicit internal fixture codec + intercepted HTTP. These are simulated
// checkout failure journeys, not canonical catalogue.v2 or provider evidence.
import {test,expect} from '@playwright/test';

const productId='20000000-0000-4000-8000-000000000001';
const skuId='20000000-0000-4000-8000-000000000002';
const orderId='30000000-0000-4000-8000-000000000001';
const confirmation={orderId,currency:'INR',subtotalMinor:129900,shippingMinor:0,totalMinor:129900,paymentStatus:'pending',fulfillmentStatus:'pending',paymentUrl:null,statusUrl:null};
const data={contract_version:'storefront.page.v1',capabilities:{public_catalogue:true,sku_checkout:true},store:{slug:'synthetic',name:'Synthetic HTTP boutique',theme:'editorial',currency:'INR',description:'Mock HTTP verification only',shipping_policy:'Synthetic',return_policy:'Synthetic',payment_methods:['cod']},categories:[],selected_product_id:null,selected_category_id:null,products:[{product_id:productId,name:'Synthetic HTTP dress',description:'No real order or payment is created',category_id:null,photo_urls:['/assets/ivory.svg'],skus:[{sku_id:skuId,product_id:productId,options:{Size:'S'},price_minor:129900,currency:'INR',stock_available:2,active:true}]}]};

async function setup(page){
 await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.fallback():route.abort());
 await page.route('**/qa-wave2-http',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/src/styles.css"><link rel="stylesheet" href="/src/live.css"></head><body><main id="live-app"></main><script type="module">
 import {mountLiveStorefront} from '/src/live-app.js';
 import {createStorefrontApi} from '/src/live-api.js';
 const contract={decodeStore:v=>v,decodeProducts:v=>v,decodeCreatedOrder:v=>v,encodeCheckout:(body,key)=>({...body,idempotency_key:key}),decodeCheckoutError:(status,body)=>status===409&&body.code==='stock_conflict'?{message:'Synthetic stock conflict: review your details.',definitive:true,code:'stock_conflict'}:null};
 mountLiveStorefront({root:document.getElementById('live-app'),data:${JSON.stringify(data)},api:createStorefrontApi({slug:'synthetic',origin:location.origin,contract,timeoutMs:1000}),storage:sessionStorage});
 </script></body></html>`}));
 await page.goto('/qa-wave2-http');
 await page.getByRole('link',{name:'View Synthetic HTTP dress',exact:true}).click();
 const product=page.getByRole('dialog',{name:'A closer look'});
 await product.getByRole('radio',{name:/S/}).check();
 await product.getByRole('button',{name:/Add to bag/}).click();
 await page.getByRole('dialog',{name:'Your bag'}).getByRole('button',{name:'Continue to checkout'}).click();
 const checkout=page.getByRole('dialog',{name:'Checkout',exact:true});
 await checkout.getByLabel('Full name').fill('Synthetic Buyer');
 await checkout.getByLabel('Indian mobile number').fill('9876543210');
 await checkout.getByLabel('Address',{exact:true}).fill('12 Synthetic Street');
 await checkout.getByLabel('City',{exact:true}).fill('Jaipur');
 await checkout.getByLabel('State',{exact:true}).fill('Rajasthan');
 await checkout.getByLabel('PIN code').fill('302001');
 return checkout;
}

test('mock HTTP ambiguity survives reload and reuses exact checkout key/body',async({page})=>{
 const requests=[];
 await page.route('**/api/v1/storefronts/synthetic/checkout',async route=>{
  requests.push(route.request().postDataJSON());
  if(requests.length===1)return route.abort('failed');
  await route.fulfill({status:201,contentType:'application/json',body:JSON.stringify(confirmation)});
 });
 let checkout=await setup(page);
 await checkout.getByRole('button',{name:'Place order',exact:true}).click();
 await expect(checkout.getByRole('button',{name:'Check this attempt again'})).toBeEnabled();
 expect(requests).toHaveLength(1);
 await page.reload();
 checkout=page.getByRole('dialog',{name:'Checkout',exact:true});
 await expect(checkout).toBeVisible();
 await expect(checkout.getByLabel('Address',{exact:true})).toHaveAttribute('readonly','');
 await checkout.getByRole('button',{name:'Check this attempt again'}).click();
 await expect(checkout.getByText('Your order is received.')).toBeVisible();
 expect(requests).toHaveLength(2);expect(requests[0]).toEqual(requests[1]);
});

test('mock definitive 409 permits corrected details and a new request key',async({page})=>{
 const requests=[];
 await page.route('**/api/v1/storefronts/synthetic/checkout',async route=>{
  requests.push(route.request().postDataJSON());
  await route.fulfill({status:requests.length===1?409:201,contentType:'application/json',body:JSON.stringify(requests.length===1?{code:'stock_conflict'}:confirmation)});
 });
 const checkout=await setup(page);
 await checkout.getByRole('button',{name:'Place order',exact:true}).click();
 await expect(checkout.getByText('Synthetic stock conflict: review your details.')).toBeVisible();
 await checkout.getByLabel('Address',{exact:true}).fill('99 Corrected Synthetic Street');
 await checkout.getByRole('button',{name:'Review details and retry'}).click();
 await expect(checkout.getByText('Your order is received.')).toBeVisible();
 expect(requests).toHaveLength(2);
 expect(requests[1].address.line1).toBe('99 Corrected Synthetic Street');
 expect(requests[1].idempotency_key).not.toBe(requests[0].idempotency_key);
});

test('mock malformed 201 remains uncertain and never announces an order',async({page})=>{
 const requests=[];
 await page.route('**/api/v1/storefronts/synthetic/checkout',async route=>{
  requests.push(route.request().postDataJSON());
  await route.fulfill({status:201,contentType:'application/json',body:JSON.stringify({...confirmation,totalMinor:1})});
 });
 const checkout=await setup(page);
 await checkout.getByRole('button',{name:'Place order',exact:true}).click();
 await expect(checkout.getByRole('button',{name:'Check this attempt again'})).toBeEnabled();
 await expect(checkout.getByText('Your order is received.')).toHaveCount(0);
 expect(requests).toHaveLength(1);
 await checkout.getByRole('button',{name:'Check this attempt again'}).click();
 await expect(checkout.getByRole('button',{name:'Check this attempt again'})).toBeEnabled();
 expect(requests).toHaveLength(2);expect(requests[1]).toEqual(requests[0]);
});
