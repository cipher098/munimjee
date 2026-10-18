/* Supplemental actual-native-source checks. In-process synthetic HTTP only.
 * No listener, real session, DB, provider, shared profile, or runtime writes. */
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=path.resolve(fileURLToPath(new URL('../..',import.meta.url)));
const out=path.join(root,'artifacts/v1/native-onboarding-repair-qa');
const modulePath=process.argv[2]||'/Users/user/Documents/ChatGPT/munimjee-wave3-qa/frontend/storefront/node_modules/@playwright/test/index.mjs';
const executable=process.argv[3]||'/Users/user/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell';
const {chromium,expect}=await import(pathToFileURL(modulePath).href);
const base='http://127.0.0.1:47991', hash=value=>createHash('sha256').update(value).digest('hex');
const files=['v1_app.html','v1_app.js','v1_app.css','v1_client.js','commerce.css'];
const assets=Object.fromEntries(await Promise.all(files.map(async name=>[name,await readFile(path.join(root,'backend/static',name))])));
const before=Object.fromEntries(files.map(name=>[name,hash(assets[name])]));
const fixtures=JSON.parse(await readFile(path.join(out,'fixtures.json'),'utf8'));
assert.ok(Object.keys(fixtures.source_sha256||{}).length>0);
for(const [name,expected] of Object.entries(fixtures.source_sha256)){
  assert.match(name,/^backend\/(?:app|tests)\/[A-Za-z0-9_/.]+\.py$/);assert.ok(!name.split('/').includes('..'));
  assert.equal(hash(await readFile(path.join(root,name))),expected,'Stale fixture: '+name);
}
const sourceHead=execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
const contexts=new Set(),network=[],pageErrors=[],results=[],clone=value=>structuredClone(value);
const browser=await chromium.launch({headless:true,executablePath:executable,args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--no-default-browser-check']});
await mkdir(out,{recursive:true});
function gate(){let release,start;return {held:new Promise(resolve=>release=resolve),seen:new Promise(resolve=>start=resolve),release:()=>release(),start:()=>start()};}
async function bounded(promise){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>timer=setTimeout(()=>reject(Error('Synthetic gate timeout')),8000))]);}finally{clearTimeout(timer);}}
async function settle(page){await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}
async function ready(page){await expect(page.locator('#business-content')).toBeVisible();await expect(page.locator('#loading')).toBeHidden();}
async function setup({signedIn=true,initialFailure=null,width=390}={}){
  const context=await browser.newContext({viewport:{width,height:920},serviceWorkers:'block'});contexts.add(context);
  const page=await context.newPage();page.setDefaultTimeout(3000);page.on('pageerror',e=>pageErrors.push(e.message));
  const model={session:clone(fixtures.roles.owner.session),records:clone(fixtures.roles.owner.records),signedIn,sessionGets:0,requests:[],onboardingHook:null,logoutHook:null,authGeneration:0};
  const cookie=async()=>context.addCookies([{name:'v1_csrf',value:model.session.csrf_token,url:base,sameSite:'Lax'}]);
  if(signedIn)await cookie();
  await page.addInitScript(()=>{window.__qaFocus=[];document.addEventListener('focusin',event=>window.__qaFocus.push({id:event.target.id,tag:event.target.tagName,workspace:!!document.getElementById('workspace')?.contains(event.target),at:performance.now()}));});
  if(context.routeWebSocket)await context.routeWebSocket('**/*',socket=>{network.push({kind:'unexpected-websocket'});socket.close();});
  await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname,method=request.method();
    if(url.origin!==base){network.push({kind:'unexpected-origin',origin:url.origin});return route.abort('blockedbyclient');}
    if(p==='/v1'&&method==='GET')return route.fulfill({contentType:'text/html',body:assets['v1_app.html']});
    if(p==='/favicon.ico')return route.fulfill({status:204});
    if(p.startsWith('/static/')&&Object.hasOwn(assets,p.slice(8)))return route.fulfill({contentType:p.endsWith('.js')?'application/javascript':'text/css',body:assets[p.slice(8)]});
    model.requests.push({method,path:p});
    if(p==='/api/v1/auth/session'&&method==='GET'){
      model.sessionGets++;
      if(model.sessionGets===1&&initialFailure){if(initialFailure==='transport')return route.abort('failed');return route.fulfill({status:503,json:{detail:'Synthetic startup unavailable'}});}
      return route.fulfill({status:model.signedIn?200:401,json:model.signedIn?model.session:{detail:'Synthetic session ended'}});
    }
    if(['/api/v1/auth/login','/api/v1/auth/signup'].includes(p)&&method==='POST'){
      model.authGeneration++;model.signedIn=true;await cookie();return route.fulfill({status:p.endsWith('signup')?201:200,json:model.session});
    }
    if(p==='/api/v1/auth/logout'&&method==='POST'){
      const generation=model.authGeneration;
      if(model.logoutHook&&await model.logoutHook(route))return;
      // Explicit synthetic response semantics: a superseded old command cannot
      // mutate this fixture's newer identity/cookie. No real server claim.
      if(generation===model.authGeneration){model.signedIn=false;await context.clearCookies();}
      return route.fulfill({json:{signed_out:true}});
    }
    const match=p.match(/^\/api\/v1\/businesses\/([^/]+)\/(onboarding|invitations)$/);
    if(match&&method==='GET'){
      if(match[2]==='invitations')return route.fulfill({json:[]});
      if(model.onboardingHook&&await model.onboardingHook(route,match[1]))return;
      assert.ok(model.records[match[1]],'Unknown synthetic tenant');return route.fulfill({json:model.records[match[1]]});
    }
    network.push({kind:'unexpected-route',path:p,method});return route.abort('blockedbyclient');
  });
  await page.goto(base+'/v1');return {page,context,model};
}
async function login(page){
  await page.locator('#access-form [name=email]').fill('qa@example.com');await page.locator('#access-form [name=password]').fill('synthetic-password');
  if(await page.locator('#business-name-label').isVisible())await page.locator('#access-form [name=business_name]').fill('Synthetic QA Atelier');
  await page.locator('#access-submit').focus();await page.keyboard.press('Enter');
}
async function scenario(id,run){
  const opened=new Set(contexts);try{results.push({id,result:'passed',observed:await run()});}
  catch(error){const page=[...contexts].filter(c=>!opened.has(c)).at(-1)?.pages()[0];let screenshot=null;if(page){screenshot=id+'.png';await page.screenshot({path:path.join(out,screenshot),fullPage:true}).catch(()=>screenshot=null);}results.push({id,result:'failed',message:error.message,screenshot});}
  finally{for(const context of [...contexts])if(!opened.has(context)){await context.close();contexts.delete(context);}}
}
try{
  for(const failure of ['503','transport'])for(const valid of [true,false])await scenario(`manual-retry-${failure}-${valid?'valid':'denied'}`,async()=>{
    const {page,model}=await setup({initialFailure:failure});await expect(page.locator('#loading')).toBeHidden();await expect(page.locator('#global-error')).not.toBeEmpty();await expect(page.locator('#workspace')).toBeHidden();
    const retry=page.getByRole('button',{name:/retry|try again/i});await expect(retry).toBeVisible();await expect(retry).toBeEnabled();
    assert.equal(model.sessionGets,1,'No automatic retry before explicit action');model.signedIn=valid;
    await retry.focus();await page.keyboard.press('Enter');await expect.poll(()=>model.sessionGets).toBeGreaterThan(1);
    if(valid){await ready(page);await expect(page.locator('#profile-form [name=name]')).toHaveValue('Synthetic QA Atelier');}
    else{await expect(page.locator('#access')).toBeVisible();await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#profile-form [name=name]')).toHaveValue('');assert.equal(model.requests.filter(r=>r.path.endsWith('/onboarding')).length,0);}
    assert.equal(model.requests.filter(r=>r.method==='POST').length,0,'Retry must only re-read current session');
    await page.screenshot({path:path.join(out,`manual-retry-${failure}-${valid?'valid':'denied'}.png`),fullPage:true});return {fresh_session_gets:model.sessionGets,valid,requests:model.requests};
  });
  await scenario('deferred-signin-logout-focus',async()=>{
    const {page,model}=await setup({signedIn:false});await expect(page.locator('#access')).toBeVisible();const held=gate();
    model.onboardingHook=async()=>{held.start();await held.held;return false;};await login(page);await bounded(held.seen);
    await page.locator('#logout').focus();await page.keyboard.press('Enter');await expect(page.locator('#access')).toBeVisible();
    const cutoff=await page.evaluate(()=>performance.now());held.release();await settle(page);await expect(page.locator('#workspace')).toBeHidden();
    assert.equal(await page.evaluate(()=>document.getElementById('access').contains(document.activeElement)),true);
    assert.deepEqual(await page.evaluate(at=>window.__qaFocus.filter(e=>e.at>at&&e.workspace),cutoff),[],'Late sign-in completion focused obsolete workspace');
    return {focus:await page.evaluate(()=>({id:document.activeElement.id,tag:document.activeElement.tagName})),cutoff};
  });
  await scenario('deferred-logout-new-signin-focus',async()=>{
    const {page,model}=await setup();await ready(page);const held=gate();model.logoutHook=async()=>{held.start();await held.held;return false;};
    await page.locator('#logout').click();await bounded(held.seen);model.signedIn=false;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#access')).toBeVisible();
    model.session.user_id='20000000-0000-4000-8000-000000000082';model.session.csrf_token='synthetic-new-identity-never-real';
    await login(page);await ready(page);await page.locator('#profile-form [name=name]').focus();const cutoff=await page.evaluate(()=>performance.now());
    held.release();await settle(page);await expect(page.locator('#workspace')).toBeVisible();await expect(page.locator('#profile-form [name=name]')).toBeFocused();
    assert.deepEqual(await page.evaluate(at=>window.__qaFocus.filter(e=>e.at>at&&e.id!=='').map(e=>e.id),cutoff),[],'Late old logout stole current focus');
    return {current_user:model.session.user_id,focus:await page.evaluate(()=>document.activeElement.name),requests:model.requests};
  });
  await scenario('passive-refresh-no-focus-steal',async()=>{
    const {page,model}=await setup();await ready(page);const input=page.locator('#profile-form [name=name]');await input.focus();const reads=model.sessionGets;
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect.poll(()=>model.sessionGets).toBeGreaterThan(reads);await expect(page.locator('#workspace')).toBeVisible();
    await expect(input).toBeFocused();return {reads_before:reads,reads_after:model.sessionGets,focus:await input.evaluate(e=>({name:e.name,id:e.id}))};
  });
  // Pass-state recapture of keyboard focus and the original long-name invariant.
  await scenario('focused-long-name-captures',async()=>{
    const {page,model}=await setup({signedIn:false,width:360});await expect(page.locator('#access')).toBeVisible();
    model.session.businesses[0].name='A'.repeat(160);model.records[model.session.businesses[0].id].profile.name='A'.repeat(160);
    await login(page);await ready(page);await settle(page);assert.equal(await page.evaluate(()=>document.getElementById('workspace').contains(document.activeElement)),true);
    const size=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(size.scroll<=size.viewport);
    await page.screenshot({path:path.join(out,'focused-long-business-name-360.png'),fullPage:true});return {size,focus:await page.evaluate(()=>({id:document.activeElement.id,outline:getComputedStyle(document.activeElement).outlineColor}))};
  });
  const after=Object.fromEntries(await Promise.all(files.map(async name=>[name,hash(await readFile(path.join(root,'backend/static',name)))])));
  const result={mode:'actual-native-source-intercepted-synthetic-http-supplement',source_head:sourceHead,source_hashes_before:before,source_hashes_after:after,source_unchanged:JSON.stringify(before)===JSON.stringify(after),runner_sha256:hash(await readFile(fileURLToPath(import.meta.url))),fixture_sha256:hash(await readFile(path.join(out,'fixtures.json'))),fixture_sources_verified_before_browser:true,server_started:false,unexpected_network:network,page_errors:pageErrors,passed:results.filter(r=>r.result==='passed').length,failed:results.filter(r=>r.result==='failed').length,results,unrun_gates:['actual server/session/cookie race behavior','mounted migrated DB','physical touch','screen-reader interaction','full WCAG audit','provider behavior']};
  await writeFile(path.join(out,'supplement-result.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({passed:result.passed,failed:result.failed,failures:results.filter(r=>r.result==='failed'),unexpected_network:network,page_errors:pageErrors},null,2));
  if(result.failed||network.length||pageErrors.length||!result.source_unchanged)process.exitCode=1;
}finally{for(const context of contexts)await context.close();await browser.close();}
