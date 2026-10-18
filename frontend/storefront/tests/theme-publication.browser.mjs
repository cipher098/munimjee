// Real SSR fixture output + actual live/payment/status JS with controlled HTTP.
// Synthetic provider, mocked orders/provider and desktop Chromium emulation only.
import {test,before,after} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
const {chromium}=await import(process.env.THEME_PLAYWRIGHT_MODULE||'/Users/user/Documents/ChatGPT/munimjee-wave3-qa/frontend/storefront/node_modules/playwright/index.mjs');
const base='http://127.0.0.1:4321',out=path.join(repo,'artifacts/v1/theme-settings/public-browser'),fixtures=path.join(repo,'artifacts/v1/theme-settings/public-provider');
const pid='22222222-2222-4222-8222-222222222201',oid='55555555-5555-4555-8555-555555555501',category='44444444-4444-4444-8444-444444444401';
const modules=['styles.css','live.css','live-entry.js','live-app.js','components.js','commerce.js','theme-config.js','published-design.js','live-api.js','canonical-contract.js','checkout-attempt.js','payment-handoff.js','order-status.js'];
let browser,server,fixtureHeaders;
before(async()=>{await mkdir(out,{recursive:true});fixtureHeaders=JSON.parse(await readFile(path.join(fixtures,'headers.json'),'utf8'));server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,base);let target,headers={};
 if(url.pathname.startsWith('/storefront-assets/src/')&&modules.includes(url.pathname.slice('/storefront-assets/src/'.length)))target=path.join(repo,'frontend/storefront/src',path.basename(url.pathname));
 else if(/^\/theme-assets\/(rose|indigo|sage|ivory)\.svg$/.test(url.pathname))target=path.join(repo,'frontend/storefront/assets',path.basename(url.pathname));
 else {const match=url.pathname.match(/^\/(?:stores\/synthetic-(editorial|catalogue|video)(.*)|preview\/(editorial|catalogue|video))$/);if(match){const theme=match[1]||match[3],kind=match[3]?'preview':!match[2]?'home':match[2].startsWith('/products/')?'pdp':match[2].startsWith('/categories/')?'category':match[2].startsWith('/orders/')?'status':null;if(kind){target=path.join(fixtures,`${theme}-${kind}.html`);headers=fixtureHeaders[`${theme}-${kind}.html`];}}}
 if(!target){res.writeHead(404).end();return;}try{const bytes=await readFile(target);res.writeHead(200,{...headers,'Content-Type':target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':target.endsWith('.svg')?'image/svg+xml':'text/html; charset=utf-8'});res.end(bytes);}catch{res.writeHead(404).end();}
 });await new Promise(resolve=>server.listen(4321,'127.0.0.1',resolve));browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||'/Users/user/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'});});
