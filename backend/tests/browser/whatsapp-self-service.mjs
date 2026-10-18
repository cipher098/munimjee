/* Actual mounted main/native/0057. Every SDK/provider response is synthetic. */
import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import {mkdir,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium,expect}=await import(pathToFileURL('/Users/gothi/Documents/Codex/2026-10-10/help-me-understand-x20/work/munimjee-v1/frontend/storefront/node_modules/@playwright/test/index.mjs').href);
const base='https://127.0.0.1:8171',output=new URL('../../../artifacts/v1/whatsapp-self-service/mounted/',import.meta.url);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const nonce=process.env.WA_SETUP_FIXTURE_NONCE,errors=[],external=[];
let checks=0,sdkLoads=0,privatePosts=0,heldOldDelivered=null;
const sdk=`window.FB={init:function(v){window.__syntheticSDKConfig=v;},login:function(callback,options){window.__syntheticSDKLogin=options;window.__syntheticSDKCallback=callback;}};`;
const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1100}});
await context.route('**/*',async route=>{
  const url=route.request().url();
  if(url.startsWith(base+'/'))return route.continue();
  if(url==='https://connect.facebook.net/en_US/sdk.js'){
    sdkLoads++;return route.fulfill({status:200,contentType:'application/javascript',body:sdk});
  }
  external.push(new URL(url).origin);return route.abort();
});
const page=await context.newPage();page.setDefaultTimeout(12000);
page.on('pageerror',error=>errors.push(error.name));
async function session(){return(await page.request.get(base+'/api/v1/auth/session')).json();}
async function api(path,method='GET',data,fixture=false){
  const identity=await session();
  const response=await page.request.fetch(base+path,{method,data,headers:{Origin:base,
    'X-CSRF-Token':identity.csrf_token||'',...(fixture?{'X-Local-Fixture':nonce}:{})}});
  return {status:response.status(),data:await response.json()};
}
async function storage(){return page.evaluate(()=>Object.entries(sessionStorage).filter(([k])=>k.startsWith('munimjee.v1.whatsapp-setup:')).map(([,v])=>v).join(''));}
async function screenshot(name){await page.screenshot({path:new URL(name+'.png',output).pathname,fullPage:true,
  mask:[page.locator('#private-command'),page.locator('#registration-pin'),page.locator('#recipient-phone')]});}
