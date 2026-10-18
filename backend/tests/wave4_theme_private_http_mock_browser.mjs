/* Actual private theme editor with HTTP mocks. No migration/public-provider claim. */
import {pathToFileURL} from 'node:url';
const {chromium,expect}=await import(process.env.MUNIMJEE_PLAYWRIGHT_MODULE?pathToFileURL(process.env.MUNIMJEE_PLAYWRIGHT_MODULE).href:new URL('../../frontend/storefront/node_modules/@playwright/test/index.mjs',import.meta.url).href);
import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const source=path.resolve(process.argv[2]||new URL('../..',import.meta.url).pathname),out=new URL('../../artifacts/v1/qa-product/wave4-theme-private-http-mock/',import.meta.url);
const files=['theme_settings.html','theme_settings.js','theme_settings.css','v1_client.js','commerce.css'];
const assets=Object.fromEntries(await Promise.all(files.map(async f=>[f,await readFile(path.join(source,'backend/static',f))])));
const sourceHead=execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
const sourceStatus=execFileSync('git',['-C',source,'status','--porcelain','--',...files.map(f=>'backend/static/'+f)],{encoding:'utf8'}).trim();
const hashes=Object.fromEntries(files.map(f=>[f,createHash('sha256').update(assets[f]).digest('hex')]));
await mkdir(out,{recursive:true});const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{})});
const base='https://qa.example.test',bid='11111111-1111-4111-8111-111111111111',uid='22222222-2222-4222-8222-222222222222',endpoint=`/api/v1/businesses/${bid}/theme-settings`;
const config=()=>({theme:'catalogue',palette:'forest',brand_tagline:'',hero_eyebrow:'',hero_headline:'Private saved headline',hero_intro:'',collection_heading:'',story_heading:'',story_body:'',show_story:true,show_categories:true});
const record=()=>({version:0,draft:config(),published:null,published_revision:0,published_at:null});
let checks=0;const results=[],errors=[],external=[];
async function setup({readonly=false,viewport={width:1440,height:1000},init}={}){
 const c=await browser.newContext({viewport}),page=await c.newPage();page.setDefaultTimeout(5000);page.on('pageerror',e=>errors.push(e.message));
 const model={record:record(),user:uid,csrf:'synthetic-csrf',status:200,gets:0,posts:[],receipts:new Map(),sessionHook:null,getHook:null,abortFirst:false,capabilities:readonly?['catalogue.read']:['catalogue.read','business.write']};
 if(init)await page.addInitScript(init);
 await page.addInitScript(()=>{window.__qaStorageWrites=[];const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(key.startsWith('munimjee.v1.theme-command:'))window.__qaStorageWrites.push({key,value});return original.call(this,key,value);};});
 await c.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  if(url.origin!==base){external.push(url.href);return route.abort();}
  if(p===`/v1/businesses/${bid}/themes`)return route.fulfill({contentType:'text/html',body:assets['theme_settings.html']});
  if(p.startsWith('/static/')){const file=p.slice(8);return assets[file]?route.fulfill({contentType:file.endsWith('.js')?'application/javascript':'text/css',body:assets[file]}):route.fulfill({status:404});}
  if(p==='/api/v1/auth/session'){
   if(model.sessionHook)await model.sessionHook();return route.fulfill({status:model.status,json:model.status===200?{auth_method:'v1_user',user_id:model.user,csrf_token:model.csrf,businesses:[{id:bid,name:'Synthetic design boutique',capabilities:model.capabilities}]}:{detail:'Session ended'}});
  }
  if(p===endpoint+'/preview')return route.fulfill({contentType:'text/html',body:'<!doctype html><p>Synthetic illustrative preview transport only.</p>'});
  if(p===endpoint&&req.method()==='GET'){
   model.gets++;if(model.getHook&&await model.getHook(route))return;return route.fulfill({json:model.record});
  }
  if((p===endpoint&&req.method()==='PUT')||(p===endpoint+'/publish'&&req.method()==='POST')){
   const operation=p.endsWith('/publish')?'publish':'save',body=req.postDataJSON();model.posts.push({operation,body});
   let result=model.receipts.get(body.idempotency_key);
   if(!result){
    if(body.expected_version!==model.record.version)return route.fulfill({status:409,json:{detail:{code:'theme_version_stale',message:'Synthetic stale design version'}}});
    if(operation==='save')model.record.draft=body.config;
    else {model.record.published=structuredClone(model.record.draft);model.record.published_revision=model.record.version+1;model.record.published_at='2026-10-18T00:00:00Z';}
    model.record.version++;result=structuredClone(model.record);model.receipts.set(body.idempotency_key,result);
   }
   if(model.abortFirst){model.abortFirst=false;return route.abort('failed');}
   return route.fulfill({json:result});
  }
  return route.fulfill({status:404});
 });
 await page.goto(base+`/v1/businesses/${bid}/themes`);await expect(page.locator('#workspace')).toBeVisible();return {c,page,model};
}
async function check(name,action){try{await action();checks++;results.push({name,result:'passed'});}catch(error){results.push({name,result:'failed',message:error.message});}}
try{
 await check('viewer can read and explicitly reload saved design at mobile width',async()=>{
  const {c,page,model}=await setup({readonly:true,viewport:{width:390,height:844}});await expect(page.locator('#role-note')).toBeVisible();await expect(page.locator('#save')).toBeDisabled();await expect(page.locator('#publish')).toBeDisabled();
  model.record.version=1;model.record.draft.hero_headline='New saved readonly headline';await page.locator('#reload').click();await expect(page.locator('[name=hero_headline]')).toHaveValue('New saved readonly headline');assert.equal(model.posts.length,0);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:new URL('mobile-viewer-reload.png',out).pathname,fullPage:true});await c.close();
 });
 await check('delayed old-session load cannot repopulate a terminal auth fence',async()=>{
  const {c,page,model}=await setup();let started,release;const seen=new Promise(r=>started=r),held=new Promise(r=>release=r);
  model.getHook=async route=>{started();await held;await route.fulfill({json:{...record(),draft:{...config(),hero_headline:'Stale secret headline'}}});return true;};
  await page.locator('#reload').click();await Promise.race([seen,new Promise((_,reject)=>setTimeout(()=>reject(Error('Expected held request did not start within 8 seconds')),8000))]);model.status=401;await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#access-needed')).toBeVisible();
  const finished=page.waitForResponse(r=>r.url()===base+endpoint);release();await finished;await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('[name=hero_headline]')).toHaveValue('');await expect(page.locator('#preview')).toHaveAttribute('src','about:blank');assert.equal(await page.locator('#notice').textContent(),'');assert.equal(await page.locator('#business-name').textContent(),'');await c.close();
 });
 await check('lost draft response reload replays exact key and publishes only explicitly',async()=>{
  const {c,page,model}=await setup();model.abortFirst=true;await page.locator('[name=hero_headline]').fill('Reviewed new draft');await page.locator('#save').click();await expect(page.locator('#recovery')).toBeVisible();await expect(page.locator('#error')).not.toHaveText('');
  assert.equal(model.posts.length,1);assert.equal(model.record.published,null);await page.reload();await expect(page.locator('#recovery')).toBeVisible();assert.equal(model.posts.length,1);
  await page.locator('#retry').click();await expect(page.locator('#notice')).toContainText('Draft saved');assert.equal(model.posts.length,2);assert.deepEqual(model.posts[0],model.posts[1]);assert.equal(model.record.published,null);
  await expect(page.locator('#recovery')).toBeHidden();await page.locator('#publish').click();await expect(page.locator('#notice')).toContainText('Saved design published');assert.equal(model.posts.length,3);assert.equal(model.posts[2].operation,'publish');assert.equal(model.record.published.hero_headline,'Reviewed new draft');await c.close();
 });
 await check('rapid draft submit preserves one immutable command',async()=>{
  const {c,page,model}=await setup();let release;const held=new Promise(r=>release=r);let calls=0;model.sessionHook=async()=>{calls++;await held;};
  await page.locator('[name=hero_headline]').fill('Rapid save');await page.locator('#design-form').evaluate(form=>{form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));});
  await expect.poll(()=>calls).toBeGreaterThan(0);release();model.sessionHook=null;await expect(page.locator('#notice')).toContainText('Draft saved');assert.equal(model.posts.length,1);assert.equal(new Set(await page.evaluate(()=>window.__qaStorageWrites.map(v=>JSON.parse(v.value).body.idempotency_key))).size,1);await c.close();
 });
 await check('unavailable browser storage prevents a new draft mutation',async()=>{
  const {c,page,model}=await setup({init:()=>{Storage.prototype.setItem=function(){throw new Error('synthetic storage unavailable');};}});await page.locator('[name=hero_headline]').fill('Unsaved');await page.locator('#save').click();await expect(page.locator('#error')).toContainText('No new action was sent');assert.equal(model.posts.length,0);await c.close();
 });
 await check('window focus identity change removes all theme command scopes and private preview',async()=>{
  const {c,page,model}=await setup();await page.evaluate(()=>sessionStorage.setItem('munimjee.v1.theme-command:another:tenant','private synthetic command'));model.user='55555555-5555-4555-8555-555555555555';model.csrf='different-session';await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#workspace')).toBeHidden();
  assert.equal(await page.evaluate(()=>[...Array(sessionStorage.length)].map((_,i)=>sessionStorage.key(i)).filter(k=>k.startsWith('munimjee.v1.theme-command:')).length),0);await expect(page.locator('#preview')).toHaveAttribute('src','about:blank');await c.close();
 });
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 const current=Object.fromEntries(await Promise.all(files.map(async f=>[f,createHash('sha256').update(await readFile(path.join(source,'backend/static',f))).digest('hex')])));
 const result={mode:'actual-theme-ui-with-synthetic-http-no-database-or-public-provider',source,source_head:sourceHead,source_worktree_ui_status:sourceStatus,browser_version:browser.version(),runner_sha256:createHash('sha256').update(await readFile(new URL(import.meta.url))).digest('hex'),source_hashes:hashes,source_unchanged_during_run:JSON.stringify(current)===JSON.stringify(hashes),checks_passed:checks,checks_failed:results.filter(r=>r.result==='failed').length,results,page_errors:errors,external_requests:external.length};
 await writeFile(new URL('result.json',out),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));if(result.checks_failed||!result.source_unchanged_during_run)process.exitCode=1;
}finally{await browser.close();}
