/* Unchanged native onboarding UI + actual formatter DTOs + synthetic HTTP.
 * Every page request is fulfilled or denied in-process. No server is contacted. */
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=path.resolve(fileURLToPath(new URL('../..',import.meta.url)));
const out=path.join(root,'artifacts/v1/independent-onboarding-experience');
const modulePath=process.argv[2]||'/Users/user/Documents/ChatGPT/munimjee-wave3-qa/frontend/storefront/node_modules/@playwright/test/index.mjs';
const executable=process.argv[3]||'/Users/user/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell';
const {chromium,expect}=await import(pathToFileURL(modulePath).href);
const base='http://127.0.0.1:47991'; // Intercept-only origin: no listener or ambient service.
const files=['v1_app.html','v1_app.js','v1_app.css','v1_client.js','commerce.css'];
const assets=Object.fromEntries(await Promise.all(files.map(async file=>[file,await readFile(path.join(root,'backend/static',file))])));
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const before=Object.fromEntries(files.map(file=>[file,hash(assets[file])]));
const sourceHead=execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
const fixtures=JSON.parse(await readFile(path.join(out,'fixtures.json'),'utf8'));
assert.ok(Object.keys(fixtures.source_sha256||{}).length>0,'Fixture source hashes are required');
for(const [file,expected] of Object.entries(fixtures.source_sha256)){
  assert.match(file,/^backend\/(?:app|tests)\/[A-Za-z0-9_/.]+\.py$/,'Unexpected fixture source path');
  assert.ok(!file.split('/').includes('..'),'Fixture source path must stay inside the checkout');
  assert.equal(hash(await readFile(path.join(root,file))),expected,`Stale formatter/capability fixture source: ${file}; regenerate fixtures before browser launch`);
}
const [A,B]=fixtures.roles.owner.session.businesses.map(b=>b.id);
const clone=value=>structuredClone(value), results=[],contexts=new Set(),network=[],pageErrors=[];
const browser=await chromium.launch({headless:true,executablePath:executable,args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--no-default-browser-check']});
await mkdir(out,{recursive:true});

async function setup({role='owner',signedIn=true,width=390,query='',initialHook=null,init=null}={}){
  const context=await browser.newContext({viewport:{width,height:920},serviceWorkers:'block'});
  contexts.add(context); const page=await context.newPage();page.setDefaultTimeout(2000);
  page.on('pageerror',error=>pageErrors.push(error.message));
  const model={session:clone(fixtures.roles[role].session),records:clone(fixtures.roles[role].records),signedIn,
    sessionStatus:200,sessionGets:0,requests:[],invites:[],sessionHook:initialHook,onboardingHook:null,profileHook:null,deleteHook:null};
  if(init)await page.addInitScript(init);
  if(context.routeWebSocket)await context.routeWebSocket('**/*',socket=>{network.push({kind:'unexpected-websocket'});socket.close();});
  await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname,method=request.method();
    if(url.origin!==base){network.push({kind:'unexpected-origin',origin:url.origin});return route.abort('blockedbyclient');}
    if(p==='/v1'&&method==='GET')return route.fulfill({contentType:'text/html',body:assets['v1_app.html']});
    if(p==='/favicon.ico')return route.fulfill({status:204});
    if(p.startsWith('/static/')&&assets[p.slice(8)])return route.fulfill({contentType:p.endsWith('.js')?'application/javascript':'text/css',body:assets[p.slice(8)]});
    if(!p.startsWith('/api/v1/')){network.push({kind:'unexpected-path',path:p});return route.abort('blockedbyclient');}
    model.requests.push({path:p,method,csrf:request.headers()['x-csrf-token']||null,body:request.postDataJSON()});
    if(p==='/api/v1/auth/session'&&method==='GET'){
      model.sessionGets++;if(model.sessionHook&&await model.sessionHook(route,model))return;
      return route.fulfill({status:!model.signedIn?401:model.sessionStatus,json:!model.signedIn||model.sessionStatus!==200?{detail:'Synthetic session unavailable'}:model.session});
    }
    if(['/api/v1/auth/login','/api/v1/auth/signup','/api/v1/auth/invitations/accept'].includes(p)&&method==='POST'){
      model.signedIn=true;return route.fulfill({status:p.endsWith('signup')?201:200,json:model.session});
    }
    if(['/api/v1/auth/logout','/api/v1/auth/logout-all'].includes(p)&&method==='POST'){
      model.signedIn=false;return route.fulfill({json:{signed_out:true}});
    }
    const match=p.match(/^\/api\/v1\/businesses\/([^/]+)\/(onboarding|profile|invitations)(?:\/([^/]+))?$/);
    if(match){
      const [,bid,kind,resource]=match,record=model.records[bid];
      if(!record)return route.fulfill({status:404,json:{detail:'Synthetic inaccessible business'}});
      if(kind==='onboarding'&&method==='GET'){
        if(model.onboardingHook&&await model.onboardingHook(route,bid))return;
        return route.fulfill({json:record});
      }
      if(kind==='profile'&&method==='PUT'){
        const body=request.postDataJSON();if(model.profileHook&&await model.profileHook(route,body,bid))return;
        if(body.expected_version!==record.profile.version)return route.fulfill({status:409,json:{detail:'Business details changed; refresh before saving'}});
        record.profile.name=body.name;record.profile.version++;record.profile.confirmed=true;
        for(const key of ['support_email','phone','website'])record.profile.profile[key]=body[key];
        model.session.businesses.find(b=>b.id===bid).name=body.name;
        return route.fulfill({json:record.profile});
      }
      if(kind==='invitations'&&method==='GET')return route.fulfill({json:model.invites.filter(row=>row.bid===bid).map(({bid,...row})=>row)});
      if(kind==='invitations'&&method==='POST'){
        const row={id:'70000000-0000-4000-8000-'+String(model.invites.length+1).padStart(12,'0'),...request.postDataJSON(),expires_at:'2030-10-18T00:00:00Z',consumed:false,revoked:false,bid};
        model.invites.push(row);const {bid:unused,...publicRow}=row;
        return route.fulfill({status:201,json:{...publicRow,invitation_url:'/v1#invite='+'synthetic-invitation-'.repeat(3)}});
      }
      if(kind==='invitations'&&method==='DELETE'){
        if(model.deleteHook&&await model.deleteHook(route,bid,resource))return;
        const row=model.invites.find(row=>row.id===resource);if(!row)return route.fulfill({status:404,json:{detail:'Invitation not found'}});
        row.revoked=true;const {bid:unused,...publicRow}=row;return route.fulfill({json:publicRow});
      }
    }
    network.push({kind:'unexpected-api',path:p,method});return route.abort('blockedbyclient');
  });
  await page.goto(base+'/v1'+query);return {context,page,model};
}

