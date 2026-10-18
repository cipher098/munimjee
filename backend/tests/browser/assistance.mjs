/* Real mounted app/native/database journey. No provider traffic is permitted. */
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const module=process.env.PLAYWRIGHT_MODULE||'/Users/gothi/Documents/Codex/2026-10-10/help-me-understand-x20/work/munimjee-v1/frontend/storefront/node_modules/@playwright/test/index.mjs';
const {chromium,expect}=await import(pathToFileURL(module).href);
const base='http://127.0.0.1:8163',output=new URL('../../../artifacts/v1/assistance/',import.meta.url);
await mkdir(output,{recursive:true});const browser=await chromium.launch({headless:true});let checks=0;
const errors=[],external=[];
async function context(options={}){const c=await browser.newContext(options);await c.route('**/*',r=>{if(r.request().url().startsWith(base+'/'))return r.continue();external.push(r.request().url());return r.abort();});return c;}
async function start(p){for(let i=0;i<40;i++){try{await p.goto(base+'/v1');return;}catch(e){if(i===39)throw e;await new Promise(r=>setTimeout(r,250));}}}
async function api(p,path,method='GET',body){const session=await(await p.request.get(base+'/api/v1/auth/session')).json();const r=await p.request.fetch(base+path,{method,data:body,headers:{Origin:base,'X-CSRF-Token':session.csrf_token||''}});return {status:r.status(),data:await r.json()};}
const password='synthetic-console-password';
try{
 const owner=await context({viewport:{width:1440,height:1000}}),page=await owner.newPage();page.on('pageerror',e=>errors.push(e.message));await start(page);
 const email=`console-${crypto.randomUUID()}@example.com`;
 await page.locator('#access-form [name=business_name]').fill('Indigo Boutique');await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel(/^Password/).fill(password);await page.getByRole('button',{name:'Create account',exact:true}).click();await page.getByRole('heading',{name:'Indigo Boutique',exact:true}).waitFor();
 let session=(await api(page,'/api/v1/auth/session')).data;const bid=session.businesses[0].id,uid=session.user_id;
 assert.equal(session.auth_method,'v1_user');checks++;
 await page.goto(base+'/v1/assistance');await page.getByRole('button',{name:/Indigo Boutique/}).click();await expect(page.locator('#business-heading')).toHaveText('Indigo Boutique');await expect(page.locator('#notice')).toContainText('recorded under your own account');
 assert.equal(await page.locator('#steps li').count(),6);await expect(page.locator('#steps')).toContainText('Live check pending');checks+=2;
 await page.locator('#assignee').selectOption(uid);await page.locator('#assignment-reviewed').check();await page.getByRole('button',{name:'Save onboarding lead',exact:true}).click();await expect(page.locator('#notice')).toContainText('Lead assignment confirmed');
 assert.equal((await api(page,`/api/v1/businesses/${bid}/assistance`)).data.assignment.assignee_user_id,uid);checks++;
 await page.locator('#filter').selectOption('mine');await expect(page.locator('#business-list')).toContainText('Indigo Boutique');checks++;
 // Commit a real assignment, then lose only its HTTP response. Reload is GET-only.
 let lost=false;const sent=[];await page.route(`**/businesses/${bid}/assistance/assignment`,async route=>{if(route.request().method()!=='PUT')return route.continue();sent.push(route.request().postDataJSON());if(lost)return route.continue();lost=true;const r=await route.fetch();assert.equal(r.status(),200);await route.abort('failed');});
 await page.locator('#assignee').selectOption('');await page.locator('#assignment-reviewed').check();await page.getByRole('button',{name:'Save onboarding lead',exact:true}).click();await expect(page.locator('#recovery')).toBeVisible();
 await page.reload();await expect(page.locator('#recovery')).toBeVisible();assert.equal(sent.length,1);await page.getByRole('button',{name:'Check the saved action again',exact:true}).click();await expect(page.locator('#notice')).toContainText('Lead assignment confirmed');assert.deepEqual(sent[0],sent[1]);assert.equal((await api(page,`/api/v1/businesses/${bid}/assistance`)).data.assignment.version,2);checks+=3;
 await page.unroute(`**/businesses/${bid}/assistance/assignment`);
 // Invite a real viewer and prove there is no member-directory/configuration fetch.
 const viewerEmail=`viewer-${crypto.randomUUID()}@example.com`,invite=await api(page,`/api/v1/businesses/${bid}/invitations`,'POST',{email:viewerEmail,role:'viewer'});
 assert.equal(invite.status,201);const viewer=await context({viewport:{width:390,height:844}}),vp=await viewer.newPage();
 await vp.goto(base+invite.data.invitation_url);await vp.getByLabel('Email',{exact:true}).fill(viewerEmail);await vp.getByLabel(/^Password/).fill(password);await vp.getByRole('button',{name:'Accept invitation',exact:true}).click();await vp.getByRole('heading',{name:'Indigo Boutique',exact:true}).waitFor();
 const reads=[];vp.on('request',r=>reads.push(r.url()));await vp.goto(base+`/v1/businesses/${bid}/assistance`);await expect(vp.locator('#detail-content')).toBeVisible();
 assert.equal(await vp.locator('#assignment-form').isHidden(),true);assert.equal(reads.some(u=>u.endsWith('/assignees')||u.endsWith('/payments/razorpay')),false);assert.equal(await vp.locator('#steps a[href$="/payments"]').count(),0);checks+=3;
 await vp.screenshot({path:new URL('mobile-viewer.png',output).pathname,fullPage:true});assert.equal(await vp.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++;await viewer.close();
 // A second boutique invites this existing account as manager. No identity merge.
 const second=await context(),sp=await second.newPage();await start(sp);const secondEmail=`boutique-${crypto.randomUUID()}@example.com`;
 let response=await sp.request.post(base+'/api/v1/auth/signup',{data:{email:secondEmail,password,business_name:'Saffron Studio'},headers:{Origin:base}});assert.equal(response.status(),201);const other=(await response.json()).businesses[0].id;
 const invitation=await api(sp,`/api/v1/businesses/${other}/invitations`,'POST',{email,role:'manager'});
 response=await page.request.post(base+'/api/v1/auth/invitations/accept',{data:{email,password,token:invitation.data.invitation_url.split('#invite=')[1]},headers:{Origin:base}});assert.equal(response.status(),200);checks++;
 await page.goto(base+'/v1/assistance');await expect(page.locator('#business-list button')).toHaveCount(2);await page.getByRole('button',{name:/Saffron Studio/}).click();await expect(page.locator('#business-heading')).toHaveText('Saffron Studio');assert.equal(await page.locator('#assignment-form').isHidden(),true);checks++;
 await page.getByRole('button',{name:/Indigo Boutique/}).click();await expect(page.locator('#assignment-form')).toBeVisible();
 // Race a detail response from A with newer selection B; older facts stay withheld.
 await expect(page.locator('#refresh')).toBeEnabled();
 let release,entered,settled;const gate=new Promise(r=>release=r),seen=new Promise(r=>entered=r),done=new Promise(r=>settled=r);let held=false;
 await page.route(`**/businesses/${bid}/assistance`,async route=>{if(held)return route.continue();held=true;const response=await route.fetch();entered();await gate;await route.fulfill({response});settled();});
 await page.getByRole('button',{name:'Refresh',exact:true}).click();await seen;await page.getByRole('button',{name:/Saffron Studio/}).click();await expect(page.locator('#business-heading')).toHaveText('Saffron Studio');release();await done;await page.unroute(`**/businesses/${bid}/assistance`);await expect(page.locator('#business-heading')).toHaveText('Saffron Studio');checks++;
 await page.getByRole('button',{name:/Indigo Boutique/}).click();await expect(page.locator('#assignment-form')).toBeVisible();
 await expect(page.locator('#refresh')).toBeEnabled();await expect(page.locator('#recovery')).toBeHidden();
 await page.screenshot({path:new URL('desktop-owner.png',output).pathname,fullPage:true});await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:new URL('mobile-owner.png',output).pathname,fullPage:true});checks++;
 // A fresh session projection removes an already rendered, nonselected revoked tenant.
 execFileSync(process.env.BROWSER_PYTHON,['-m','tests.assistance_fixture','revoke',other,uid],{cwd:new URL('../../',import.meta.url),env:process.env});
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#business-list')).not.toContainText('Saffron Studio');await expect(page.locator('#business-heading')).toHaveText('Indigo Boutique');checks++;
 execFileSync(process.env.BROWSER_PYTHON,['-m','tests.assistance_fixture','viewer',bid,uid],{cwd:new URL('../../',import.meta.url),env:process.env});
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#business-intro')).toContainText('Your access: viewer');await expect(page.locator('#assignment-form')).toBeHidden();await expect(page.locator('#assignee')).toBeEmpty();assert.equal(await page.locator('#steps a[href$="/payments"]').count(),0);checks+=2;
 // A late successful guard cannot restore private DOM after a replacement sign-in.
 let guardRelease,guardStarted;const guardGate=new Promise(r=>guardRelease=r),guardSeen=new Promise(r=>guardStarted=r);let heldSession=false;
 await page.route('**/api/v1/auth/session',async route=>{if(heldSession)return route.continue();heldSession=true;const response=await route.fetch();guardStarted();await guardGate;await route.fulfill({response});});
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await guardSeen;
 response=await page.request.post(base+'/api/v1/auth/login',{data:{email,password},headers:{Origin:base}});assert.equal(response.status(),200);
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));guardRelease();await expect(page.locator('#session-ended')).toBeVisible();
 assert.equal(await page.locator('#business-list').textContent(),'');assert.equal(await page.locator('#steps').textContent(),'');assert.equal(await page.locator('#assignee').textContent(),'');await page.screenshot({path:new URL('mobile-session-ended.png',output).pathname,fullPage:true});checks+=3;
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);checks+=2;
 await writeFile(new URL('browser-results.json',output),JSON.stringify({checks,provider_calls:0,source:'actual app.main, native sessions, migrated PostgreSQL0050',external_requests:external},null,2)+'\n');
 console.log(`${checks} real assistance browser checks passed`);await second.close();await owner.close();
}finally{await browser.close();}
