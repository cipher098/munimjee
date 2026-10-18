/* Actual app.main/native/theme/publication/SKU APIs; no payment or provider calls. */
import {chromium,expect} from '../../../../munimjee-v1/frontend/storefront/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';
import {mkdir,writeFile,readFile,readdir} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const origin='https://127.0.0.1:8156',root=new URL('../../..',import.meta.url),out=new URL('artifacts/v1/independent-storefront-experience/cart-repair-mounted/',root);
await mkdir(out,{recursive:true});
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const paths=(await readdir(new URL('frontend/storefront/src/',root))).filter(name=>/\.(js|css)$/.test(name)).map(name=>'frontend/storefront/src/'+name);
const snapshot=async()=>Object.fromEntries(await Promise.all(paths.map(async name=>[name,hash(await readFile(new URL(name,root)))])));
const before=await snapshot(),head=execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
const browser=await chromium.launch(),contexts=[],results=[],errors=[],external=[],prohibited=[];
async function context(viewport={width:1365,height:1000}){
 const c=await browser.newContext({viewport,ignoreHTTPSErrors:true,serviceWorkers:'block'});contexts.push(c);
 await c.route('**/*',route=>{const request=route.request(),url=new URL(request.url());if(url.origin!==origin){external.push(url.origin);return route.abort();}if(/\/checkout(?:-session)?(?:\/|$)|\/payments\//.test(url.pathname)&&request.method()!=='GET'){prohibited.push(url.pathname);return route.abort();}return route.continue();});
 return c;
}
async function setup(theme,palette){
 const owner=await context(),page=await owner.newPage();page.on('pageerror',e=>errors.push(e.message));
 for(let index=0;index<60;index++){try{await page.goto(origin+'/v1');break;}catch(error){if(index===59)throw error;await new Promise(resolve=>setTimeout(resolve,200));}}
 const signup=await page.request.post(origin+'/api/v1/auth/signup',{headers:{Origin:origin},data:{email:`cart-${randomUUID()}@example.com`,password:'synthetic-cart-fallback-password',business_name:`Synthetic ${theme} bag boutique`}});assert.equal(signup.status(),201);
 const me=await signup.json(),bid=me.businesses[0].id,slug='cart-'+randomUUID().slice(0,12),headers={Origin:origin,'X-CSRF-Token':me.csrf_token},catalogue=`/api/v1/businesses/${bid}/catalogue`,themePath=`/api/v1/businesses/${bid}/theme-settings`;
 async function write(path,data,method='POST'){const response=await page.request.fetch(origin+path,{method,headers,data});assert.ok(response.ok(),`${method} ${path}: ${response.status()} ${await response.text()}`);return response.json();}
 const store={name:`Synthetic ${theme} bag boutique`,slug,description:'Literal local cart-fallback fixture.',shipping_fee:0,currency:'INR',cod_enabled:true,published:false,shipping_policy:'Confirm delivery with the boutique.',return_policy:'Contact the boutique.'};
 await write(catalogue+'/storefront',store,'PUT');
 const made=await write(catalogue+'/products',{idempotency_key:randomUUID(),seller_reviewed:true,name:'Independent occasion dress',description:'Literal synthetic reviewed garment.',photo_urls:[],skus:[{options:{Size:'M'},price_minor:129950,currency:'INR',stock_available:2,active:true}]});
 const product=made.product.product_id;await write(catalogue+`/products/${product}/activate`,{seller_reviewed:true,expected_mapping_revision:made.mapping_revision,expected_legacy_fingerprint:made.legacy_fingerprint});
 const original=await(await page.request.get(origin+themePath)).json();const saved=await write(themePath,{idempotency_key:randomUUID(),expected_version:original.version,config:{...original.draft,theme,palette}},'PUT');await write(themePath+'/publish',{idempotency_key:randomUUID(),expected_version:saved.version});
 await write(catalogue+'/storefront',{...store,published:true},'PUT');await write(catalogue+'/checkout-policy',{checkout_enabled:true},'PUT');
 const html=await(await page.request.get(origin+`/stores/${slug}`)).text();assert.match(html,/Independent occasion dress/);assert.match(html,new RegExp(`data-theme="${theme}"`));assert.doesNotMatch(html,/floor_price|access_token|password_hash/);
 return {owner,page,bid,slug};
}
try{
 for(const [theme,palette]of [['editorial','rose'],['catalogue','forest'],['video','indigo']]){
  const data=await setup(theme,palette);
  for(const width of [320,390]){
   const c=await context({width,height:844}),page=await c.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));await page.goto(origin+'/stores/'+data.slug);
   assert.equal(await page.locator('html').getAttribute('data-theme'),theme);await page.getByRole('link',{name:'View Independent occasion dress',exact:true}).click();const detail=page.getByRole('dialog',{name:'A closer look',exact:true});await detail.getByRole('radio',{name:/^M /}).check();await detail.getByRole('button',{name:/Add to bag/}).click();const bag=page.getByRole('dialog',{name:'Your bag',exact:true});
   const layout=await bag.locator('.cart-line').evaluate(node=>{const title=node.querySelector('h3'),price=node.querySelector(':scope > strong'),range=document.createRange();range.selectNodeContents(title);const plain=rect=>({left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,width:rect.width,height:rect.height});const titleRects=[...range.getClientRects()].map(plain),priceRange=document.createRange();priceRange.selectNodeContents(price);const priceRect=plain(priceRange.getBoundingClientRect());return {title:title.textContent,price:price.textContent,titleRects,priceRect,overlaps:titleRects.filter(rect=>Math.min(rect.right,priceRect.right)-Math.max(rect.left,priceRect.left)>0.5&&Math.min(rect.bottom,priceRect.bottom)-Math.max(rect.top,priceRect.top)>0.5)};});
   assert.equal(layout.overlaps.length,0,`Product title overlaps line price: ${JSON.stringify(layout)}`);await expect(bag.getByText('Image unavailable',{exact:true})).toBeVisible();await expect(bag.getByRole('button',{name:'Continue to checkout',exact:true})).toBeEnabled();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.equal(await bag.evaluate(node=>node.scrollWidth>node.clientWidth),false);
   await page.screenshot({path:new URL(`${theme}-${width}-bag.png`,out).pathname});results.push({theme,width,result:'passed',layout});console.log(`PASS actual mounted ${theme} ${width}px missing-photo title/price`);await c.close();
  }
  assert.equal((await(await data.page.request.get(origin+`/api/v1/businesses/${data.bid}/orders`)).json()).total,0);await data.owner.close();
 }
 assert.deepEqual(external,[]);assert.deepEqual(prohibited,[]);assert.deepEqual(errors,[]);const after=await snapshot();assert.deepEqual(after,before);
 await writeFile(new URL('result.json',out),JSON.stringify({mode:'actual-app.main-native-API-P01-migrated0056-publication-no-payment-or-provider',source_head:head,checks_passed:results.length,results,source_hashes_before:before,source_hashes_after:after,source_unchanged:true,external_requests:external,prohibited_financial_requests:prohibited,page_errors:errors,tls:'ephemeral self-signed loopback; ignoreHTTPSErrors, no public/providerTLS claim',runner_sha256:hash(await readFile(new URL(import.meta.url)))},null,2)+'\n');
}catch(error){await writeFile(new URL('failure.txt',out),error.stack||String(error));throw error;}
finally{for(const c of contexts)await c.close();await browser.close();}
