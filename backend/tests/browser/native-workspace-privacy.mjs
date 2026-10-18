/* Actual native HTML/JS in Chromium; controlled HTTP only, no API/DB acceptance. */
import assert from 'node:assert/strict';import {readFile,writeFile,mkdir} from 'node:fs/promises';import {pathToFileURL} from 'node:url';
const {chromium,expect}=await import(pathToFileURL('/Users/gothi/Documents/Codex/2026-10-10/help-me-understand-x20/work/munimjee-v1/frontend/storefront/node_modules/@playwright/test/index.mjs').href);
const base='http://127.0.0.1:8170',root=new URL('../../../',import.meta.url),out=new URL('artifacts/v1/onboarding-followup/',root);await mkdir(out,{recursive:true});
const A='11111111-1111-4111-8111-111111111111',B='22222222-2222-4222-8222-222222222222',uid='33333333-3333-4333-8333-333333333333';
const caps=['business.read','business.write','readiness.read','members.manage','catalogue.read','analytics.read'];
const make=(businesses=[{id:A,name:'Allowed Boutique A',role:'owner',capabilities:caps},{id:B,name:'Revoked Boutique B',role:'owner',capabilities:caps}])=>({user_id:uid,csrf_token:'bound-session-csrf',auth_method:'v1_user',businesses,features:{}});
const browser=await chromium.launch({headless:true}),results=[];
async function fixture(){
 const context=await browser.newContext({viewport:{width:390,height:844}});await context.addCookies([{name:'v1_csrf',value:'bound-session-csrf',url:base}]);let session=make(),status=200,held=null,holdNext=false,calls=[];
 const page=await context.newPage();page.setDefaultTimeout(6000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',async route=>{const url=new URL(route.request().url());assert.equal(url.origin,base);
  if(url.pathname==='/v1')return route.fulfill({contentType:'text/html',body:await readFile(new URL('backend/static/v1_app.html',root),'utf8')});
  if(url.pathname.startsWith('/static/')){const name=url.pathname.slice(8);assert(['v1_app.js','v1_app.css','v1_client.js','commerce.css'].includes(name));return route.fulfill({contentType:name.endsWith('.js')?'text/javascript':'text/css',body:await readFile(new URL('backend/static/'+name,root),'utf8')});}
  calls.push({path:url.pathname,method:route.request().method()});
  if(url.pathname==='/api/v1/auth/session'){
   const body=structuredClone(session),code=status;
   if(holdNext){holdNext=false;let release;const wait=new Promise(r=>release=r);held={release};await wait;}
   return route.fulfill({status:code,json:body});
  }
  if(url.pathname.endsWith('/onboarding'))return route.fulfill({json:{business_id:A,profile:{version:0,name:'Allowed Boutique A',profile:{support_email:'private-owner@example.com',phone:'9876543210',website:'https://private.example.com'},confirmed:false},completed_steps:1,total_steps:5,steps:[]}});
  if(url.pathname.endsWith('/invitations'))return route.fulfill({status:route.request().method()==='POST'?201:200,json:route.request().method()==='POST'?{invitation_url:'/v1#invite=private-bearer-sentinel'}:[{id:'44444444-4444-4444-8444-444444444444',email:'private-team@example.com',role:'staff',revoked:false,consumed:false,expires_at:'2099-01-01'}]});
  throw Error('Unexpected path '+url.pathname);
 });
 await page.goto(base+'/v1');await expect(page.locator('#business-content')).toBeVisible();await expect(page.locator('#team-list')).toContainText('private-team');
 return {context,page,errors,calls,setSession:value=>session=value,setStatus:value=>status=value,hold:()=>holdNext=true,held:()=>held};
}
try{
 {
 const f=await fixture(),p=f.page;await p.locator('#invite-form [name=email]').fill('new-team@example.com');await p.getByRole('button',{name:'Create invitation link',exact:true}).click();await expect(p.locator('#invite-link')).toHaveValue(/private-bearer/);
 f.setStatus(401);f.setSession({detail:'expired'});await p.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(p.locator('#access')).toBeVisible();
 for(const id of ['profile-form','invite-form'])assert.equal(await p.locator('#'+id).evaluate(n=>[...n.elements].some(x=>/private-|987654/.test(x.value||''))),false);
 assert.equal(await p.locator('#invite-link').inputValue(),'');assert.equal(await p.locator('#team-list').textContent(),'');assert.equal(await p.locator('#business-picker option').count(),0);await expect(p.locator('#logout')).toBeHidden();await expect(p.locator('#logout-all')).toBeHidden();results.push('confirmed401 physically clears profile/team/picker/invite bearer and hides identity actions');await p.screenshot({path:new URL('mobile-access-ended.png',out).pathname,fullPage:false});assert.deepEqual(f.errors,[]);await f.context.close();
 }
 {
 const f=await fixture();await f.context.addCookies([{name:'v1_csrf',value:'replacement-session-csrf',url:base}]);const before=f.calls.filter(x=>x.method!=='GET').length;await f.page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(f.page.locator('#access')).toBeVisible();assert.equal(f.calls.filter(x=>x.method!=='GET').length,before);assert.equal(await f.page.locator('#profile-form [name=support_email]').inputValue(),'');results.push('same-user native session replacement fences before another mutation and clears private profile');await f.context.close();
 }
 {
 const f=await fixture();f.hold();await f.page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect.poll(()=>!!f.held()).toBe(true);
 const viewer={id:A,name:'Allowed Boutique A',role:'viewer',capabilities:['business.read','readiness.read','catalogue.read','analytics.read']};f.setSession(make([viewer]));
 // A separate real guarded request provides newer session authority while the older focus guard is held.
 await f.page.selectOption('#business-picker',A,{force:true});await expect(f.page.locator('#profile-form [name=name]')).toBeDisabled();f.held().release();
 await expect(f.page.locator('#business-picker option')).toHaveCount(1);await expect(f.page.locator('#team')).toBeHidden();assert.equal(await f.page.locator('#team-list').textContent(),'');assert.equal(await f.page.locator('#invite-link').inputValue(),'');assert.equal(await f.page.locator('#business-tools').getByText('Payment setup',{exact:true}).count(),0);results.push('older session response cannot revive revoked business options or owner team/payment controls');assert.deepEqual(f.errors,[]);await f.context.close();
 }
 await writeFile(new URL('native-workspace-controlled.json',out),JSON.stringify({checks:results.length,results,proof_scope:'Actual current HTML/JS in Chromium with controlled local HTTP; no database/provider acceptance'},null,2)+'\n');console.log(`PASS ${results.length} controlled native workspace privacy cases; no DB/provider.`);
}finally{await browser.close();}
