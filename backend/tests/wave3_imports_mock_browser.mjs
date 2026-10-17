/* Independent DOM behavior of actual UI sources, synthetic HTTP only; no DB claim. */
import {chromium,expect} from '../../frontend/storefront/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const source=path.resolve(process.argv[2]||new URL('../..',import.meta.url).pathname);
const out=new URL('../../artifacts/v1/qa-product/import-browser-http-mock/',import.meta.url);
const files=['import_workspace.html','import_workspace.js','import_workspace.css','v1_client.js','commerce.css'];
const assets=Object.fromEntries(await Promise.all(files.map(async file=>[file,await readFile(path.join(source,'backend/static',file))])));
const sourceHead=execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
const sourceStatus=execFileSync('git',['-C',source,'status','--porcelain','--',...files.map(f=>'backend/static/'+f)],{encoding:'utf8'}).trim();
const hashes=Object.fromEntries(files.map(file=>[file,createHash('sha256').update(assets[file]).digest('hex')]));
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{})});
const base='https://qa.example.test',bid='11111111-1111-4111-8111-111111111111',uid='22222222-2222-4222-8222-222222222222',jid='33333333-3333-4333-8333-333333333333';
let checks=0;const results=[],errors=[],external=[];
function job(state='pending',revision=1){return {contract_version:'imports.v1',job_id:jid,business_id:bid,state,revision,attempts:state==='pending'?0:1,candidate_count:state==='review_required'?1:0,error_code:null,source:{kind:'website',url:'https://shop.example.com/dress'},created_at:'2026-10-18T00:00:00Z'};}
function candidate(title='Synthetic private candidate') {const id='44444444-4444-4444-8444-444444444444';return {candidate_id:id,revision:1,catalogue_bridge_status:'not_requested',candidate:{id,state:'review_required',extracted:{title,description:'Synthetic description',price:{amount:'1299',currency:'INR'},stock:null,options:null},overrides:[],review:null,provenance:{business_id:bid,import_job_id:jid,source:{kind:'website',url:'https://shop.example.com/dress'},source_product_id:'dress',captured_at:'2026-10-18T00:00:00Z',evidence:'Literal synthetic source'}}};}
async function setup({jobs=[],candidates=[],viewport={width:1440,height:1000},init}={}) {
 const c=await browser.newContext({viewport});const page=await c.newPage();page.setDefaultTimeout(5000);
 page.on('pageerror',e=>errors.push(e.message));
 const model={jobs,candidates,user:uid,csrf:'bound-synthetic-csrf',capabilities:['catalogue.read','catalogue.write'],sessionStatus:200,posts:[],sessionHook:null,jobsHook:null};
 await page.addInitScript(()=>{window.__qaStorageWrites=[];const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(key.startsWith('munimjee.v1.import-command:'))window.__qaStorageWrites.push({key,value});return original.call(this,key,value);};});
 if(init)await page.addInitScript(init);
 await c.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url()),pathname=url.pathname;
  if(url.origin!==base){external.push(url.href);return route.abort();}
  if(pathname===`/v1/businesses/${bid}/imports`)return route.fulfill({contentType:'text/html',body:assets['import_workspace.html']});
  if(pathname.startsWith('/static/')){const file=pathname.slice(8);return assets[file]?route.fulfill({contentType:file.endsWith('.js')?'application/javascript':'text/css',body:assets[file]}):route.fulfill({status:404});}
  if(pathname==='/api/v1/auth/session'){
   if(model.sessionHook)await model.sessionHook(route);
   return route.fulfill({status:model.sessionStatus,json:model.sessionStatus===200?{auth_method:'v1_user',user_id:model.user,csrf_token:model.csrf,businesses:[{id:bid,name:'Synthetic QA boutique',capabilities:model.capabilities}]}:{detail:'Session ended'}});
  }
  if(pathname.endsWith('/imports/jobs')&&request.method()==='GET'){
   if(model.jobsHook&&await model.jobsHook(route))return;
   return route.fulfill({json:model.jobs});
  }
  if(pathname.endsWith('/imports/candidates'))return route.fulfill({json:{items:model.candidates,next_after:null}});
  if(pathname.endsWith('/imports/jobs')&&request.method()==='POST'){
   const body=request.postDataJSON();model.posts.push(body);model.jobs=[job()];return route.fulfill({status:202,json:model.jobs[0]});
  }
  if(pathname.includes('/imports/'))return route.fulfill({status:409,json:{detail:'Synthetic current revision conflict'}});
  return route.fulfill({status:404});
 });
 await page.goto(base+`/v1/businesses/${bid}/imports`);await expect(page.locator('#workspace')).toBeVisible();
 return {c,page,model};
}
async function record(name,action){try{await action();checks++;results.push({name,result:'passed'});}catch(error){results.push({name,result:'failed',message:error.message});}}
try {
 await record('source consent and unknown-stock approval block are visible',async()=>{
  const {c,page,model}=await setup({candidates:[candidate()]});
  await page.getByRole('button',{name:/Synthetic private candidate/}).click();
  await expect(page.locator('#fact-stock')).toHaveValue('');await expect(page.locator('#approve')).toBeDisabled();
  await page.locator('#website-url').fill('https://shop.example.com/dress');await page.locator('#website-form').evaluate(form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  await expect(page.locator('#global-error')).toContainText('Explicit source permission');assert.equal(model.posts.length,0);
  await expect(page.getByRole('button',{name:'Retrieval unavailable',exact:true})).toBeDisabled();await c.close();
 });
 await record('rapid submits preserve one immutable request key',async()=>{
  const {c,page,model}=await setup();
  let release;const held=new Promise(resolve=>release=resolve);let waiting=0;
  model.sessionHook=async()=>{waiting++;await held;};
  await page.locator('#website-url').fill('https://shop.example.com/dress');await page.locator('#website-consent').check();
  await page.locator('#website-form').evaluate(form=>{form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));});
  await expect.poll(()=>waiting).toBeGreaterThan(0);release();model.sessionHook=null;
  await expect(page.locator('#notice')).toContainText('Import request confirmed');
  const keys=await page.evaluate(()=>window.__qaStorageWrites.map(v=>JSON.parse(v.value).body.idempotency_key));
  assert.equal(new Set(keys).size,1,`Competing durable keys allocated: ${keys.join(',')}`);assert.equal(model.posts.length,1);await c.close();
 });
 await record('a delayed old poll cannot overwrite an explicitly refreshed job',async()=>{
  const {c,page,model}=await setup({jobs:[job()]});
  let release,started;const held=new Promise(resolve=>release=resolve),seen=new Promise(resolve=>started=resolve);let first=true;
  model.jobsHook=async route=>{if(!first)return false;first=false;started();await held;await route.fulfill({json:[job()]});return true;};
  await Promise.race([seen,new Promise((_,reject)=>setTimeout(()=>reject(Error('Expected held request did not start within 8 seconds')),8000))]);model.jobs=[job('review_required',3)];
  await page.locator('#refresh').click();await expect(page.locator('#job-list')).toContainText('review required');
  const finished=page.waitForResponse(response=>response.url().includes('/imports/jobs')&&response.request().method()==='GET');release();await finished;await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await expect(page.locator('#job-list')).not.toContainText('pending ·');
  await expect(page.locator('#job-list')).toContainText('revision 3');await c.close();
 });
 await record('identity change erases private evidence, form facts and saved operations',async()=>{
  const {c,page,model}=await setup({candidates:[candidate('Private identity title')]});
  await page.getByRole('button',{name:/Private identity title/}).click();
  await page.evaluate(()=>sessionStorage.setItem('munimjee.v1.import-command:other:tenant','private-test-command'));
  model.user='55555555-5555-4555-8555-555555555555';model.csrf='new-sign-in';
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#access-needed')).toBeVisible();
  assert.equal(await page.locator('#candidate-evidence').textContent(),'');assert.equal(await page.locator('#fact-title').inputValue(),'');
  assert.equal(await page.evaluate(()=>[...Array(sessionStorage.length)].map((_,i)=>sessionStorage.key(i)).filter(k=>k.startsWith('munimjee.v1.import-command:')).length),0);await c.close();
 });
 await record('read-only role removes every mutation control and mobile layout fits',async()=>{
  const {c,page,model}=await setup({jobs:[job('failed',3)],candidates:[candidate()],viewport:{width:390,height:844}});
  model.capabilities=['catalogue.read'];await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await expect(page.locator('#role-note')).toBeVisible();await expect(page.locator('#website-fields button')).toBeDisabled();
  await expect(page.locator('#upload-fields button')).toBeDisabled();await expect(page.locator('.job-actions button').first()).toBeDisabled();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:new URL('mobile-readonly.png',out).pathname,fullPage:true});await c.close();
 });
 await record('source markup stays literal and creates no executable elements',async()=>{
  const title='<img src=x onerror="window.__injected=true">';const {c,page}=await setup({candidates:[candidate(title)]});
  await page.getByRole('button',{name:new RegExp('img src=x')}).click();await expect(page.locator('#review-heading')).toHaveText(title);
  assert.equal(await page.locator('#candidate-list img').count(),0);assert.equal(await page.evaluate(()=>window.__injected),undefined);await c.close();
 });
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 const current=await Promise.all(files.map(async file=>[file,createHash('sha256').update(await readFile(path.join(source,'backend/static',file))).digest('hex')]));
 const sourceUnchanged=JSON.stringify(Object.fromEntries(current))===JSON.stringify(hashes);
 const result={mode:'actual-ui-with-synthetic-http-no-database',source,source_head:sourceHead,source_worktree_ui_status:sourceStatus,browser_version:browser.version(),runner_sha256:createHash('sha256').update(await readFile(new URL(import.meta.url))).digest('hex'),source_hashes:hashes,source_unchanged_during_run:sourceUnchanged,checks_passed:checks,checks_failed:results.filter(r=>r.result==='failed').length,results,page_errors:errors,external_requests:external.length};
 await writeFile(new URL('result.json',out),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
 if(result.checks_failed||!sourceUnchanged)process.exitCode=1;
} finally {await browser.close();}