async function signedWebhook(value){
  const raw=JSON.stringify({object:'whatsapp_business_account',entry:[{id:'456',changes:[{field:'messages',value}]}]});
  const signature='sha256='+createHmac('sha256','synthetic-matching-app-secret').update(raw).digest('hex');
  const response=await page.request.post(base+'/webhooks/whatsapp',{data:raw,headers:{'content-type':'application/json','X-Hub-Signature-256':signature}});
  assert.equal(response.status(),200,'Synthetic signed ingress must acknowledge canonical transaction');
}
try{
  for(let n=0;n<60;n++){
    try{await page.goto(base+'/v1');break;}catch(error){if(n===59)throw error;await new Promise(resolve=>setTimeout(resolve,100));}
  }
  const identified=await(await page.request.get(base+'/__wa_setup/identify')).json();
  assert.equal(identified.nonce,nonce);assert.equal(identified.actual_main_router,true);assert.equal(identified.synthetic_provider,true);checks++;
  const email=`wa-setup-${crypto.randomUUID()}@example.com`,password='synthetic-wa-owner-password';
  await page.locator('#access-form [name=business_name]').fill('Synthetic Indigo WhatsApp');
  await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel(/^Password/).fill(password);
  await page.getByRole('button',{name:'Create account',exact:true}).click();
  await page.getByRole('heading',{name:'Synthetic Indigo WhatsApp',exact:true}).waitFor();checks++;
  const identity=await session(),bid=identity.businesses[0].id,path=`/v1/businesses/${bid}/channels/whatsapp/setup`,endpoint=`/api/v1/businesses/${bid}/channels/whatsapp`;
  page.on('request',request=>{if(request.url().startsWith(base+endpoint)&&request.method()==='POST')privatePosts++;});
  await page.goto(base+path);await expect(page.locator('#business-name')).toHaveText('Synthetic Indigo WhatsApp');
  await expect(page.locator('#operator-gate')).toBeVisible();await expect(page.locator('#consent-fields')).toBeDisabled();
  assert.equal(sdkLoads,0);assert.equal((await page.request.get(base+path)).headers()['cache-control'],'no-store');checks++;
  await screenshot('desktop-default-off');
  assert.equal((await api(`/__wa_setup/${bid}/enable-synthetic`,'POST',{},true)).status,200);
  await page.getByRole('button',{name:'Refresh status',exact:true}).click();await expect(page.locator('#consent-fields')).toBeEnabled();checks++;

  // The first prepare commits, then its response is lost. Reload never invents a new key.
  let firstBody=null,replayBody=null,prepareWrites=0;
  page.on('request',request=>{if(request.url()===base+endpoint+'/signup'&&request.method()==='POST')prepareWrites++;});
  await page.route('**'+endpoint+'/signup',async route=>{firstBody=route.request().postData();const response=await route.fetch();assert.equal(response.status(),200);await route.abort();});
  await page.locator('#consent-reviewed').check();await page.getByRole('button',{name:'Prepare Meta signup',exact:true}).click();
  await expect(page.locator('#recovery')).toBeVisible();await expect(page.locator('#page-error')).not.toBeEmpty();assert.equal(prepareWrites,1);checks++;
  await page.unroute('**'+endpoint+'/signup');await page.reload();await expect(page.locator('#retry-action')).toBeVisible();
  assert.equal(prepareWrites,1);assert.equal(sdkLoads,0);checks++;
  await page.route('**'+endpoint+'/signup',async route=>{replayBody=route.request().postData();await route.continue();});
  await page.locator('#retry-action').click();await expect(page.locator('#open-meta')).toBeEnabled();
  assert.equal(replayBody,firstBody);assert.equal(prepareWrites,2);assert.equal(sdkLoads,1);checks++;
  const snapshot=await api(`/__wa_setup/${bid}/snapshot`,'POST',{},true);assert.equal(snapshot.data.attempts,1);checks++;
  const sdkConfig=await page.evaluate(()=>window.__syntheticSDKConfig);
  assert.equal(sdkConfig.appId,'123');assert.equal(sdkConfig.autoLogAppEvents,false);assert.equal(sdkConfig.xfbml,false);checks++;
  await page.getByRole('button',{name:'Open Meta signup',exact:true}).click();
  await page.evaluate(()=>{
    window.dispatchEvent(new MessageEvent('message',{origin:'https://www.facebook.com',data:JSON.stringify({type:'WA_EMBEDDED_SIGNUP',event:'FINISH',data:{waba_id:'456',phone_number_id:'12345',business_id:'789'}})}));
    window.__syntheticSDKCallback({authResponse:{code:'synthetic-one-use-code'}});
  });
  await expect(page.locator('#selection-section')).toBeVisible();await expect(page.locator('#account-choice')).toHaveValue('');
  assert.equal((await api(`/__wa_setup/${bid}/snapshot`,'POST',{},true)).data.operations.exchange,1);checks++;
  const choice=await page.locator('#account-choice option').nth(1).getAttribute('value');await page.locator('#account-choice').selectOption(choice);
  await page.locator('#registration-pin').fill('123456');await page.locator('#account-confirmed').check();
  let selectionWrites=0;page.on('request',request=>{if(request.url().endsWith('/select')&&request.method()==='POST')selectionWrites++;});
  await page.route('**'+endpoint+'/signup/*/select',async route=>{const response=await route.fetch();assert.equal(response.status(),200);await route.abort();});
  await page.getByRole('button',{name:'Register & save with automation paused',exact:true}).click();
  assert.equal(await page.locator('#registration-pin').evaluate(input=>input.value===''),true);await expect(page.locator('#recovery-message')).toContainText('PIN was erased');
  const afterSelection=await storage();assert.equal(afterSelection.includes('registration_pin'),false);assert.equal(afterSelection.includes('synthetic-one-use-code'),false);assert.equal(afterSelection.includes('signed_state'),false);checks++;
  await page.setViewportSize({width:390,height:844});await screenshot('mobile-unknown-setup');
  await page.unroute('**'+endpoint+'/signup/*/select');await page.reload();await expect(page.locator('#check-action')).toBeVisible();
  assert.equal(selectionWrites,1);await page.locator('#check-action').click();await expect(page.locator('#recovery')).toBeHidden();
  await expect(page.locator('#connection-status')).toHaveText('Saved with automation paused');
  const saved=await api(`/__wa_setup/${bid}/snapshot`,'POST',{},true);
  assert.equal(saved.data.operations.subscribe,1);assert.equal(saved.data.operations.register,1);assert.equal(saved.data.provider_sends,0);checks++;
  await page.setViewportSize({width:1440,height:1100});await screenshot('desktop-paused-account');

  await page.locator('#recipient-authorized').check();await page.getByRole('button',{name:'Create private recipient command',exact:true}).click();
  await expect(page.locator('#private-command')).not.toHaveValue('');
  const privateCommand=await page.locator('#private-command').inputValue();
  const storedChallenge=await storage();assert.equal(storedChallenge.includes(privateCommand),false);assert.equal(storedChallenge.includes('MUNIMJEE-WA-TEST:'),false);checks++;
  const journal=JSON.parse(storedChallenge),testId=journal.test.test_id;
  await signedWebhook({metadata:{phone_number_id:'12345'},messages:[{id:'synthetic-signed-inbound',from:'910000000001',timestamp:String(Math.floor(Date.now()/1000)),type:'text',text:{body:privateCommand}}]});
  await page.getByRole('button',{name:'Review received recipient',exact:true}).click();
  await expect(page.locator('#recipient-phone')).toHaveText('+910000000001');await expect(page.locator('#queue-test')).toBeEnabled();checks++;
  await page.locator('#recipient-confirmed').check();
  let originalQueue=null,replayedQueue=null,queueWrites=0;
  page.on('request',request=>{if(request.url()===base+endpoint+`/tests/${testId}/send`&&request.method()==='POST')queueWrites++;});
  await page.route('**'+endpoint+`/tests/${testId}/send`,async route=>{originalQueue=route.request().postData();const response=await route.fetch();assert.equal(response.status(),200);await route.abort();});
  await page.getByRole('button',{name:'Queue one fixed test reply',exact:true}).click();await expect(page.locator('#recovery-message')).toContainText('may already be queued');
  assert.equal((await api(`/__wa_setup/${bid}/snapshot`,'POST',{},true)).data.provider_sends,0);checks++;
  await page.unroute('**'+endpoint+`/tests/${testId}/send`);await page.reload();await expect(page.locator('#retry-action')).toBeVisible();
  assert.equal(queueWrites,1);checks++;
  await page.route('**'+endpoint+`/tests/${testId}/send`,async route=>{replayedQueue=route.request().postData();await route.continue();});
  await page.locator('#retry-action').click();await expect(page.locator('#test-status')).toContainText('One fixed reply is queued');
  assert.equal(replayedQueue,originalQueue);assert.equal(queueWrites,2);
  assert.equal((await api(`/__wa_setup/${bid}/snapshot`,'POST',{},true)).data.authorizations,1);checks++;
  assert.equal((await api(`/__wa_setup/${bid}/deliver/${testId}`,'POST',{},true)).status,200);
  await page.getByRole('button',{name:'Check test result',exact:true}).click();await expect(page.locator('#test-status')).toContainText('Delivery is not confirmed');
  assert.equal((await api(`/__wa_setup/${bid}/snapshot`,'POST',{},true)).data.provider_sends,1);checks++;
  await api(`/__wa_setup/${bid}/deliver/${testId}`,'POST',{},true);
  assert.equal((await api(`/__wa_setup/${bid}/snapshot`,'POST',{},true)).data.provider_sends,1);checks++;
  const observed=await api(endpoint+`/tests/${testId}`),mid='synthetic-outbound-'+observed.data.message_id;
  await signedWebhook({metadata:{phone_number_id:'12345'},statuses:[{id:mid,status:'delivered',recipient_id:'910000000001',timestamp:String(Math.floor(Date.now()/1000))}]});
  await page.getByRole('button',{name:'Check test result',exact:true}).click();await expect(page.locator('#test-status')).toContainText('synthetic test evidence');
  assert.equal((await api(endpoint+`/tests/${testId}`)).data.delivery_confirmed,false);checks++;
  const storedFinal=await storage();assert.equal(storedFinal.includes(privateCommand),false);assert.equal(storedFinal.includes('910000000001'),false);checks++;
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await screenshot('mobile-synthetic-result');checks++;
  await page.route('**'+endpoint+'/self-service',route=>route.fulfill({status:503,contentType:'application/json',body:'{"detail":"Synthetic read unavailable"}'}));
  await page.getByRole('button',{name:'Refresh status',exact:true}).click();await expect(page.locator('#page-error')).not.toBeEmpty();await expect(page.locator('#workspace')).toBeHidden();
  assert.equal(await page.locator('#recipient-phone').textContent(),'');await screenshot('mobile-read-error');checks++;
  await page.unroute('**'+endpoint+'/self-service');await page.getByRole('button',{name:'Refresh status',exact:true}).click();await expect(page.locator('#workspace')).toBeVisible();

  // Hold an old valid private GET, then replace this same user's actual native
  // session. Controlled input canaries test physical erasure, not screenshot masks.
  let releaseOld,oldEntered,oldFinished;const oldWait=new Promise(resolve=>{releaseOld=resolve;}),oldStarted=new Promise(resolve=>{oldEntered=resolve;}),oldDone=new Promise(resolve=>{oldFinished=resolve;});
  await page.route('**'+endpoint+`/tests/${testId}`,async route=>{
    const response=await route.fetch();oldEntered();await oldWait;
    try{await route.fulfill({response});heldOldDelivered=true;}catch(_){heldOldDelivered=false;}
    finally{oldFinished();} // Ended AbortController may cancel, rather than deliver, this GET.
  });
  await page.getByRole('button',{name:'Check test result',exact:true}).click();await oldStarted;
  await page.evaluate(value=>{document.querySelector('#private-command').value=value;document.querySelector('#registration-pin').value='123456';},privateCommand);
  const postsBeforeReplacement=privatePosts;
  const replaced=await page.request.post(base+'/api/v1/auth/login',{data:{email,password},headers:{Origin:base}});
  assert.equal(replaced.status(),200);
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#access-needed')).toBeVisible();
  const replacementSecretsEmpty=await page.evaluate(()=>document.querySelector('#private-command').value===''&&document.querySelector('#registration-pin').value==='');
  assert.equal(replacementSecretsEmpty,true);await expect(page.locator('#logout')).toBeHidden();checks++;
  releaseOld();await oldDone;await page.unroute('**'+endpoint+`/tests/${testId}`);
  await page.evaluate(()=>{for(const id of ['consent-form','send-form'])document.getElementById(id).dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));});
  await page.waitForTimeout(100);assert.equal(privatePosts,postsBeforeReplacement);
  assert.equal(await page.locator('#test-status').textContent(),'');await expect(page.locator('#workspace')).toBeHidden();checks++;
  await screenshot('mobile-session-replaced');
  await page.reload();await expect(page.locator('#workspace')).toBeVisible();
  await api(`/__wa_setup/${bid}/viewer`,'POST',{},true);await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await expect(page.locator('#workspace')).toBeHidden();await expect(page.locator('#logout')).toBeHidden();assert.equal(await page.locator('#recipient-phone').textContent(),'');checks++;
  await page.reload();await expect(page.locator('#view-only')).toBeVisible();await expect(page.locator('#owner-tools')).toBeHidden();await screenshot('mobile-viewer');checks++;
  assert.equal((await api(endpoint+'/tests','POST',{idempotency_key:crypto.randomUUID(),expected_connection_version:1,recipient_authorized:true})).status,403);checks++;
  await page.getByRole('button',{name:'Sign out',exact:true}).click();await expect(page.locator('#access-needed')).toBeVisible();
  for(const selector of ['#connection-status','#recipient-phone','#signup-status','#test-status','#recovery-message'])assert.equal(await page.locator(selector).textContent(),'');
  const endedSecretsEmpty=await page.evaluate(()=>document.querySelector('#private-command').value===''&&document.querySelector('#registration-pin').value==='');
  assert.equal(endedSecretsEmpty,true);
  await expect(page.locator('#logout')).toBeHidden();await screenshot('mobile-session-ended');checks++;
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);checks++;
  await writeFile(new URL('result.json',output),JSON.stringify({checks,actual_main_router:true,synthetic_provider:true,synthetic_sdk:true,
    synthetic_sdk_requests_fulfilled:sdkLoads,external_network_attempts:external.length,
    held_old_get_handler_finished:true,held_old_get_route_fulfilled:heldOldDelivered,ended_abort_may_cancel_held_get:true,
    actual_meta_sdk_network_requests:0,page_errors:errors.length,real_meta_consent:false,live_delivery_proved:false},null,2)+'\n');
  console.log(`PASS ${checks} actual-mounted native/0057 browser checks; SDK/provider synthetic, real Meta/delivery not proved`);
}finally{await browser.close();}
