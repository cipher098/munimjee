/* Actual native catalogue UI/main/PG0052 and signed synthetic inbound/outbox. */
import {chromium,expect} from '../../../frontend/storefront/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';
import {createHash,createHmac,randomUUID} from 'node:crypto';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
const origin='http://127.0.0.1:8156',out=new URL('../../../artifacts/v1/sku-facts/',import.meta.url),browser=await chromium.launch(),results=[],errors=[],external=[],observed=[];
await mkdir(out,{recursive:true});
async function check(name,fn){await fn();results.push(name);}
async function owner(mobile=false){
 const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1365,height:1000}});
 await context.route('**/*',route=>{if(route.request().url().startsWith(origin+'/'))return route.continue();external.push(route.request().url());return route.abort();});
 const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
 for(let n=0;n<50;n++){try{await page.goto(origin+'/v1');break;}catch(e){if(n===49)throw e;await new Promise(r=>setTimeout(r,200));}}
 const signup=await page.request.post(origin+'/api/v1/auth/signup',{headers:{Origin:origin},data:{email:`sku-${randomUUID()}@example.com`,password:'synthetic-sku-password',business_name:'Synthetic SKU Boutique'}});assert.equal(signup.status(),201);
 const me=await signup.json(),bid=me.businesses[0].id,headers={Origin:origin,'X-CSRF-Token':me.csrf_token},base=`/api/v1/businesses/${bid}/catalogue`;
 const store={name:'Synthetic SKU Boutique',slug:'sku-'+randomUUID().slice(0,12),published:true,cod_enabled:false};
 assert.equal((await page.request.put(origin+base+'/storefront',{headers,data:store})).status(),200);
 await page.goto(origin+`/v1/businesses/${bid}/catalogue`);await expect(page.locator('#workspace')).toBeVisible();
 return{context,page,bid,headers,base,store};
}
async function prepare(f){
 const{page}=f;await page.locator('#draft-editor').evaluate(e=>e.open=true);
 await page.locator('#draft-form [name=name]').fill('Synthetic SKU dress');await page.locator('#draft-form [name=description]').fill('Private description must stay out of automated facts.');
 await page.locator('#sku-rows [name=price]').fill('123.45');await page.locator('#sku-rows [name=stock]').fill('4');
 await page.locator('#sku-rows').getByRole('button',{name:'Add an option',exact:true}).click();
 await page.locator('#sku-rows [name=option-name]').fill('Size');await page.locator('#sku-rows [name=option-value]').fill('M');
 await page.locator('#draft-reviewed').check();await page.getByRole('button',{name:'Save reviewed draft',exact:true}).click();
 await expect(page.locator('#product-list')).toContainText('Synthetic SKU dress');await page.getByRole('button',{name:'Review product',exact:true}).click();
 await expect(page.locator('#activation-form')).toBeVisible();await page.locator('#activation-reviewed').check();await page.getByRole('button',{name:'Activate product',exact:true}).click();await expect(page.locator('#inventory-form')).toBeVisible();
 const list=await(await page.request.get(origin+f.base+'/products')).json(),pid=list.items[0].product.product_id;
 const bind=await page.request.post(origin+`/__test/sku-facts/${f.bid}/${pid}/bind`,{headers:f.headers});assert.equal(bind.status(),200);f.fixture=await bind.json();f.pid=pid;
}
async function signed(f,channel,text,mid=randomUUID(),valid=true){
 const stamp=Date.now(),v=f.fixture;
 const payload=channel==='instagram'?{object:'instagram',entry:[{id:v.instagram_account,messaging:[{sender:{id:v.customer},recipient:{id:v.instagram_account},timestamp:stamp,message:{mid,text}}]}]}:
 {object:'whatsapp_business_account',entry:[{id:v.waba,changes:[{field:'messages',value:{metadata:{phone_number_id:v.whatsapp_account},messages:[{id:mid,from:'919876543210',timestamp:String(Math.floor(stamp/1000)),type:'text',text:{body:text}}]}}]}]};
 const raw=JSON.stringify(payload),signature='sha256='+createHmac('sha256',valid?'synthetic-sku-signature':'wrong-synthetic-signature').update(raw).digest('hex');
 const response=await f.page.request.post(origin+'/webhooks/'+channel,{data:raw,headers:{'Content-Type':'application/json','X-Hub-Signature-256':signature}});assert.equal(response.status(),valid?200:403);return mid;
}
async function drain(f){const r=await f.page.request.post(origin+`/__test/sku-facts/${f.bid}/drain`,{headers:f.headers});assert.equal(r.status(),200);return r.json();}
async function inventory(f,price,stock=null){
 await f.page.locator('#inventory-rows [name=price]').fill(price);
 await f.page.locator('#inventory-rows [name=untracked]').setChecked(stock===null);
 if(stock!==null)await f.page.locator('#inventory-rows [name=stock]').fill(String(stock));
 await f.page.locator('#inventory-reviewed').check();await f.page.getByRole('button',{name:'Save inventory',exact:true}).click();await expect(f.page.locator('#notice')).toHaveText('Inventory saved.');await expect(f.page.locator('#inventory-form')).toBeVisible();
}
try{
 await check('desktop native reviewed draft and explicit activation; pending signed channels regenerate after UI price/stock update',async()=>{const f=await owner();try{
  await prepare(f);await signed(f,'instagram','price?');await signed(f,'whatsapp','https://instagram.com/reel/Synthetic_sku/ price?');
  await inventory(f,'456.78',0);const data=await drain(f);assert.equal(data.sends.length,2);for(const send of data.sends){assert.ok(send.text.includes('₹456.78'));assert.ok(send.text.includes('recorded out of stock'));assert.ok(!send.text.includes('123.45')&&!send.text.includes('Private description'));assert.ok(send.text.includes('not a reservation'));}assert.deepEqual(data.mutations,{orders:0,reservations:0,cycles:0});observed.push(...data.sends);
  await f.page.screenshot({path:new URL('desktop-current-inventory.png',out).pathname,fullPage:true});
 }finally{await f.context.close();}});
 await check('mobile untracked stock stays unknown and both existing writers remain once-only across duplicate MID/drain',async()=>{const f=await owner(true);try{
  await prepare(f);await inventory(f,'234.56',null);const ig=await signed(f,'instagram','available?'),wa=await signed(f,'whatsapp','https://instagram.com/reel/Synthetic_sku/ available?');await signed(f,'instagram','available?',ig);await signed(f,'whatsapp','https://instagram.com/reel/Synthetic_sku/ available?',wa);
  const data=await drain(f);assert.equal(data.sends.length,2);for(const send of data.sends){assert.ok(send.text.includes('₹234.56')&&send.text.includes('availability untracked'));assert.ok(!send.text.includes('In stock'));}assert.equal((await drain(f)).sends.length,2);assert.deepEqual(data.mutations,{orders:0,reservations:0,cycles:0});observed.push(...data.sends);
  assert.ok(await f.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await f.page.locator('#product-detail').scrollIntoViewIfNeeded();await f.page.screenshot({path:new URL('mobile-untracked-inventory.png',out).pathname,fullPage:true});
 }finally{await f.context.close();}});
 await check('unpublished storefront blocks already queued IG/WA fact sends',async()=>{const f=await owner();try{
  await prepare(f);await signed(f,'instagram','price?');await signed(f,'whatsapp','https://instagram.com/reel/Synthetic_sku/ price?');assert.equal((await f.page.request.put(origin+f.base+'/storefront',{headers:f.headers,data:{...f.store,published:false}})).status(),200);const data=await drain(f);assert.equal(data.sends.length,0);assert.deepEqual(data.mutations,{orders:0,reservations:0,cycles:0});
 }finally{await f.context.close();}});
 await check('invalid signed channel sources create no automated send',async()=>{const f=await owner();try{
  await prepare(f);await signed(f,'instagram','price?',randomUUID(),false);await signed(f,'whatsapp','https://instagram.com/reel/Synthetic_sku/ price?',randomUUID(),false);assert.equal((await drain(f)).sends.length,0);
 }finally{await f.context.close();}});
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 const files=['backend/app/schemas/sku_fact_replies.py','backend/app/services/sku_fact_replies.py','backend/app/services/whatsapp_context.py','backend/app/bot/conversation.py','backend/app/workers/message_batch.py','backend/app/config.py','backend/app/main.py'];
 await writeFile(new URL('browser-results.json',out),JSON.stringify({source_commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),hashes:Object.fromEntries(await Promise.all(files.map(async file=>[file,createHash('sha256').update(await readFile(new URL('../../../'+file,import.meta.url))).digest('hex')]))),checks:results.length,results,observed,errors,external,proof_scope:'Actual app.main/PG0052/native sessions/catalogue UI + synthetic configured account bindings, signed synthetic provider ingress and in-process fake provider transports. No live Meta/customer delivery or provider acceptance.'},null,2)+'\n');console.log(`PASS ${results.length} mounted native SKU/channel journeys; providers synthetic.`);
}finally{await browser.close();}
