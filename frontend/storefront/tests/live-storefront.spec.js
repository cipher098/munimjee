// Injected local mock HTTP contract, not the pending catalogue.v2 backend DTO.
import {test,expect} from '@playwright/test';
import {catalogueFixtures} from '../src/fixtures.js';
const order={orderId:'66666666-6666-4666-8666-666666666601',currency:'INR',subtotalMinor:1378000,shippingMinor:5000,totalMinor:1383000,paymentStatus:'pending',fulfillmentStatus:'pending',paymentUrl:null,statusUrl:null};
async function harness(page,theme='editorial'){
 const categories=catalogueFixtures.map((p,index)=>({category_id:p.category_id,name:['Occasionwear','Dresses','Kurtas','Co-ords','Dresses','Layers'][index]}));
 const data={contract_version:'storefront.page.v1',store:{slug:'tara',name:'Tara',theme,currency:'INR',description:'Local mock HTTP shopping journey.',shipping_policy:'Sample local test policy',return_policy:'Sample local test policy',payment_methods:['cod']},capabilities:{public_catalogue:true,sku_checkout:true},products:catalogueFixtures.map(p=>({...p,photo_urls:[`/assets/${['rose','saffron','sage','ivory','indigo','terracotta'][catalogueFixtures.indexOf(p)]}.svg`]})),categories,selected_product_id:null,selected_category_id:null};
 await page.route('**/live-test*',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><html data-theme="${theme}"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/src/styles.css"><link rel="stylesheet" href="/src/live.css"><main id="live-app"></main><script type="module">import {mountLiveStorefront} from '/src/live-app.js';import {createStorefrontApi} from '/src/live-api.js';const contract={decodeStore:x=>x,decodeProducts:x=>x,decodeCreatedOrder:x=>x,encodeCheckout:(body,key)=>({...body,idempotency_key:key}),decodeCheckoutError:(status,data)=>status===409&&data.code==='stock_conflict'?{definitive:true,code:'stock_conflict',message:'This size is no longer available. Review your bag.'}:null};const api=createStorefrontApi({slug:'tara',contract,timeoutMs:500});mountLiveStorefront({root:document.getElementById('live-app'),data:${JSON.stringify(data).replaceAll('<','\\u003c')},api,storage:sessionStorage});</script></html>`}));
 await page.route('**/api/v1/storefronts/tara/products',route=>route.fulfill({json:{products:data.products}}));
}
async function bagToCheckout(page){
 await page.getByRole('link',{name:'View Gulab occasion set',exact:true}).click();
 const detail=page.getByRole('dialog',{name:'A closer look'});
 await page.keyboard.press('Escape');
 const link=page.getByRole('link',{name:'View Gulab occasion set',exact:true});
 await expect(link).toBeFocused();await expect(link).toHaveAttribute('href',/\/stores\/tara\/products\/22222222/);
 await link.press('Enter');
 await detail.getByRole('radio',{name:/S \/ Rose/}).check();
 await detail.getByLabel('Quantity',{exact:true}).fill('2');
 await detail.getByRole('button',{name:/Add to bag/}).click();
 await page.getByRole('dialog',{name:'Your bag'}).getByRole('button',{name:'Continue to checkout'}).click();
 const form=page.getByRole('dialog',{name:'Checkout',exact:true});
 await form.getByLabel('Full name').fill('Local Test');await form.getByLabel('Indian mobile number').fill('9876543210');await form.getByLabel('Address',{exact:true}).fill('Synthetic Street');await form.getByLabel('City',{exact:true}).fill('Bengaluru');await form.getByLabel('State',{exact:true}).fill('Karnataka');await form.getByLabel('PIN code').fill('560001');return form;
}
for(const theme of ['editorial','catalogue','video'])for(const width of [390,1440]){
 test(`mockHTTP ${theme} ${width}: details -> server201 pending confirmation`,async({page},testInfo)=>{
  const errors=[],requests=[];page.on('pageerror',error=>errors.push(error.message));await page.setViewportSize({width,height:900});await harness(page,theme);
  await page.route('**/api/v1/storefronts/tara/checkout',async route=>{requests.push(route.request().postDataJSON());await route.fulfill({status:201,json:order});});
  await page.goto('/live-test');const form=await bagToCheckout(page);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`${theme}-${width}-checkout.png`),fullPage:true});
  await form.getByRole('button',{name:'Place order',exact:true}).click();
  await expect(form.getByText('Your order is received.',{exact:true})).toBeVisible();await expect(form.getByText('Payment: Pending',{exact:true})).toBeVisible();await expect(form.getByText('₹13,830',{exact:true})).toBeVisible();
  expect(requests).toHaveLength(1);expect(requests[0].items[0].quantity).toBe(2);expect(requests[0]).not.toHaveProperty('business_id');expect(requests[0]).not.toHaveProperty('total');expect(requests[0].idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
  expect(await page.evaluate(()=>sessionStorage.getItem('munimjee.checkout.v1:tara'))).not.toContain('Local Test');expect(errors).toEqual([]);
  await page.screenshot({path:testInfo.outputPath(`${theme}-${width}-confirmation.png`),fullPage:true});
 });
}
test('mockHTTP ambiguous timeout -> reload -> exact same-key retry; no fake confirmation',async({page})=>{
 await harness(page);const requests=[];
 await page.route('**/api/v1/storefronts/tara/checkout',async route=>{requests.push(route.request().postDataJSON());if(requests.length===1)await route.abort('failed');else await route.fulfill({status:201,json:order});});
 await page.goto('/live-test');let form=await bagToCheckout(page);await form.getByRole('button',{name:'Place order',exact:true}).click();await expect(form.getByRole('alert')).toContainText('could not confirm');await expect(form.getByText('Your order is received.')).toHaveCount(0);
 await page.reload();form=page.getByRole('dialog',{name:'Checkout',exact:true});await expect(form.getByLabel('Full name')).toHaveAttribute('readonly','');await form.getByRole('button',{name:'Check this attempt again'}).click();await expect(form.getByText('Your order is received.',{exact:true})).toBeVisible();expect(requests).toHaveLength(2);expect(requests[1]).toEqual(requests[0]);
});
test('mockHTTP definitive stock409 -> edited details and changed quantity get fresh intent',async({page})=>{
 await harness(page);const requests=[];
 await page.route('**/api/v1/storefronts/tara/checkout',async route=>{requests.push(route.request().postDataJSON());await route.fulfill(requests.length===1?{status:409,json:{code:'stock_conflict'}}:{status:201,json:order});});
 await page.goto('/live-test');const form=await bagToCheckout(page);await form.getByRole('button',{name:'Place order',exact:true}).click();await expect(form.getByRole('alert')).toContainText('no longer available');await form.getByLabel('Full name').fill('Edited Person');await form.getByRole('button',{name:'Review details and retry'}).click();await expect(form.getByText('Your order is received.',{exact:true})).toBeVisible();expect(requests[1].customer.name).toBe('Edited Person');expect(requests[1].idempotency_key).not.toBe(requests[0].idempotency_key);
});