async function ready(page){await expect(page.locator('#business-content')).toBeVisible();await expect(page.locator('#loading')).toBeHidden();}
async function settle(page){await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}
async function bounded(promise){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>timer=setTimeout(()=>reject(Error('Synthetic request gate did not start within 8 seconds')),8000))]);}finally{clearTimeout(timer);}}
function gate(){let release,started;return {held:new Promise(r=>release=r),seen:new Promise(r=>started=r),release:()=>release(),start:()=>started()};}
async function createInvite(page){await page.locator('#invite-form [name=email]').fill('synthetic-invitee@example.com');await page.locator('#invite-form button').click();await expect(page.locator('#invite-result')).toBeVisible();}
async function scenario(id,name,run,{severity='P2',source='backend/static/v1_app.js'}={}){
  const opened=new Set(contexts);let observed=null;
  try{observed=await run();results.push({id,name,result:'passed',observed});}
  catch(error){
    const active=[...contexts].filter(c=>!opened.has(c));let screenshot=null,state=null;
    if(active.length){const page=active.at(-1).pages()[0];state=await page.evaluate(()=>{
      const visible=id=>Boolean(document.getElementById(id)?.getClientRects().length);
      return {workspace_visible:visible('workspace'),business_content_visible:visible('business-content'),
        profile_control_visible:document.querySelector('#profile-form [name=name]').getClientRects().length>0,
        profile_value_in_DOM:document.querySelector('#profile-form [name=name]').value,
        profile_error_visible:visible('profile-error'),profile_error:document.getElementById('profile-error').textContent,
        invitation_link_visible:visible('invite-link'),invitation_link_has_value:Boolean(document.getElementById('invite-link').value)};
    }).catch(()=>null);screenshot=id+'.png';await page.screenshot({path:path.join(out,screenshot),fullPage:true}).catch(()=>{screenshot=null;});}
    results.push({id,name,result:'failed',severity,source,message:error.message.slice(0,2200),screenshot,state});
  }finally{for(const context of [...contexts])if(!opened.has(context)){await context.close();contexts.delete(context);}}
}
async function noOverflow(page){const sizes=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:innerWidth}));assert.ok(sizes.scroll<=sizes.viewport,JSON.stringify(sizes));return sizes;}
function luminance(rgb){const values=rgb.match(/[\d.]+/g).slice(0,3).map(n=>{const v=Number(n)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return .2126*values[0]+.7152*values[1]+.0722*values[2];}
function contrast(a,b){const [light,dark]=[luminance(a),luminance(b)].sort((a,b)=>b-a);return (light+.05)/(dark+.05);}

try{
  for(const width of [360,390,768,1440]){
    await scenario('layout-access-'+width,`signup layout and associated labels at ${width}px`,async()=>{
      const {page}=await setup({signedIn:false,width});await expect(page.locator('#access')).toBeVisible();
      for(const name of ['business_name','email','password'])assert.ok(await page.locator(`#access-form [name=${name}]`).evaluate(input=>input.labels.length>0));
      assert.equal(await page.locator('html').getAttribute('lang'),'en');
      const size=await noOverflow(page);if(width<=390)assert.ok(await page.locator('#access-form [name=email]').evaluate(input=>parseFloat(getComputedStyle(input).fontSize)>=16));
      await page.screenshot({path:path.join(out,'signup-'+width+'.png'),fullPage:true});return size;
    },{source:'backend/static/v1_app.css'});
    await scenario('layout-owner-'+width,`owner checklist/profile/invitation layout at ${width}px`,async()=>{
      const {page}=await setup({width});await ready(page);await createInvite(page);
      const size=await noOverflow(page);for(const element of await page.locator('#profile-form input,#profile-form select,#invite-form input,#invite-form select').all())assert.ok(await element.evaluate(input=>input.labels.length>0));
      await page.screenshot({path:path.join(out,'owner-'+width+'.png'),fullPage:true});return size;
    },{source:'backend/static/v1_app.css'});
  }
  await scenario('keyboard-access','keyboard order, skip link and native validation block invalid email',async()=>{
    const {page,model}=await setup({signedIn:false});await expect(page.locator('#access')).toBeVisible();
    await page.keyboard.press('Tab');await expect(page.locator('.skip-link')).toBeFocused();
    assert.ok((await page.locator('.skip-link').boundingBox()).y>=0);await page.keyboard.press('Enter');
    assert.equal(new URL(page.url()).hash,'#main');
    await page.locator('#access-form [name=business_name]').focus();await page.keyboard.press('Tab');await expect(page.locator('#access-form [name=email]')).toBeFocused();
    await page.locator('#access-form [name=business_name]').fill('Valid Atelier');await page.locator('#access-form [name=email]').fill('bad-email');await page.locator('#access-form [name=password]').fill('synthetic-password');
    await page.locator('#access-submit').click();assert.equal(model.requests.filter(r=>r.method==='POST').length,0);
    assert.equal(await page.locator('#access-form [name=email]').evaluate(input=>input.validity.typeMismatch),true);
  });
  await scenario('keyboard-transition','keyboard submit moves focus into newly opened workspace',async()=>{
    const {page}=await setup({signedIn:false});await expect(page.locator('#access')).toBeVisible();
    await page.locator('#access-form [name=business_name]').fill('Synthetic QA Atelier');await page.locator('#access-form [name=email]').fill('qa@example.com');await page.locator('#access-form [name=password]').fill('synthetic-password');
    await page.locator('#access-submit').focus();await page.keyboard.press('Enter');await ready(page);
    const focus=await page.evaluate(()=>({tag:document.activeElement.tagName,id:document.activeElement.id,inside:document.getElementById('workspace').contains(document.activeElement)}));
    assert.ok(focus.inside,'Focus did not enter new workspace: '+JSON.stringify(focus));return focus;
  });
  await scenario('contrast-control','primary button meets chosen 4.5:1 text contrast criterion',async()=>{
    const {page}=await setup({signedIn:false});await expect(page.locator('#access')).toBeVisible();
    const colors=await page.locator('#access-submit').evaluate(button=>({fg:getComputedStyle(button).color,bg:getComputedStyle(button).backgroundColor}));
    const ratio=contrast(colors.fg,colors.bg);assert.ok(ratio>=4.5,JSON.stringify({colors,ratio}));return {colors,ratio};
  },{source:'backend/static/commerce.css'});
  await scenario('contrast-focus','keyboard focus outline meets chosen 3:1 adjacent-background criterion',async()=>{
    const {page}=await setup({signedIn:false});await expect(page.locator('#access')).toBeVisible();await page.locator('#access-form [name=email]').focus();await page.keyboard.press('Tab');
    const colors=await page.locator('#access-form [name=password]').evaluate(input=>({outline:getComputedStyle(input).outlineColor,width:getComputedStyle(input).outlineWidth,style:getComputedStyle(input).outlineStyle,focus_visible:input.matches(':focus-visible'),background:getComputedStyle(input.closest('.panel')).backgroundColor}));
    const ratio=contrast(colors.outline,colors.background);assert.ok(colors.focus_visible&&colors.style==='solid'&&parseFloat(colors.width)>=2&&ratio>=3,JSON.stringify({colors,ratio,keyboard_tab:true}));return {colors,ratio};
  },{source:'backend/static/commerce.css'});
  await scenario('loading-session','initial held session shows announced loading and no private workspace',async()=>{
    const held=gate();const {page}=await setup({initialHook:async()=>{held.start();await held.held;return false;}});
    await bounded(held.seen);await expect(page.locator('#loading')).toBeVisible();assert.equal(await page.locator('#loading').getAttribute('role'),'status');await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#access')).toBeHidden();held.release();await ready(page);
  });
  await scenario('startup-error','startup 503 offers an actionable retry or sign-in path',async()=>{
    const {page}=await setup({initialHook:async route=>{await route.fulfill({status:503,json:{detail:'Synthetic maintenance; try again'}});return true;}});
    await expect(page.locator('#loading')).toBeHidden();await expect(page.locator('#global-error')).toContainText('Synthetic maintenance');
    assert.ok(await page.locator('#access').isVisible()||await page.getByRole('button',{name:/retry|try again|sign in/i}).count()>0,'Both panels remain hidden and no retry/sign-in control is available');
  });
  await scenario('long-business-name','valid 160-character unbroken business name does not overflow 360px',async()=>{
    const {page,model}=await setup({width:360,initialHook:async(route,m)=>{m.session.businesses[0].name='A'.repeat(160);m.records[A].profile.name='A'.repeat(160);return false;}});await ready(page);return await noOverflow(page);
  },{source:'backend/static/v1_app.css'});
  for(const role of ['manager','staff','viewer'])await scenario('role-'+role,`${role} controls match actual capability output`,async()=>{
    const {page,model}=await setup({role});await ready(page);
    const writable=model.session.businesses[0].capabilities.includes('business.write');assert.equal(await page.locator('#profile-save').isEnabled(),writable);await expect(page.locator('#team')).toBeHidden();
    assert.equal(model.requests.filter(r=>r.path.endsWith('/invitations')).length,0);
    if(!writable)for(const control of await page.locator('#profile-form input,#profile-form select').all())await expect(control).toBeDisabled();
  });
  await scenario('unavailable-business','unavailable requested tenant never falls back to another business',async()=>{
    const {page,model}=await setup({query:'?business=90000000-0000-4000-8000-000000000099'});await expect(page.locator('#loading')).toBeHidden();await expect(page.locator('#no-business')).toContainText('unavailable');await expect(page.locator('#business-content')).toBeHidden();assert.equal(model.requests.filter(r=>r.path.endsWith('/onboarding')).length,0);
  });
  await scenario('empty-membership','no memberships yields no cached profile or mutation controls',async()=>{
    const {page,model}=await setup({initialHook:async(route,m)=>{m.session.businesses=[];return false;}});await expect(page.locator('#loading')).toBeHidden();await expect(page.locator('#no-business')).toContainText('No active business access');await expect(page.locator('#business-content')).toBeHidden();assert.equal(model.requests.length,1);
  });
  await scenario('profile-busy','held profile save disables duplicates and exposes busy state',async()=>{
    const {page,model}=await setup();await ready(page);const held=gate();model.profileHook=async()=>{held.start();await held.held;return false;};await page.locator('#profile-save').click();await bounded(held.seen);await expect(page.locator('#profile-form')).toHaveAttribute('aria-busy','true');await expect(page.locator('#profile-save')).toBeDisabled();assert.equal(model.requests.filter(r=>r.method==='PUT').length,1);held.release();await expect(page.locator('#profile-status')).toHaveText('Business details saved.');await expect(page.locator('#profile-form')).not.toHaveAttribute('aria-busy','true');
  });
  await scenario('profile-lost-response','lost save response is not acknowledged; explicit reload resumes persisted facts',async()=>{
    const {page,model}=await setup();await ready(page);let first=true;model.profileHook=async(route,body,bid)=>{if(!first)return false;first=false;model.records[bid].profile.name=body.name;model.records[bid].profile.version++;model.session.businesses[0].name=body.name;await route.abort('failed');return true;};
    await page.locator('#profile-form [name=name]').fill('Confirmed after reload');await page.locator('#profile-save').click();await expect(page.locator('#profile-error')).not.toBeEmpty();await expect(page.locator('#profile-status')).not.toHaveText('Business details saved.');await page.locator('#profile-save').click();await expect(page.locator('#profile-error')).toContainText('changed');await page.reload();await ready(page);await expect(page.locator('#profile-form [name=name]')).toHaveValue('Confirmed after reload');assert.equal(model.records[A].profile.version,4);
  });
  await scenario('profile-switch','delayed A profile response cannot overwrite B workspace',async()=>{
    const {page,model}=await setup();await ready(page);const held=gate();model.profileHook=async()=>{held.start();await held.held;return false;};await page.locator('#profile-form [name=name]').fill('A private pending name');await page.locator('#profile-save').click();await bounded(held.seen);await page.locator('#business-picker').selectOption(B);await expect(page.locator('#profile-form [name=name]')).toHaveValue('Second QA Atelier');held.release();await settle(page);await expect(page.locator('#profile-form [name=name]')).toHaveValue('Second QA Atelier');assert.equal(await page.locator('#profile-status').textContent(),'Saved');
  });
  await scenario('session-profile-401','profile mutation 401 clears workspace and announces sign-in',async()=>{
    const {page,model}=await setup();await ready(page);await createInvite(page);model.profileHook=async route=>{await route.fulfill({status:401,json:{detail:'Synthetic session ended'}});return true;};await page.locator('#profile-save').click();await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#access-error')).toContainText('session ended');await expect(page.locator('#invite-link')).toHaveValue('');await expect(page.locator('#profile-form [name=name]')).toHaveValue('');
  },{severity:'P1'});
  await scenario('session-switch-401','business-load 401 clears workspace and presents sign-in',async()=>{
    const {page,model}=await setup();await ready(page);model.onboardingHook=async route=>{await route.fulfill({status:401,json:{detail:'Synthetic session ended'}});return true;};await page.locator('#business-picker').selectOption(B);await expect(page.locator('#global-error')).toContainText('session ended');await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#access')).toBeVisible();
  },{severity:'P2'});
  await scenario('session-revoke-401','invitation revoke 401 removes prior private profile and bearer link',async()=>{
    const {page,model}=await setup();await ready(page);await createInvite(page);model.deleteHook=async route=>{await route.fulfill({status:401,json:{detail:'Synthetic session ended'}});return true;};await page.getByRole('button',{name:'Revoke',exact:true}).click();await expect(page.locator('#invite-error')).toContainText('session ended');await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#invite-link')).toHaveValue('');
  },{severity:'P1'});
  await scenario('role-focus','returning focus revalidates a downgraded role before further edits',async()=>{
    const {page,model}=await setup();await ready(page);const reads=model.sessionGets;model.session=clone(fixtures.roles.viewer.session);await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect.poll(()=>model.sessionGets).toBeGreaterThan(reads);await expect(page.locator('#profile-save')).toBeDisabled();await expect(page.locator('#team')).toBeHidden();
  },{severity:'P2'});
  await scenario('session-focus','returning focus revalidates expired identity and clears private DOM',async()=>{
    const {page,model}=await setup();await ready(page);await createInvite(page);model.signedIn=false;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#invite-link')).toHaveValue('');await expect(page.locator('#profile-form [name=name]')).toHaveValue('');
  },{severity:'P2'});
  await scenario('cross-identity-error','prior profile error is absent after sign-out and another identity/business signs in',async()=>{
    const {page,model}=await setup();await ready(page);const marker='Synthetic A private profile error';
    model.profileHook=async route=>{await route.fulfill({status:422,json:{detail:marker}});return true;};
    await page.locator('#profile-save').click();await expect(page.locator('#profile-error')).toHaveText(marker);
    await page.locator('#logout').click();await expect(page.locator('#access')).toBeVisible();
    model.profileHook=null;model.session.user_id='20000000-0000-4000-8000-000000000082';model.session.csrf_token='synthetic-other-identity';model.session.businesses=model.session.businesses.filter(b=>b.id===B);
    await page.locator('#access-form [name=email]').fill('second-identity@example.com');await page.locator('#access-form [name=password]').fill('synthetic-password');await page.locator('#access-submit').click();await ready(page);
    await expect(page.locator('#business-heading')).toHaveText('Second QA Atelier');
    assert.equal(await page.locator('#profile-error').textContent(),'','Prior-context error remained visible under another identity/business');
  },{severity:'P1'});
  await scenario('literal-name','HTML-looking business facts render as text without executing',async()=>{
    const name='<img src=x onerror="window.__injected=true">';const {page}=await setup({initialHook:async(route,m)=>{m.session.businesses[0].name=name;m.records[A].profile.name=name;return false;}});await ready(page);await expect(page.locator('#business-heading')).toHaveText(name);assert.equal(await page.locator('#business-heading img').count(),0);assert.equal(await page.evaluate(()=>window.__injected),undefined);
  });
  await scenario('logout-storage','sign-out removes native recovery commands while preserving public checkout namespace',async()=>{
    const {page}=await setup();await ready(page);await page.evaluate(()=>{sessionStorage.setItem('munimjee.v1.import-command:synthetic','private');sessionStorage.setItem('munimjee.v1.theme-command:synthetic','private');sessionStorage.setItem('munimjee.checkout.v1:synthetic','public');});await page.locator('#logout').click();await expect(page.locator('#access')).toBeVisible();assert.deepEqual(await page.evaluate(()=>Object.keys(sessionStorage)),['munimjee.checkout.v1:synthetic']);
  });
  await scenario('logout-focus','sign-out leaves keyboard focus in the visible sign-in context',async()=>{
    const {page}=await setup();await ready(page);await page.locator('#logout').focus();await page.keyboard.press('Enter');await expect(page.locator('#access')).toBeVisible();const focus=await page.evaluate(()=>({tag:document.activeElement.tagName,id:document.activeElement.id,inside:document.getElementById('access').contains(document.activeElement)}));assert.ok(focus.inside,'Focus did not enter sign-in context: '+JSON.stringify(focus));return focus;
  });
  const after=Object.fromEntries(await Promise.all(files.map(async file=>[file,hash(await readFile(path.join(root,'backend/static',file)))])));
  const result={mode:'actual-native-onboarding-source-and-actual-formatter-with-synthetic-http',source_head:sourceHead,
    source_hashes_before:before,source_hashes_after:after,source_unchanged:JSON.stringify(before)===JSON.stringify(after),
    runner_sha256:hash(await readFile(fileURLToPath(import.meta.url))),fixture_sha256:hash(await readFile(path.join(out,'fixtures.json'))),fixture_sources_verified_before_browser:true,
    playwright_module:modulePath,chromium_executable:executable,browser_version:browser.version(),origin:base,
    server_started:false,requests_intercepted:true,unexpected_network:network,page_errors:pageErrors,
    passed:results.filter(r=>r.result==='passed').length,failed:results.filter(r=>r.result==='failed').length,results,
    unrun_gates:['actual mounted migrated DB','physical iPhone/Android','screen-reader interaction','complete contrast/WCAG audit','production/provider behavior']};
  await writeFile(path.join(out,'result.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({source_head:sourceHead,passed:result.passed,failed:result.failed,unexpected_network:network,page_errors:pageErrors,failed_cases:results.filter(r=>r.result==='failed').map(r=>({id:r.id,name:r.name,message:r.message}))},null,2));
  if(result.failed||network.length||pageErrors.length||!result.source_unchanged)process.exitCode=1;
}finally{for(const context of contexts)await context.close();await browser.close();}
