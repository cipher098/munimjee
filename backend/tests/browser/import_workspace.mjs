/* Synthetic same-origin transport proof. Does not claim provider or DB acceptance. */
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium,expect}=await import(process.env.PLAYWRIGHT_MODULE?pathToFileURL(process.env.PLAYWRIGHT_MODULE).href:new URL('../../../frontend/storefront/node_modules/@playwright/test/index.mjs',import.meta.url).href);
const base='http://127.0.0.1:4320',output=new URL('../../../artifacts/v1/import-workspace/',import.meta.url);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{})});
const bid='11111111-1111-4111-8111-111111111111',uid='22222222-2222-4222-8222-222222222222',jid='33333333-3333-4333-8333-333333333333',cid='44444444-4444-4444-8444-444444444444',aid='55555555-5555-4555-8555-555555555555';
const root=`/api/v1/businesses/${bid}/imports`,workspace=`/v1/businesses/${bid}/imports`,prefix='munimjee.v1.import-command:',key=prefix+uid+':'+bid;
let checks=0;const errors=[];
const freshJob=()=>({contract_version:'imports.v1',job_id:jid,business_id:bid,state:'review_required',revision:2,attempts:1,candidate_count:1,error_code:null,source:{kind:'website',url:'https://example.com/products'},created_at:'2026-10-18T00:00:00Z'});
const freshCandidate=()=>({candidate_id:cid,revision:1,catalogue_bridge_status:'not_requested',candidate:{id:cid,state:'review_required',provenance:{business_id:bid,import_job_id:jid,captured_at:'2026-10-18T00:00:00Z',source:{kind:'website',url:'https://example.com/products'},source_product_id:'dress-1',evidence:'<img src=x onerror="window.injected=true"> Untrusted source'},extracted:{title:'Indigo cotton dress <script>unsafe()</script>',description:null,price:null,stock:null,options:null},overrides:[],review:null}});
async function fixture({viewer=false,empty=false}={}) {
 const context=await browser.newContext(),page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 const state={session:{auth_method:'v1_user',user_id:uid,csrf_token:'synthetic-csrf',businesses:[{id:bid,name:'Indigo Studio',capabilities:viewer?['catalogue.read']:['catalogue.read','catalogue.write']}]},jobs:empty?[]:[freshJob()],candidates:empty?[]:[freshCandidate()],posts:[],audits:new Map(),hook:null,sessionHook:null,status:200};
 const json=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data),headers:{'Cache-Control':'no-store'}});
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());if(url.origin!==base)return route.abort();
  if(url.pathname==='/api/v1/auth/session'){if(state.sessionHook)await state.sessionHook();return json(route,state.status===200?state.session:{detail:'Session ended'},state.status);}
  if(!url.pathname.startsWith(root))return route.continue();
  const path=url.pathname.slice(root.length);if(request.method()==='GET'){if(state.readHook&&await state.readHook(route,path,json))return;return json(route,path==='/jobs'?state.jobs:{items:state.candidates,next_after:null});}
  const body=path==='/uploads'?null:request.postDataJSON();const post={path,body,headers:request.headers(),raw:request.postDataBuffer(),url:request.url()};state.posts.push(post);
  if(state.hook&&await state.hook(route,post,json))return;
  const id=path==='/uploads'?url.searchParams.get('idempotency_key'):body.idempotency_key;
  if(state.audits.has(id))return json(route,state.audits.get(id));
  let result;
  if(path==='/jobs'){result={...freshJob(),state:'pending',revision:1,candidate_count:0,attempts:0,source:body.source_kind==='website'?{kind:'website',url:body.source_url}:{kind:'uploaded_media',media_id:'synthetic-sha'}};state.jobs=[result,...state.jobs.filter(j=>j.job_id!==jid)];}
  else if(path.startsWith('/jobs/')){result={...state.jobs[0],state:path.endsWith('/cancel')?'cancelled':'pending',revision:state.jobs[0].revision+1,error_code:null};state.jobs[0]=result;}
  else if(path.startsWith('/candidates/')){result=structuredClone(state.candidates[0]);if(body.expected_revision!==result.revision)return json(route,{detail:'Import revision or idempotency conflict'},409);result.revision++;if(body.action==='edit'){result.candidate.state='review_required';for(const o of body.overrides){result.candidate.overrides=result.candidate.overrides.filter(v=>v.field!==o.field);result.candidate.overrides.push({...o,reviewer_id:uid});}}else{result.candidate.state=body.action==='approve'?'approved':'rejected';result.catalogue_bridge_status=body.action==='approve'?'pending_reviewed_allocation':'not_requested';}state.candidates[0]=result;}
  else throw Error('Unexpected mutation '+path);
  state.audits.set(id,result);return json(route,result,path==='/jobs'?202:200);
 });
 for(let attempt=0;attempt<40;attempt++){try{await page.goto(base+workspace);break;}catch(error){if(attempt===39)throw error;await new Promise(resolve=>setTimeout(resolve,100));}}await page.locator('#workspace').waitFor({state:'visible'});
 return {context,page,state,json,async close(){await context.close();}};
}
async function select(page){await page.locator('.candidate-select').first().click();await expect(page.locator('#review-content')).toBeVisible();}
async function website(page){await page.locator('#website-url').fill('https://example.com/products');await page.locator('#website-consent').check();await page.getByRole('button',{name:'Start website import',exact:true}).click();}
async function saved(page){await expect(page.locator('#notice')).toContainText('confirmed');await expect(page.locator('#recovery')).toBeHidden();}
try {
 {
  const f=await fixture(),{page,state}=f;await select(page);await expect(page.locator('#approval-blockers')).toContainText('price, stock, options');await expect(page.locator('#approve')).toBeDisabled();checks+=2;
  await expect(page.locator('#candidate-evidence')).toContainText('<img');assert.equal(await page.evaluate(()=>window.injected),undefined);assert.equal(await page.locator('#candidate-evidence img').count(),0);checks+=2;
  await page.locator('#fact-price').fill('799.05');await page.locator('#fact-stock').fill('0');await page.locator('#options-mode').selectOption('specified');await page.locator('[name=option-name]').fill('Size');await page.locator('[name=option-values]').fill('Small\nMedium');await page.getByRole('button',{name:'Save factual changes',exact:true}).click();await saved(page);
  const edit=state.posts[0].body;assert.equal(edit.action,'edit');assert.deepEqual(edit.overrides,[{field:'price',value:{amount:'799.05',currency:'INR'}},{field:'stock',value:0},{field:'options',value:[{name:'Size',values:['Small','Medium']}]}]);assert.equal(edit.expected_revision,1);assert.equal(edit.confirmed_fields,undefined);checks+=4;
  for(const box of await page.locator('#confirmations input').all())await box.check();await page.getByRole('button',{name:'Approve reviewed candidate',exact:true}).click();await saved(page);await expect(page.locator('#candidate-state')).toContainText('approved');await expect(page.locator('#bridge-note')).toBeVisible();assert.deepEqual(state.posts[1].body.confirmed_fields,['title','description','price','stock','options']);assert.equal(state.posts.filter(p=>!p.path.endsWith('/review')).length,0);checks+=4;
  await page.screenshot({path:new URL('desktop-approved.png',output).pathname,fullPage:true});await page.setViewportSize({width:390,height:844});await page.screenshot({path:new URL('mobile-approved.png',output).pathname,fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++;await f.close();
 }
 {
  const f=await fixture({empty:true}),{page,state}=f;let lost=true;
  state.hook=async(route,post)=>{if(post.path==='/jobs'&&lost){lost=false;const result={...freshJob(),state:'pending'};state.jobs=[result];state.audits.set(post.body.idempotency_key,result);await route.abort('failed');return true;}return false;};
  await website(page);await expect(page.locator('#recovery-error')).not.toBeEmpty();const first=structuredClone(state.posts[0].body);assert.equal(first.source_authorized,true);assert.equal(state.posts[0].headers['x-csrf-token'],'synthetic-csrf');checks+=2;
  await page.reload();await expect(page.locator('#recovery')).toBeVisible();assert.equal(state.posts.length,1);await page.getByRole('button',{name:'Retry saved action'}).click();await saved(page);assert.deepEqual(state.posts[1].body,first);assert.equal(state.jobs.length,1);assert.equal(await page.evaluate(k=>sessionStorage.getItem(k),key),null);checks+=4;await f.close();
 }
 {
  const f=await fixture({empty:true}),{page,state}=f;let lost=true;
  const bytes=Buffer.from('89504e470d0a1a0a00000000','hex'),{createHash}=await import('node:crypto'),sha=createHash('sha256').update(bytes).digest('hex');
  state.hook=async(route,post,json)=>{if(post.path!=='/uploads')return false;if(lost){lost=false;await route.abort('failed');return true;}await json(route,{asset_id:aid,content_type:'image/png',size_bytes:bytes.length,sha256:sha},201);return true;};
  await page.locator('#upload-file').setInputFiles({name:'original.png',mimeType:'image/png',buffer:bytes});await page.locator('#upload-consent').check();await page.getByRole('button',{name:'Upload and start import'}).click();await expect(page.locator('#recovery-error')).not.toBeEmpty();const uploadUrl=state.posts[0].url;assert.deepEqual(state.posts[0].raw,bytes);assert.equal(state.posts[0].headers['content-type'],'image/png');assert.equal(state.posts[0].headers['x-csrf-token'],'synthetic-csrf');checks+=3;
  await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await page.locator('#recovery-file').setInputFiles({name:'wrong.png',mimeType:'image/png',buffer:Buffer.from('wrong')});await page.getByRole('button',{name:'Retry saved action'}).click();await expect(page.locator('#recovery-error')).toContainText('exact original');assert.equal(state.posts.length,1);checks++;
  await page.locator('#recovery-file').setInputFiles({name:'original.png',mimeType:'image/png',buffer:bytes});await page.getByRole('button',{name:'Retry saved action'}).click();await saved(page);assert.equal(state.posts[1].url,uploadUrl);assert.deepEqual(state.posts[1].raw,bytes);assert.equal(state.posts[2].body.asset_id,aid);assert.equal(state.posts[2].body.source_authorized,true);checks+=4;await f.close();
 }
 {
  const f=await fixture(),{page,state}=f;await select(page);state.hook=async(route,post,json)=>{if(post.path.endsWith('/review')){state.candidates[0].revision=2;await json(route,{detail:'Import revision conflict'},409);return true;}return false;};await page.locator('#fact-title').fill('Seller correction');await page.getByRole('button',{name:'Save factual changes',exact:true}).click();await expect(page.locator('#global-error')).toContainText('record changed');await expect(page.locator('#recovery')).toBeHidden();assert.equal(state.posts.length,1);await page.getByRole('button',{name:'Refresh',exact:true}).click();await expect(page.locator('#candidate-state')).toContainText('revision 2');checks+=3;await f.close();
 }
 {
  const f=await fixture({viewer:true}),{page,state}=f;await select(page);await expect(page.locator('#role-note')).toBeVisible();await expect(page.locator('#website-fields')).toHaveAttribute('disabled','');await expect(page.locator('#facts-fields')).toHaveAttribute('disabled','');assert.equal(state.posts.length,0);checks+=3;await f.close();
 }
 {
  const f=await fixture(),{page,state}=f;await select(page);state.session.businesses[0].capabilities=['catalogue.read'];await page.locator('#fact-title').fill('Downgraded');await page.getByRole('button',{name:'Save factual changes',exact:true}).click();await expect(page.locator('#facts-error')).toContainText('read-only');await expect(page.locator('#facts-fields')).toHaveAttribute('disabled','');assert.equal(state.posts.length,0);checks+=3;await f.close();
 }
 {
  const f=await fixture({empty:true}),{page,state}=f;state.hook=async(route,post,json)=>{state.session.user_id='66666666-6666-4666-8666-666666666666';state.session.csrf_token='other-csrf';await json(route,{...freshJob(),state:'pending'},202);return true;};await website(page);await expect(page.locator('#access-needed')).toBeVisible();await expect(page.locator('#workspace')).toBeHidden();assert.equal(await page.evaluate(k=>sessionStorage.getItem(k),key),null);assert.equal(await page.locator('#candidate-evidence').textContent(),'');checks+=3;await f.close();
 }
 {
  const f=await fixture({empty:true}),{page,state}=f;const bytes=Buffer.from('test');state.hook=async(route,post,json)=>{if(post.path==='/uploads'){await json(route,{detail:'Expired'},401);return true;}return false;};await page.locator('#upload-file').setInputFiles({name:'original.png',mimeType:'image/png',buffer:bytes});await page.locator('#upload-consent').check();await page.getByRole('button',{name:'Upload and start import'}).click();await expect(page.locator('#workspace')).toBeHidden();assert.equal(await page.evaluate(k=>sessionStorage.getItem(k),key),null);checks+=2;await f.close();
 }
 {
  const f=await fixture(),{page,state}=f;await page.evaluate(k=>sessionStorage.setItem(k,'{"invalid":true}'),key);await page.reload();await expect(page.locator('#recovery')).toBeVisible();await expect(page.locator('#retry-command')).toBeDisabled();await expect(page.locator('#website-fields')).toHaveAttribute('disabled','');assert.equal(state.posts.length,0);checks+=3;await f.close();
 }
 {
  const f=await fixture({empty:true}),{page,state}=f;state.sessionHook=()=>new Promise(r=>setTimeout(r,70));await page.locator('#website-url').fill('https://example.com/products');await page.locator('#website-consent').check();await page.evaluate(()=>{document.getElementById('website-form').requestSubmit();document.getElementById('website-form').requestSubmit();});await expect(page.locator('#notice')).toContainText('Import request confirmed');assert.equal(state.posts.length,1);checks++;await f.close();
 }
 {
  const f=await fixture({empty:true}),{page,state}=f;state.jobs=[{...freshJob(),state:'failed',attempts:3,error_code:'fetch_failed'}];await page.getByRole('button',{name:'Refresh',exact:true}).click();await expect(page.locator('#job-list')).toContainText('Retry limit reached');assert.equal(await page.getByRole('button',{name:'Retry job',exact:true}).count(),0);state.jobs[0]={...freshJob(),state:'failed',error_code:'provider_capability_pending'};await page.getByRole('button',{name:'Refresh',exact:true}).click();await expect(page.locator('#job-list')).toContainText('awaiting provider capability');checks+=3;await f.close();
 }

 {
  const f=await fixture({empty:true}),{page,state}=f;const bytes=Buffer.from('original-bytes'),{createHash}=await import('node:crypto'),sha=createHash('sha256').update(bytes).digest('hex');let lost=true;
  state.hook=async(route,post,json)=>{if(post.path==='/uploads'){await json(route,{asset_id:aid,content_type:'image/png',size_bytes:bytes.length,sha256:sha},201);return true;}if(post.path==='/jobs'&&lost){lost=false;const result={...freshJob(),state:'pending'};state.jobs=[result];state.audits.set(post.body.idempotency_key,result);await route.abort('failed');return true;}return false;};
  await page.locator('#upload-file').setInputFiles({name:'original.png',mimeType:'image/png',buffer:bytes});await page.locator('#upload-consent').check();await page.getByRole('button',{name:'Upload and start import'}).click();await expect(page.locator('#recovery-error')).not.toBeEmpty();const request=structuredClone(state.posts[1].body);await page.reload();await expect(page.locator('#recovery-file-label')).toBeHidden();await page.getByRole('button',{name:'Retry saved action'}).click();await saved(page);assert.deepEqual(state.posts[2].body,request);assert.equal(state.posts.filter(p=>p.path==='/uploads').length,1);checks+=3;await f.close();
 }
 {
  const f=await fixture(),{page,state}=f;await page.evaluate(()=>{Storage.prototype.setItem=function(){throw Error('disabled');};});await website(page);await expect(page.locator('#global-error')).toContainText('No new request was sent');assert.equal(state.posts.length,0);checks++;await f.close();
 }
 {
  const f=await fixture(),{page,state}=f;await select(page);await page.locator('#options-mode').selectOption('specified');await page.getByRole('button',{name:'Remove option'}).click();await page.getByRole('button',{name:'Save factual changes',exact:true}).click();await expect(page.locator('#facts-error')).toContainText('explicitly choose No options');assert.equal(state.posts.length,0);checks++;await f.close();
 }
 {
  const f=await fixture({empty:true}),{page,state}=f;await website(page);await saved(page);let release,started;const gate=new Promise(r=>release=r),seen=new Promise(r=>started=r);let delayed=true;
  state.readHook=async(route,path,json)=>{if(path==='/jobs'&&delayed){delayed=false;const stale=structuredClone(state.jobs);started();await gate;await json(route,stale);return true;}return false;};
  await seen;state.jobs=[{...freshJob(),state:'cancelled'}];await page.getByRole('button',{name:'Refresh',exact:true}).click();await expect(page.locator('#job-list')).toContainText('cancelled');release();await page.waitForTimeout(150);await expect(page.locator('#job-list')).toContainText('cancelled');assert.equal(await page.locator('#job-list').textContent().then(t=>t.includes('Waiting for worker')),false);checks+=2;await f.close();
 }
 assert.deepEqual(errors,[]);checks++;await writeFile(new URL('browser-results.json',output),JSON.stringify({checks,transport:'synthetic same-origin HTTP mocks',database:'not exercised by this suite',provider_calls:0,errors},null,2));console.log(`${checks} import workspace browser checks passed; synthetic transport, no provider or DB claims.`);
} finally {await browser.close();}
