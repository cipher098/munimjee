/* Real mounted signup/profile/invitation/session routes; only response timing is held. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const {chromium,expect}=await import(pathToFileURL('/Users/gothi/Documents/Codex/2026-10-10/help-me-understand-x20/work/munimjee-v1/frontend/storefront/node_modules/@playwright/test/index.mjs').href);
const base='http://127.0.0.1:8170',root=new URL('../../../',import.meta.url),out=new URL('artifacts/v1/onboarding-followup/mounted/',root);
await mkdir(out,{recursive:true});
const sourceFiles=['backend/static/v1_app.js','backend/static/v1_client.js','backend/app/services/onboarding.py','backend/app/api/v1/auth.py','backend/app/api/v1/session.py','backend/tests/browser/onboarding-followup.mjs','backend/tests/onboarding_followup_server.py','backend/tests/run_onboarding_followup_browser.py'];
const hashes=async()=>Object.fromEntries(await Promise.all(sourceFiles.map(async p=>[p,createHash('sha256').update(await readFile(new URL(p,root))).digest('hex')])));
const before=await hashes(),source=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),browser=await chromium.launch({headless:true}),results=[],errors=[],external=[];
async function fixture(){
 const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():(external.push(r.request().url()),r.abort()));
 for(let n=0;n<60;n++){try{await page.goto(base+'/v1');break;}catch{await new Promise(r=>setTimeout(r,100));}}
 await expect(page.locator('#access-title')).toHaveText('Create your account');
 const email='native-'+crypto.randomUUID()+'@example.com',password='synthetic-native-password';
 await page.locator('#access-form [name=business_name]').fill('Synthetic native boutique');await page.locator('#access-form [name=email]').fill(email);await page.locator('#access-form [name=password]').fill(password);await page.locator('#access-submit').click();
 await expect(page.locator('#business-content')).toBeVisible();const session=await(await context.request.get(base+'/api/v1/auth/session')).json(),bid=session.businesses[0].id;
 return {context,page,email,password,bid,uid:session.user_id};
}
try{
 let identity;
 {
  const f=await fixture(),p=f.page;identity=await(await f.context.request.get(base+'/__onboarding/identify')).json();assert.equal(identity.nonce,process.env.ONBOARDING_FIXTURE_NONCE);assert.equal(identity.mounted,'app.main');
  await expect(p.locator('#setup-progress')).toHaveText('1 of 6 ready');results.push('first unauthenticated visit retains Create account; real UI signup opens six-step checklist');
  await p.locator('#profile-form [name=support_email]').fill('private-native@example.com');await p.locator('#profile-form [name=phone]').fill('9876543210');await p.locator('#profile-save').click();await expect(p.locator('#setup-progress')).toHaveText('2 of 6 ready');await expect(p.locator('#profile-form [name=support_email]')).toHaveValue('private-native@example.com');results.push('real profile save advances only the confirmed local setup step');await p.screenshot({path:new URL('mobile-owner-progress.png',out).pathname,fullPage:false});
  await p.locator('#invite-form [name=email]').fill('synthetic-team-'+crypto.randomUUID()+'@example.com');await p.getByRole('button',{name:'Create invitation link',exact:true}).click();await expect(p.locator('#invite-result')).toBeVisible();assert.match(await p.locator('#invite-link').inputValue(),/#invite=/);results.push('real owner invitation returns a private one-use link without rendering it in evidence');
  await p.locator('#logout').click();await expect(p.locator('#access')).toBeVisible();await expect(p.locator('#logout')).toBeHidden();await expect(p.locator('#logout-all')).toBeHidden();assert.equal(await p.locator('#invite-link').inputValue(),'');assert.equal(await p.locator('#profile-form [name=support_email]').inputValue(),'');assert.equal(await p.locator('#team-list').textContent(),'');results.push('real logout clears profile/team/invitation DOM and both identity actions');await p.screenshot({path:new URL('mobile-session-ended.png',out).pathname,fullPage:false});await f.context.close();
 }
 {
  const f=await fixture(),p=f.page;const login=await f.context.request.post(base+'/api/v1/auth/login',{headers:{Origin:base},data:{email:f.email,password:f.password}});assert.equal(login.status(),200);let mutations=0;p.on('request',r=>{if(r.url().startsWith(base+'/api/')&&r.method()!=='GET')mutations++;});await p.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(p.locator('#access')).toBeVisible();assert.equal(mutations,0);assert.equal(await p.locator('#business-picker option').count(),0);results.push('same-user real session replacement fences current workspace before another mutation');await f.context.close();
 }
 {
  const f=await fixture(),p=f.page;let release,held=false;await p.route('**/api/v1/auth/session',async r=>{if(held)return r.continue();held=true;const response=await r.fetch();const wait=new Promise(resolve=>release=resolve);await wait;await r.fulfill({response});});
  await p.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect.poll(()=>!!release).toBe(true);
  const changed=await f.context.request.post(base+`/__onboarding/viewer?business_id=${f.bid}&user_id=${f.uid}`,{headers:{'X-Fixture-Nonce':process.env.ONBOARDING_FIXTURE_NONCE}});assert.equal(changed.status(),200);
  await p.selectOption('#business-picker',f.bid,{force:true});await expect(p.locator('#profile-form [name=name]')).toBeDisabled();release();await expect(p.locator('#team')).toBeHidden();await expect(p.locator('#profile-save')).toBeDisabled();assert.equal(await p.locator('#invite-link').inputValue(),'');await expect(p.locator('#business-tools')).not.toContainText('Payment setup');results.push('older real owner-session response cannot restore controls after newer actual viewer downgrade');await p.screenshot({path:new URL('mobile-viewer-progress.png',out).pathname,fullPage:false});await f.context.close();
 }
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);const after=await hashes();assert.deepEqual(after,before);await writeFile(new URL('browser-results.json',out),JSON.stringify({source_commit:source,checks:results.length,results,revision:identity.revision,mount:identity.mounted,before,after,page_errors:errors,external_requests:external,provider_calls:0,proof_boundary:'Actual native API/DB; test-only nonce role fixture and held actual HTTP response; no provider evidence'},null,2)+'\n');console.log(`PASS ${results.length} actual native onboarding/privacy journeys; providers0.`);
}finally{await browser.close();}
