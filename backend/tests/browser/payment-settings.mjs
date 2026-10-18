/* Mounted native UI/API with synthetic credentials. Provider calls are forbidden. */
import {chromium,expect} from '../../../frontend/storefront/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';import {mkdir} from 'node:fs/promises';
const base='http://127.0.0.1:8162',output=new URL('../../../artifacts/v1/payment-settings/',import.meta.url);
await mkdir(output,{recursive:true});const browser=await chromium.launch({headless:true});let checks=0;
const secrets=['synthetic-api-secret-ONE','synthetic-webhook-secret-ONE','synthetic-api-secret-TWO','synthetic-webhook-secret-TWO'];
const logs=[],external=[],errors=[];
async function context(viewport={width:1365,height:1000}){const c=await browser.newContext({viewport});await c.route('**/*',r=>{if(r.request().url().startsWith(base+'/'))return r.continue();external.push(r.request().url());return r.abort();});return c;}
async function watch(page){page.setDefaultTimeout(12000);page.on('console',m=>logs.push(m.text()));page.on('pageerror',e=>errors.push(e.message));}
async function ready(page){for(let n=0;n<50;n++){try{await page.goto(base+'/v1');return;}catch(error){if(n===49)throw error;await new Promise(r=>setTimeout(r,200));}}}
async function setup(label='Indigo Boutique'){
 const c=await context(),page=await c.newPage();await watch(page);await ready(page);
 const email=`settings-${crypto.randomUUID()}@example.com`,password='synthetic-native-password';
 await page.locator('#access-form [name=business_name]').fill(label);await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel(/^Password/).fill(password);await page.getByRole('button',{name:'Create account',exact:true}).click();await page.getByRole('heading',{name:label,exact:true}).waitFor();
 const session=await(await page.request.get(base+'/api/v1/auth/session')).json(),bid=session.businesses[0].id,api=`/api/v1/businesses/${bid}/payments/razorpay`,url=base+`/v1/businesses/${bid}/payments`,headers={Origin:base,'X-CSRF-Token':session.csrf_token};
 await page.goto(url);await expect(page.locator('#account-status')).toHaveText('Not configured');checks++;
 return {c,page,email,password,bid,api,url,headers,session};
}
async function fill(page,{key='rzp_test_synthetic',api=secrets[0],webhook=secrets[1],enabled=false}={}){
 await page.getByLabel('Key ID',{exact:true}).fill(key);
 if(!await page.locator('#api-secret').isVisible())await page.getByLabel('Replace the stored API secret',{exact:true}).check();
 if(!await page.locator('#webhook-secret').isVisible())await page.getByLabel('Replace the stored webhook secret',{exact:true}).check();
 await page.getByLabel('API secret',{exact:true}).fill(api);await page.getByLabel('Webhook secret',{exact:true}).fill(webhook);
 await page.locator('#gateway-enabled').setChecked(enabled);
 if(await page.locator('#replacement-review-label').isVisible())await page.locator('#replacement-review').check();
}
async function saved(page){await page.getByRole('button',{name:/^Save (payment setup|replacement credentials)$/}).click();await expect(page.locator('#notice')).toHaveText('Payment settings saved. A Razorpay connection was not checked.');}
async function noSecrets(page){
 assert.equal(await page.locator('#api-secret').inputValue(),'');assert.equal(await page.locator('#webhook-secret').inputValue(),'');
 const state=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage},body:document.body.innerText}));
 for(const secret of secrets)assert.ok(!state.includes(secret));checks++;
}
try{
 const data=await setup(),{page}=data;const writes=[];
 page.on('request',request=>{if(request.url()===base+data.api&&request.method()==='PUT')writes.push(request.postDataJSON());});
 assert.equal((await page.request.get(data.url)).headers()['cache-control'],'no-store');
 await expect(page.getByText('Saving credentials does not contact Razorpay or verify a live connection.',{exact:false})).toBeVisible();
 await page.screenshot({path:new URL('desktop-not-configured.png',output).pathname,fullPage:true});checks++;
 await fill(page);await saved(page);assert.equal(writes.length,1);assert.match(writes[0].expected_revision,/^[a-f0-9]{64}$/);await noSecrets(page);
 assert.equal((await(await page.request.get(base+'/__payment-settings-test/status')).json()).public_payments_enabled,false);checks++;
 await page.setViewportSize({width:390,height:844});await page.reload();await expect(page.locator('#account-status')).toHaveText('Credentials configured');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await noSecrets(page);
 await page.screenshot({path:new URL('mobile-configured.png',output).pathname,fullPage:true});checks++;
 // Preference-only saves omit secrets and may retain the same revision on no-op.
 await page.locator('#gateway-enabled').check();await saved(page);assert.equal(Object.hasOwn(writes.at(-1),'key_secret'),false);assert.equal(Object.hasOwn(writes.at(-1),'webhook_secret'),false);checks++;
 // Client validation never sends mismatched mode/key or echoes secret content.
 const prior=writes.length;await page.getByLabel('Key ID',{exact:true}).fill('rzp_live_wrongmode');await page.getByLabel('API secret',{exact:true}).fill(secrets[0]);await page.getByRole('button',{name:'Save payment setup',exact:true}).click();await expect(page.locator('#form-error')).toContainText('matches the selected');assert.equal(writes.length,prior);checks++;
 await page.getByRole('button',{name:'Refresh settings',exact:true}).click();await expect(page.getByLabel('Key ID',{exact:true})).toHaveValue('rzp_test_synthetic');await noSecrets(page);
 // Two writers: a newer settings revision causes a typed pre-write rejection.
 const current=await(await page.request.get(base+data.api)).json();let actual=await page.request.put(base+data.api,{headers:data.headers,data:{key_id:'rzp_test_otherwriter',key_secret:secrets[2],webhook_secret:secrets[3],mode:'test',enabled:true,expected_revision:current.configuration_revision}});assert.equal(actual.status(),200);
 await page.locator('#gateway-enabled').uncheck();await page.getByRole('button',{name:'Save payment setup',exact:true}).click();await expect(page.locator('#page-error')).toContainText('changed while you were editing');assert.equal((await(await page.request.get(base+data.api)).json()).key_id,'rzp_test_otherwriter');checks++;
 await page.getByRole('button',{name:'Refresh settings',exact:true}).click();await expect(page.getByLabel('Key ID',{exact:true})).toHaveValue('rzp_test_otherwriter');
 // Committed response loss retains only a nonsecret marker; reload never replays.
 let oldBody;await page.route('**'+data.api,async route=>{if(route.request().method()!=='PUT')return route.continue();oldBody=route.request().postDataJSON();const response=await route.fetch();assert.equal(response.status(),200);return route.abort('failed');});
 await fill(page,{key:'rzp_test_afterloss',api:secrets[0],webhook:secrets[1],enabled:true});await page.getByRole('button',{name:'Save payment setup',exact:true}).click();await expect(page.locator('#recovery')).toBeVisible();await noSecrets(page);
 await page.unroute('**'+data.api);const beforeReload=writes.length;await page.reload();await expect(page.locator('#recovery')).toBeVisible();assert.equal(writes.length,beforeReload);assert.equal(await page.locator('#editor').isVisible(),false);await expect(page.locator('#notice')).toBeEmpty();checks++;
 await page.getByRole('button',{name:'Check saved settings',exact:true}).click();await expect(page.getByRole('button',{name:'Replace current credentials',exact:true})).toBeEnabled();await expect(page.locator('#notice')).toBeEmpty();checks++;
 await page.screenshot({path:new URL('mobile-unknown-save.png',output).pathname,fullPage:true});
 await page.getByRole('button',{name:'Replace current credentials',exact:true}).click();await fill(page,{key:'rzp_test_afterloss',api:secrets[2],webhook:secrets[3],enabled:true});await saved(page);await noSecrets(page);
 const finalRevision=(await(await page.request.get(base+data.api)).json()).configuration_revision;
 // Delayed old conditional request cannot overwrite the newly reviewed replacement.
 const late=await page.request.put(base+data.api,{headers:data.headers,data:oldBody});assert.equal(late.status(),409);assert.equal((await late.json()).detail.code,'gateway_config_stale');assert.equal((await(await page.request.get(base+data.api)).json()).configuration_revision,finalRevision);checks++;
 // A valid-shaped old 200 cannot acknowledge supplied secret replacement.
 const oldAck=await(await page.request.get(base+data.api)).json();
 await page.route('**'+data.api,async route=>{if(route.request().method()!=='PUT')return route.continue();const committed=await route.fetch();assert.equal(committed.status(),200);return route.fulfill({status:200,json:oldAck});});
 await fill(page,{key:oldAck.key_id,api:secrets[0],webhook:secrets[1],enabled:oldAck.enabled});await page.getByRole('button',{name:'Save payment setup',exact:true}).click();await expect(page.locator('#recovery')).toBeVisible();await expect(page.locator('#notice')).toBeEmpty();await noSecrets(page);assert.equal(await page.evaluate(()=>Object.keys(sessionStorage).some(k=>k.startsWith('munimjee.v1.gateway-intent:'))),true);await page.unroute('**'+data.api);checks++;
 await page.getByRole('button',{name:'Check saved settings',exact:true}).click();await page.getByRole('button',{name:'Replace current credentials',exact:true}).click();await fill(page,{key:oldAck.key_id,api:secrets[2],webhook:secrets[3],enabled:oldAck.enabled});await saved(page);
 // Malformed committed 200 also remains uncertain; no saved claim from GET.
 await page.route('**'+data.api,async route=>{if(route.request().method()!=='PUT')return route.continue();await route.fetch();return route.fulfill({status:200,json:{}});});
 await page.locator('#gateway-enabled').uncheck();await page.getByRole('button',{name:'Save payment setup',exact:true}).click();await expect(page.locator('#recovery')).toBeVisible();await expect(page.locator('#notice')).toBeEmpty();await noSecrets(page);await page.unroute('**'+data.api);
 await page.getByRole('button',{name:'Check saved settings',exact:true}).click();await expect(page.getByRole('button',{name:'Replace current credentials',exact:true})).toBeEnabled();checks++;
 // An older successful session read cannot repopulate DOM after sign-out.
 let sessionEntered,sessionRelease,sessionFinished,sessionHeld=false;const sessionWaiting=new Promise(r=>sessionEntered=r),sessionContinue=new Promise(r=>sessionRelease=r),sessionDone=new Promise(r=>sessionFinished=r);
 await page.route('**/api/v1/auth/session',async route=>{if(route.request().method()!=='GET'||sessionHeld)return route.continue();sessionHeld=true;const response=await route.fetch();sessionEntered();await sessionContinue;await route.fulfill({response});sessionFinished();});
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await sessionWaiting;
 // Logout clears every private field immediately, even before its response.
 await page.getByRole('button',{name:'Sign out',exact:true}).click();await expect(page.locator('#access-message')).toContainText('Signed out');sessionRelease();await sessionDone;await page.unroute('**/api/v1/auth/session');await page.waitForTimeout(100);await expect(page.locator('#logout')).toBeHidden();await expect(page.locator('#business-name')).toHaveText('Payment setup');await expect(page.locator('#recovery-message')).toBeEmpty();await expect(page.locator('#recovery-current')).toBeEmpty();assert.equal(await page.locator('#catalogue-link').getAttribute('href'),null);checks++;assert.equal(await page.locator('#workspace').isVisible(),false);await noSecrets(page);assert.equal(await page.evaluate(()=>Object.keys(sessionStorage).some(k=>k.startsWith('munimjee.v1.gateway-intent:'))),false);checks++;
 await data.c.close();
 // Manager can configure; owner revocation on another page scrubs current DOM.
 const owner=await setup('Shared Boutique');await fill(owner.page);await saved(owner.page);
 const inviteEmail=`manager-${crypto.randomUUID()}@example.com`,invitation=await(await owner.page.request.post(base+`/api/v1/businesses/${owner.bid}/invitations`,{headers:owner.headers,data:{email:inviteEmail,role:'manager'}})).json();
 const managerContext=await context({width:390,height:844}),manager=await managerContext.newPage();await watch(manager);
 const accepted=await manager.request.post(base+'/api/v1/auth/invitations/accept',{headers:{Origin:base},data:{email:inviteEmail,password:'synthetic-manager-password',token:invitation.invitation_url.split('=')[1]}});assert.equal(accepted.status(),200);const managerSession=await accepted.json();
 await manager.goto(owner.url);await expect(manager.locator('#account-status')).toHaveText('Credentials configured');await manager.getByLabel('Replace the stored API secret',{exact:true}).check();await manager.getByLabel('API secret',{exact:true}).fill(secrets[0]);checks++;
 const members=await(await owner.page.request.get(base+`/api/v1/businesses/${owner.bid}/members`)).json(),membership=members.find(m=>m.user_id===managerSession.user_id);
 assert.equal((await owner.page.request.patch(base+`/api/v1/businesses/${owner.bid}/members/${membership.id}`,{headers:owner.headers,data:{action:'revoke'}})).status(),200);
 await manager.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(manager.locator('#access-needed')).toBeVisible();assert.equal(await manager.locator('#key-id').inputValue(),'');assert.equal(await manager.locator('#account-summary').innerText(),'');await noSecrets(manager);checks++;
 await managerContext.close();
 // Staff receives a useful denial shell but never fetches private config.
 const staffEmail=`staff-${crypto.randomUUID()}@example.com`,staffInvite=await(await owner.page.request.post(base+`/api/v1/businesses/${owner.bid}/invitations`,{headers:owner.headers,data:{email:staffEmail,role:'staff'}})).json();
 const staffContext=await context({width:390,height:844}),staff=await staffContext.newPage();await watch(staff);let staffReads=0;
 staff.on('request',r=>{if(r.url()===base+owner.api)staffReads++;});
 assert.equal((await staff.request.post(base+'/api/v1/auth/invitations/accept',{headers:{Origin:base},data:{email:staffEmail,password:'synthetic-staff-password',token:staffInvite.invitation_url.split('=')[1]}})).status(),200);
 await staff.goto(owner.url);await expect(staff.locator('#access-message')).toContainText('owner or manager');assert.equal(staffReads,0);await staff.screenshot({path:new URL('mobile-role-denied.png',output).pathname,fullPage:true});checks++;await staffContext.close();
 // A delayed old configuration response cannot render after a different login.
 let release,entered;const enteredPromise=new Promise(r=>entered=r),releasePromise=new Promise(r=>release=r);
 await owner.page.route('**'+owner.api,async route=>{if(route.request().method()!=='GET')return route.continue();const response=await route.fetch();entered();await releasePromise;return route.fulfill({response});});
 const nav=owner.page.goto(owner.url);await enteredPromise;
 assert.equal((await owner.page.request.post(base+'/api/v1/auth/signup',{headers:{Origin:base},data:{email:`other-${crypto.randomUUID()}@example.com`,password:'synthetic-other-password',business_name:'Other Business'}})).status(),201);
 release();await nav;await expect(owner.page.locator('#access-needed')).toBeVisible();assert.equal(await owner.page.locator('#key-id').inputValue(),'');assert.equal(await owner.page.locator('#account-summary').innerText(),'');checks++;await owner.page.unroute('**'+owner.api);await owner.c.close();
 // Missing/malformed recovery is withheld; storage failure sends no credential PUT.
 const safety=await setup('Recovery Boutique');let safetyWrites=0;safety.page.on('request',r=>{if(r.url()===base+safety.api&&r.method()==='PUT')safetyWrites++;});
 await safety.page.evaluate(({user,bid})=>sessionStorage.setItem('munimjee.v1.gateway-intent:'+user+':'+bid,'{"broken":true}'),{user:safety.session.user_id,bid:safety.bid});
 await safety.page.reload();await expect(safety.page.locator('#recovery')).toBeVisible();await expect(safety.page.locator('#recovery-message')).toContainText('withheld');assert.equal(safetyWrites,0);assert.equal(await safety.page.locator('#editor').isVisible(),false);checks++;
 await safety.page.evaluate(()=>sessionStorage.clear());await safety.page.reload();await expect(safety.page.locator('#account-status')).toHaveText('Not configured');
 await safety.page.evaluate(()=>{Storage.prototype.setItem=()=>{throw new Error('Restricted storage');};});await fill(safety.page);await safety.page.getByRole('button',{name:'Save payment setup',exact:true}).click();await expect(safety.page.locator('#form-error')).toContainText('Enable browser session storage');assert.equal(safetyWrites,0);await noSecrets(safety.page);checks++;await safety.c.close();
 // A held pre-submit session read cannot dispatch credentials after access closes.
 const fence=await setup('Session Fence Boutique');let fenceWrites=0;fence.page.on('request',r=>{if(r.url()===base+fence.api&&r.method()==='PUT')fenceWrites++;});
 let fenceEntered,fenceRelease,fenceFinished,fenceHeld=false;const fenceWaiting=new Promise(r=>fenceEntered=r),fenceContinue=new Promise(r=>fenceRelease=r),fenceDone=new Promise(r=>fenceFinished=r);
 await fence.page.route('**/api/v1/auth/session',async route=>{if(fenceHeld)return route.continue();fenceHeld=true;const response=await route.fetch();fenceEntered();await fenceContinue;await route.fulfill({response});fenceFinished();});
 await fill(fence.page);await fence.page.getByRole('button',{name:'Save payment setup',exact:true}).click();await fenceWaiting;await fence.page.getByRole('button',{name:'Sign out',exact:true}).click();await expect(fence.page.locator('#access-message')).toContainText('Signed out');fenceRelease();await fenceDone;await fence.page.waitForTimeout(100);assert.equal(fenceWrites,0);await expect(fence.page.locator('#logout')).toBeHidden();await expect(fence.page.locator('#business-name')).toHaveText('Payment setup');await noSecrets(fence.page);checks++;await fence.c.close();
 // The first context has been closed; verify global network/provider evidence in a fresh context.
 const verifier=await context(),check=await verifier.request.get(base+'/__payment-settings-test/status');assert.equal((await check.json()).provider_calls,0);await verifier.close();
 for(const secret of secrets)assert.ok(!logs.join('\n').includes(secret));assert.deepEqual(errors,[]);assert.deepEqual(external,[]);checks++;
 console.log(`PASS ${checks} native payment settings Chromium checks: real signup/API/CAS, masked entry, no stored secret echo, same-key unknown-save recovery, stale response/conditional request fences, manager revocation and staff denial. No provider calls or charges.`);
}finally{await browser.close();}
