/* Independent QA: fresh actual SSR + actual modules, all HTTP fulfilled/denied. */
import assert from 'node:assert/strict';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const root=new URL('../..',import.meta.url),out=new URL('../../artifacts/v1/independent-storefront-experience/',import.meta.url),fixtures=new URL('fixtures/',out);
const modulePath=process.env.MUNIMJEE_PLAYWRIGHT_MODULE;
if(!modulePath||!process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE)throw new Error('Explicit cached Playwright and Chromium paths required; no installation or server fallback.');
const {chromium,expect:playwrightExpect}=await import(pathToFileURL(modulePath).href);
const expect=playwrightExpect.configure({timeout:2500});
const metadata=JSON.parse(await readFile(new URL('metadata.json',fixtures))),base='https://storefront-experience.example.test';
const sourceHead=execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
const sourcePaths=Object.keys(metadata.source_hashes_before);
const hash=body=>createHash('sha256').update(body).digest('hex');
const snapshot=async()=>Object.fromEntries(await Promise.all(sourcePaths.map(async name=>[name,hash(await readFile(new URL(name,root)))])));
const before=await snapshot();assert.deepEqual(before,metadata.source_hashes_before,'fresh fixture source hash mismatch');
const assetDir=new URL('frontend/storefront/src/',root),assetNames=(await readdir(assetDir)).filter(name=>/\.(js|css)$/.test(name));
const assets=Object.fromEntries(await Promise.all(assetNames.map(async name=>[name,await readFile(new URL(name,assetDir))])));
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const results=[],unexpected=[],pageErrors=[],observations=[];let active=[];
const themes=['editorial','catalogue','video'];
async function setup(theme,{variant='standard',viewport={width:390,height:844},javascript=true,refresh='success',checkout='abort'}={}){
 const context=await browser.newContext({viewport,javaScriptEnabled:javascript,serviceWorkers:'block'});active.push(context);
 const filename=`${theme}-${variant}.html`,html=await readFile(new URL(filename,fixtures));assert.equal(hash(html),metadata.fixture_hashes[filename]);
 const model={refreshCalls:[],checkoutCalls:[],releaseRefresh:null,releaseCheckout:null};
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname;
  if(url.origin!==base){unexpected.push({kind:'origin',url:url.href});return route.abort('blockedbyclient');}
  if(path==='/stores/experience'&&request.method()==='GET')return route.fulfill({contentType:'text/html',body:html});
  if(path.startsWith('/storefront-assets/src/')&&request.method()==='GET'){
   const name=path.slice('/storefront-assets/src/'.length);
   if(Object.hasOwn(assets,name))return route.fulfill({contentType:name.endsWith('.js')?'application/javascript':'text/css',body:assets[name]});
  }
  if(path==='/api/v1/storefronts/experience/products'&&request.method()==='GET'){
   model.refreshCalls.push(url.search);
   if(refresh==='deferred')await new Promise(resolve=>{model.releaseRefresh=resolve;});
   if(refresh==='abort')return route.abort('failed');
   if(refresh==='server500')return route.fulfill({status:500,json:{detail:'Synthetic service unavailable'}});
   if(refresh==='malformed')return route.fulfill({status:200,json:{items:[{product_id:'malformed'}],total:1,page:1,page_size:100}});
   if(refresh==='invalid_json')return route.fulfill({contentType:'application/json',body:'{broken'});
   if(refresh==='empty')return route.fulfill({json:{items:[],total:0,page:1,page_size:100}});
   return route.fulfill({json:{items:[metadata.api_product],total:1,page:1,page_size:100}});
  }
  if(path==='/api/v1/storefronts/experience/checkout'&&request.method()==='POST'){
   model.checkoutCalls.push(request.postDataJSON());
   if(checkout==='deferred')await new Promise(resolve=>{model.releaseCheckout=resolve;});
   if(checkout==='abort'||checkout==='deferred')return route.abort('failed');
   if(checkout==='stock')return route.fulfill({status:409,json:{detail:{code:'sku_out_of_stock',message:'Synthetic sold out'}}});
   if(checkout==='malformed')return route.fulfill({status:201,json:{contract_version:'order.v1',id:'bad'}});
   return route.fulfill({status:500,json:{detail:'Synthetic failure'}});
  }
  unexpected.push({kind:'unhandled',method:request.method(),path});return route.abort('blockedbyclient');
 });
 const page=await context.newPage();page.setDefaultTimeout(2500);page.on('pageerror',error=>pageErrors.push(error.message));
 await page.goto(base+'/stores/experience');
 if(javascript)await expect(page.getByRole('button',{name:'Bag (0)',exact:true})).toBeVisible();
 return {page,context,model};
}
async function check(name,run){
 const started=Date.now();
 try{await run();results.push({name,result:'passed',elapsed_ms:Date.now()-started});}
 catch(error){results.push({name,result:'failed',message:error.message,elapsed_ms:Date.now()-started});console.error('FAIL '+name+' '+error.message.split('\n')[0]);}
 finally{for(const context of active.splice(0))await context.close();}
}
async function noOverflow(page,dialog){
 const actual=await page.evaluate(()=>({width:innerWidth,page:document.documentElement.scrollWidth}));
 assert(actual.page<=actual.width+1,`page horizontal overflow: ${JSON.stringify(actual)}`);
 if(dialog){const sizes=await dialog.evaluate(node=>({width:node.clientWidth,scroll:node.scrollWidth,bodyWidth:node.querySelector('.dialog-body').clientWidth,bodyScroll:node.querySelector('.dialog-body').scrollWidth}));assert(sizes.scroll<=sizes.width+1&&sizes.bodyScroll<=sizes.bodyWidth+1,`dialog horizontal overflow: ${JSON.stringify(sizes)}`);}
}
async function openProduct(page){await page.getByRole('link',{name:'View Independent occasion dress',exact:true}).click();return page.getByRole('dialog',{name:'A closer look',exact:true});}
async function openCheckout(page){const detail=await openProduct(page);await detail.getByRole('radio',{name:/^M /}).check();await detail.getByRole('button',{name:/Add to bag/}).click();const bag=page.getByRole('dialog',{name:'Your bag',exact:true});await bag.getByRole('button',{name:'Continue to checkout',exact:true}).click();return page.getByRole('dialog',{name:'Checkout',exact:true});}
async function fill(form){for(const [name,value]of [['Full name','Synthetic Buyer'],['Indian mobile number','9876543210'],['Address','Synthetic Street'],['City','Bengaluru'],['State','Karnataka'],['PIN code','560001']])await form.getByLabel(name,{exact:true}).fill(value);}
async function keyboardActivate(locator,page){await locator.focus();await page.keyboard.press('Enter');}
try{
 await mkdir(out,{recursive:true});
 for(const theme of themes){
  for(const viewport of [{width:320,height:740},{width:360,height:800},{width:390,height:844},{width:844,height:390},{width:768,height:1024},{width:1440,height:1000}]){
   await check(`${theme} ${viewport.width}x${viewport.height}: public layout and product/bag/checkout dialogs fit`,async()=>{
    const {page}=await setup(theme,{viewport});await noOverflow(page);const detail=await openProduct(page);await noOverflow(page,detail);
    await detail.getByRole('radio',{name:/^M /}).check();await detail.getByRole('button',{name:/Add to bag/}).click();const bag=page.getByRole('dialog',{name:'Your bag',exact:true});await noOverflow(page,bag);
    if(viewport.width===320)await page.screenshot({path:new URL(`${theme}-320-bag.png`,out).pathname});
    await bag.getByRole('button',{name:'Continue to checkout',exact:true}).click();const checkout=page.getByRole('dialog',{name:'Checkout',exact:true});await noOverflow(page,checkout);
    await checkout.getByLabel('PIN code',{exact:true}).scrollIntoViewIfNeeded();await expect(checkout.getByLabel('PIN code',{exact:true})).toBeInViewport();
    if(viewport.width===390||viewport.height===390)await page.screenshot({path:new URL(`${theme}-${viewport.width}-checkout.png`,out).pathname});
   });
  }
  for(const width of [320,390])await check(`${theme} ${width}px: missing-photo bag title does not overlap line price`,async()=>{
   const {page}=await setup(theme,{viewport:{width,height:844}});const detail=await openProduct(page);await detail.getByRole('radio',{name:/^M /}).check();await detail.getByRole('button',{name:/Add to bag/}).click();const bag=page.getByRole('dialog',{name:'Your bag',exact:true});
   const layout=await bag.locator('.cart-line').evaluate(node=>{const title=node.querySelector('h3'),price=node.querySelector(':scope > strong'),range=document.createRange();range.selectNodeContents(title);const plain=rect=>({left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,width:rect.width,height:rect.height});const titleRects=[...range.getClientRects()].map(plain),priceRange=document.createRange();priceRange.selectNodeContents(price);const priceRect=plain(priceRange.getBoundingClientRect());return {title:title.textContent,price:price.textContent,titleRects,priceRect,overlaps:titleRects.filter(rect=>Math.min(rect.right,priceRect.right)-Math.max(rect.left,priceRect.left)>0.5&&Math.min(rect.bottom,priceRect.bottom)-Math.max(rect.top,priceRect.top)>0.5)};});
   observations.push({theme,viewport_width:width,missing_photo_cart_layout:layout});await page.screenshot({path:new URL(`${theme}-${width}-missing-photo-overlap.png`,out).pathname});assert.equal(layout.overlaps.length,0,`Product title overlaps line price: ${JSON.stringify(layout)}`);
  });
  await check(`${theme}: keyboard dialogs trap focus, preserve visible focus and restore triggers`,async()=>{
   const {page}=await setup(theme);const trigger=page.getByRole('link',{name:'View Independent occasion dress',exact:true});await keyboardActivate(trigger,page);
   const dialog=page.getByRole('dialog',{name:'A closer look',exact:true});await expect(dialog).toBeVisible();
   for(let index=0;index<12;index++){await page.keyboard.press('Tab');const focus=await dialog.evaluate(node=>({inside:node.contains(document.activeElement),tag:document.activeElement?.tagName,text:document.activeElement?.textContent?.slice(0,60),documentFocus:document.hasFocus()}));assert(focus.inside||(focus.tag==='BODY'&&focus.documentFocus===false),`Background document control received modal focus: ${JSON.stringify(focus)}`);}
   const medium=dialog.getByRole('radio',{name:/^M /});await medium.focus();await page.keyboard.press('Space');await expect(medium).toBeChecked();
   const focus=await medium.evaluate(node=>({style:getComputedStyle(node).outlineStyle,width:parseFloat(getComputedStyle(node).outlineWidth)}));assert(focus.style!=='none'&&focus.width>=2,'Keyboard focus indicator missing');
   await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();await expect(trigger).toBeFocused();
   const bagButton=page.getByRole('button',{name:'Bag (0)',exact:true});await keyboardActivate(bagButton,page);await expect(page.getByRole('dialog',{name:'Your bag',exact:true})).toBeVisible();await page.keyboard.press('Escape');await expect(bagButton).toBeFocused();
  });
  await check(`${theme}: semantic landmarks, dialog names, form labels and keyboard skip link`,async()=>{
   const {page}=await setup(theme);await expect(page.getByRole('main')).toHaveCount(1);await expect(page.getByRole('heading',{level:1})).toHaveCount(1);
   const skip=page.getByRole('link',{name:'Skip to collection',exact:true});await skip.focus();await expect(skip).toBeInViewport();await page.keyboard.press('Enter');assert.equal(new URL(page.url()).hash,'#collection');
   const form=await openCheckout(page);for(const name of ['Full name','Indian mobile number','Address','City','State','PIN code'])await expect(form.getByLabel(name,{exact:true})).toBeVisible();await expect(form.getByRole('combobox',{name:/^Payment method/})).toBeVisible();
   assert.equal(await form.getByRole('button',{name:'Close ×',exact:true}).count(),1);
   const unnamed=await page.locator('button:visible').evaluateAll(nodes=>nodes.filter(node=>!((node.getAttribute('aria-label')||'').trim()||(node.textContent||'').trim())).length);assert.equal(unnamed,0);
  });
  await check(`${theme}: enabled primary control text and keyboard focus have representative contrast`,async()=>{
   const {page}=await setup(theme);const detail=await openProduct(page);await detail.getByRole('radio',{name:/^M /}).check();const add=detail.getByRole('button',{name:/Add to bag/});await page.keyboard.press('Tab');await add.focus();
   const colors=await add.evaluate(node=>{const style=getComputedStyle(node),paper=getComputedStyle(document.documentElement).getPropertyValue('--paper').trim();const probe=document.createElement('span');probe.style.color=paper;document.body.append(probe);const resolved=getComputedStyle(probe).color;probe.remove();return {foreground:style.color,background:style.backgroundColor,outline:style.outlineColor,outlineStyle:style.outlineStyle,outlineWidth:parseFloat(style.outlineWidth),paper:resolved};});
   const luminance=value=>{const match=value.match(/^rgb\((\d+), (\d+), (\d+)\)$/);assert(match,`Unsupported nonopaque color ${value}`);return match.slice(1).map(Number).map(value=>{value/=255;return value<=0.04045?value/12.92:((value+0.055)/1.055)**2.4;}).reduce((total,value,index)=>total+value*[0.2126,0.7152,0.0722][index],0);};
   const contrast=(a,b)=>{const left=luminance(a),right=luminance(b);return (Math.max(left,right)+0.05)/(Math.min(left,right)+0.05);};observations.push({theme,primary_text_contrast:contrast(colors.foreground,colors.background),keyboard_outline_contrast:contrast(colors.outline,colors.paper),computed_colors:colors});assert(colors.outlineStyle!=='none'&&colors.outlineWidth>=2,'Keyboard focus outline missing');assert(contrast(colors.foreground,colors.background)>=4.5,`Small primary text contrast ${JSON.stringify(colors)}`);assert(contrast(colors.outline,colors.paper)>=3,`Focus contrast ${JSON.stringify(colors)}`);
  });
  await check(`${theme}: sold-out and inactive variants cannot enter bag; untracked stock stays explicit`,async()=>{
   const {page,model}=await setup(theme);const detail=await openProduct(page);
   for(const name of [/^L /,/^XL /]){await detail.getByRole('radio',{name}).check();await expect(detail.getByRole('button',{name:'Unavailable',exact:true})).toBeDisabled();await expect(detail.getByLabel('Quantity',{exact:true})).toBeDisabled();}
   await detail.getByRole('radio',{name:/^S /}).check();await expect(detail.getByText('Availability checked when the order is placed.',{exact:true})).toBeVisible();assert.equal(model.checkoutCalls.length,0);
  });
  await check(`${theme}: empty collection retains visible explanation after hydration`,async()=>{
   const {page}=await setup(theme,{variant:'empty'});await expect(page.locator('#live-count')).toHaveText('0 pieces');await expect(page.getByText('New pieces are on their way.',{exact:true})).toBeVisible();assert.equal(await page.locator('#live-count').getAttribute('aria-live'),'polite');
  });
  await check(`${theme}: filtered-empty count is announced and clearing search restores results`,async()=>{
   const {page}=await setup(theme);const search=page.getByRole('searchbox',{name:'Search products',exact:true});await search.fill('no-such-product');await expect(page.locator('#live-count')).toHaveText('0 pieces');
   assert.equal(await page.locator('#live-count').getAttribute('aria-live'),'polite');await search.focus();await page.keyboard.press('ControlOrMeta+A');await page.keyboard.press('Backspace');await expect(page.locator('.product-card')).toHaveCount(1);
  });
  await check(`${theme}: long published branding and product text fit 320px`,async()=>{const {page}=await setup(theme,{variant:'long',viewport:{width:320,height:740}});await noOverflow(page);});
  await check(`${theme}: JavaScript-off SSR empty collection remains meaningful`,async()=>{const {page}=await setup(theme,{variant:'empty',javascript:false});await expect(page.getByText('No published pieces available.',{exact:true})).toBeVisible();});
  await check(`${theme}: deferred availability refresh shows pending control then restores it`,async()=>{
   const {page,model}=await setup(theme,{refresh:'deferred'});const button=page.getByRole('button',{name:'Refresh availability',exact:true});await button.click();await expect(button).toBeDisabled();await expect(page.locator('.product-card')).toHaveCount(1);
   await expect.poll(()=>typeof model.releaseRefresh).toBe('function');model.releaseRefresh();await expect(button).toBeEnabled();await expect(page.locator('[aria-live=polite]').filter({hasText:'Availability updated.'})).toHaveCount(1);
  });
  for(const failure of ['abort','server500','malformed','invalid_json']){
   await check(`${theme}: ${failure} availability refresh reports failure and preserves catalogue`,async()=>{
    const {page,model}=await setup(theme,{refresh:failure});const button=page.getByRole('button',{name:'Refresh availability',exact:true});await button.click();await expect(button).toBeEnabled();assert.equal(model.refreshCalls.length,1);await expect(page.locator('.product-card')).toHaveCount(1);
    await expect(page.locator('[aria-live=polite]').filter({hasText:/could not|unavailable|failed|verified|unexpected|JSON|fetch/i})).toHaveCount(1);
   });
  }
  for(const failure of ['abort','malformed','stock']){
   await check(`${theme}: ${failure} checkout has accessible error and no invented confirmation`,async()=>{
    const {page,model}=await setup(theme,{checkout:failure});const form=await openCheckout(page);await fill(form);await form.getByRole('button',{name:'Place order',exact:true}).click();await expect(form.getByRole('alert')).not.toBeEmpty();await expect(form.getByText('Your order is received.',{exact:true})).toHaveCount(0);assert.equal(model.checkoutCalls.length,1);
    const saved=JSON.parse(await page.evaluate(()=>sessionStorage.getItem('munimjee.checkout.v1:experience')));assert.equal(saved.state,failure==='stock'?'rejected':'uncertain');
    if(failure!=='stock'){await expect(form.getByLabel('Full name',{exact:true})).toHaveAttribute('readonly','');await expect(form.getByRole('button',{name:'Check this attempt again',exact:true})).toBeEnabled();}
   });
  }
  await check(`${theme}: pending checkout disables repeated submission and retains visible progress`,async()=>{
   const {page,model}=await setup(theme,{checkout:'deferred'});const form=await openCheckout(page);await fill(form);await form.getByRole('button',{name:'Place order',exact:true}).click();await expect(form.getByRole('button',{name:'Checking your order…',exact:true})).toBeDisabled();await expect(form.getByLabel('Full name',{exact:true})).toHaveAttribute('readonly','');assert.equal(model.checkoutCalls.length,1);
   await expect.poll(()=>typeof model.releaseCheckout).toBe('function');model.releaseCheckout();await expect(form.getByRole('alert')).not.toBeEmpty();
  });
 }
 const after=await snapshot(),report={mode:'fresh-actual-SSR-and-live-browser-synthetic-HTTP',source_head:sourceHead,fixture_export:metadata,source_hashes_before:before,source_hashes_after:after,source_unchanged:JSON.stringify(before)===JSON.stringify(after),runner_sha256:hash(await readFile(new URL(import.meta.url))),exporter_sha256:hash(await readFile(new URL('independent_storefront_experience_qa.py',import.meta.url))),browser_version:browser.version(),playwright_module:modulePath,physical_device:false,screen_reader:false,database_allocated:false,real_provider:false,checks_passed:results.filter(result=>result.result==='passed').length,checks_failed:results.filter(result=>result.result==='failed').length,results,observations,unexpected_requests:unexpected,page_errors:pageErrors};
 await writeFile(new URL('result.json',out),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({checks_passed:report.checks_passed,checks_failed:report.checks_failed,unexpected_requests:unexpected,page_errors:pageErrors,source_unchanged:report.source_unchanged}));
 if(report.checks_failed||unexpected.length||pageErrors.length||!report.source_unchanged)process.exitCode=1;
}finally{await browser.close();}