after(async()=>{await browser?.close();await new Promise(resolve=>server?.close(resolve));});
async function shop(theme,width,{loseResponse=false}={}){
 const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[],external=[],requests=[],state={order:null,paid:false,loseResponse};page.setDefaultTimeout(8000);page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{if(route.request().url().startsWith(base+'/'))return route.continue();external.push(route.request().url());return route.abort();});
 await page.addInitScript(()=>{window.__syntheticSdk=[];window.Razorpay=class{constructor(options){this.options=options;}open(){window.__syntheticSdk.push({key:this.options.key,order_id:this.options.order_id,amount:this.options.amount,currency:this.options.currency});setTimeout(()=>this.options.handler({razorpay_order_id:this.options.order_id,razorpay_payment_id:'pay_Synthetic1',razorpay_signature:'a'.repeat(64)}),10);}};});
 const slug=`synthetic-${theme}`,api=`/api/v1/storefronts/${slug}`,orderPath=`${api}/orders/${oid}`;
 await page.route('**/api/v1/storefronts/**',async route=>{
  const request=route.request(),url=new URL(request.url());requests.push({path:url.pathname,method:request.method(),body:request.postData(),authorization:request.headers().authorization});
  if(url.pathname===api+'/checkout'){
   const body=request.postDataJSON();
   if(!state.order)state.order={contract_version:'order.v1',id:oid,number:'SYNTHETIC-001',access_token:'c'.repeat(64),customer:body.customer,address:body.address,subtotal:129950,shipping_fee:5000,total:134950,currency:'INR',payment_method:body.payment_method,payment_status:'pending',fulfillment_status:'pending',items:[{product_id:pid,sku_id:body.items[0].sku_id,name:'Synthetic Rose Set',options:{Size:'M'},currency:'INR',quantity:1,unit_price:129950,line_total:129950,photo_url:null}]};
   assert.equal(body.idempotency_key,JSON.parse(requests.find(item=>item.path===api+'/checkout').body).idempotency_key);
   if(state.loseResponse){state.loseResponse=false;return route.abort('failed');}
   return route.fulfill({status:requests.filter(item=>item.path===api+'/checkout').length>1?200:201,json:state.order});
  }
  const paymentState=()=>({contract_version:'checkout-state.v1',order_id:oid,amount_minor:134950,currency:'INR',payment_status:state.paid?'paid':'pending',fulfillment_status:'pending',attempt_state:state.paid?'ready':'not_started',expires_at:null,retry_allowed:!state.paid});
  if(url.pathname===orderPath+'/checkout-session/verify'){
   assert.equal(request.headers().authorization,'Bearer synthetic.session.token');assert.equal(request.postDataJSON().razorpay_order_id,'order_Synthetic1');state.paid=true;return route.fulfill({json:paymentState()});
  }
  if(url.pathname===orderPath+'/checkout-session'){
   assert.equal(request.headers().authorization,'Bearer '+'c'.repeat(64));
   if(request.method()==='GET')return route.fulfill({json:paymentState()});
   return route.fulfill({json:{contract_version:'checkout-session.v1',order_id:oid,provider:'razorpay',provider_order_id:'order_Synthetic1',key_id:'rzp_test_Synthetic1',mode:'test',amount_minor:134950,currency:'INR',session_token:'synthetic.session.token',expires_at:new Date(Date.now()+600000).toISOString(),merchant_name:'Synthetic Boutique',prefill:{name:'Synthetic Buyer',contact:'9876543210',email:''},verify_url:orderPath+'/checkout-session/verify',status_url:orderPath+'/checkout-session',order_status_url:orderPath}});
  }
  if(url.pathname===orderPath){
   if(request.headers().authorization!=='Bearer '+'c'.repeat(64))return route.fulfill({status:404,json:{detail:'Unavailable'}});
   const {access_token,...order}=state.order;return route.fulfill({json:{...order,payment_status:state.paid?'paid':'pending'}});
  }
  return route.fulfill({status:404,json:{detail:'Unexpected synthetic request'}});
 });
 await page.goto(`${base}/stores/${slug}`);await page.getByRole('button',{name:'Bag (0)',exact:true}).waitFor();
 return {context,page,state,requests,errors,external,slug,orderPath};
}
async function checkout(page,method){
 await page.getByRole('link',{name:'View Synthetic Rose Set',exact:true}).click();const detail=page.getByRole('dialog',{name:'A closer look'});await detail.getByRole('radio',{name:/M/}).check();await detail.getByRole('button',{name:/Add to bag/}).click();await page.getByRole('dialog',{name:'Your bag'}).getByRole('button',{name:'Continue to checkout',exact:true}).click();const form=page.getByRole('dialog',{name:'Checkout',exact:true});
 for(const [label,value] of [['Full name','Synthetic Buyer'],['Indian mobile number','9876543210'],['Address','Synthetic Street'],['City','Bengaluru'],['State','Karnataka'],['PIN code','560001']])await form.getByLabel(label,{exact:true}).fill(value);
 await form.getByLabel('Payment method').selectOption(method);return form;
}
for(const theme of ['editorial','catalogue','video'])for(const width of [390,1440])for(const method of ['cod','razorpay'])test(`synthetic provider actual SSR/live ${theme} ${width} ${method} canonical wire -> private status`,async()=>{
 const x=await shop(theme,width),{page,requests}=x;
 try{
  assert.equal(await page.locator('html').getAttribute('data-theme'),theme);assert.equal(await page.locator('html').getAttribute('class'),`palette-${{editorial:'rose',catalogue:'forest',video:'indigo'}[theme]}`);
  assert.equal(await page.locator('.hero h1').innerText(),`Your ${theme}\ncollection.`);assert.equal(await page.locator('.published-story h2').innerText(),'Pieces with a story');assert.equal(await page.locator('.brand-tagline').innerText(),'A thoughtful collection');
  const ink=await page.locator('.collection').evaluate(node=>({color:getComputedStyle(node).color,background:getComputedStyle(node).backgroundColor}));
  if(theme==='video')assert.deepEqual(ink,{color:'rgb(41, 44, 71)',background:'rgb(247, 247, 252)'});
  assert.equal(await page.locator('.product-card').count(),4);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  if(method==='cod')await page.screenshot({path:path.join(out,`${theme}-${width}-published.png`),fullPage:true});
  const form=await checkout(page,method);await form.getByRole('button',{name:'Place order',exact:true}).click();await form.getByText('Your order is received.',{exact:true}).waitFor();await form.getByText(`Payment: ${method==='cod'?'Pending':'Paid'}`,{exact:true}).waitFor();
  assert.equal(requests.filter(request=>request.path.endsWith('/checkout')).length,1);
  assert.equal(await page.evaluate(()=>window.__syntheticSdk.length),method==='cod'?0:1);
  const journal=await page.evaluate(slug=>sessionStorage.getItem(`munimjee.checkout.v1:${slug}`),x.slug);assert.ok(!journal.includes('Synthetic Buyer')&&!journal.includes('Synthetic Street')&&!journal.includes('synthetic.session.token'));
  await form.getByRole('button',{name:'Check order status',exact:true}).click();await form.locator('.payment-status-message').filter({hasText:'Checking the saved order…'}).waitFor({state:'hidden'});
  await form.getByRole('link',{name:'Open order status page',exact:true}).click();await page.getByRole('status').filter({hasText:'Order status checked.'}).waitFor();assert.equal(page.url().includes('token'),false);
  assert.equal(await page.getByText(`Payment: ${method==='cod'?'pending':'paid'}`,{exact:true}).count(),1);
  await page.reload();await page.getByRole('status').filter({hasText:'Order status checked.'}).waitFor();
  assert.ok(requests.filter(request=>request.path===x.orderPath).every(request=>request.authorization==='Bearer '+'c'.repeat(64)));
  assert.deepEqual(x.errors,[]);assert.deepEqual(x.external,[]);
 }finally{await x.context.close();}
});
for(const theme of ['editorial','catalogue','video'])test(`synthetic provider ${theme} ambiguous COD -> reload immutable retry`,async()=>{
 const x=await shop(theme,390,{loseResponse:true}),{page,requests}=x;try{const form=await checkout(page,'cod');await form.getByRole('button',{name:'Place order',exact:true}).click();await form.getByRole('alert').filter({hasText:'could not confirm'}).waitFor();await page.reload();const retry=page.getByRole('dialog',{name:'Checkout',exact:true});await retry.getByRole('button',{name:'Check this attempt again'}).click();await retry.getByText('Your order is received.',{exact:true}).waitFor();const commands=requests.filter(request=>request.path.endsWith('/checkout'));assert.equal(commands.length,2);assert.equal(commands[0].body,commands[1].body);assert.deepEqual(x.errors,[]);assert.deepEqual(x.external,[]);}finally{await x.context.close();}
});
for(const theme of ['editorial','catalogue','video'])test(`synthetic published provider ${theme} SSR without JS; presentation routes and private preview`,async()=>{
 const context=await browser.newContext({javaScriptEnabled:false,viewport:{width:390,height:900}}),page=await context.newPage();try{
 for(const route of ['',`/products/${pid}`,`/categories/${category}`]){await page.goto(`${base}/stores/synthetic-${theme}${route}`);assert.equal(await page.getByText('Synthetic Rose Set',{exact:true}).count()>=1,true);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
 await page.goto(`${base}/preview/${theme}`);assert.equal(await page.getByRole('heading',{name:`Private ${theme} draft`,exact:true}).count(),1);assert.equal(await page.locator('script,form').count(),0);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:path.join(out,`${theme}-390-private-preview.png`),fullPage:true});
 }finally{await context.close();}
});
