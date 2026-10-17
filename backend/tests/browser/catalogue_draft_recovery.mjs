/* Adversarial browser-session recovery against real native/catalogue APIs.
   Transport corruption and storage faults below are explicit browser boundaries. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const sha=value=>createHash('sha256').update(value).digest('hex');
export async function recoveryChecks({base,page,owner,context,email,password,bid,session,savedIntent,intentKey,expect}) {
 let checks=0,posts=0;
 const cat=`/api/v1/businesses/${bid}/catalogue`,workspace=`/v1/businesses/${bid}/catalogue`,prefix='munimjee.v1.catalogue-draft:';
 const postListener=request=>{if(request.method()==='POST'&&request.url()===base+cat+'/products')posts++;};page.on('request',postListener);
 const write=async(raw,key=intentKey)=>page.evaluate(({raw,key})=>sessionStorage.setItem(key,raw),{raw,key});
 const read=async(key=intentKey)=>page.evaluate(key=>sessionStorage.getItem(key),key);
 const clear=async()=>page.evaluate(key=>sessionStorage.removeItem(key),intentKey);
 const reload=async()=>{await page.goto(base+workspace);await page.locator('#workspace').waitFor({state:'visible'});};
 const api=async(path,method='GET',body)=>{
  const response=await page.request.fetch(base+path,{method,data:body,headers:{Origin:base,'X-CSRF-Token':(await(await page.request.get(base+'/api/v1/auth/session')).json()).csrf_token||''}});
  return {status:response.status(),data:await response.json()};
 };
 const fresh=async()=>{const current=(await api('/api/v1/auth/session')).data;const envelope=JSON.parse(savedIntent);envelope.session_fingerprint=sha(current.csrf_token);envelope.created_at=new Date().toISOString();return envelope;};
 // Corruption/expiry must block new commands; never silently mint a new key.
 for(const kind of ['malformed','changed','expired']){
  let raw='{broken';if(kind!=='malformed'){const command=await fresh();if(kind==='changed')command.body.name='Unexpected local change';else command.created_at=new Date(Date.now()-8*86400000).toISOString();raw=JSON.stringify(command);}
  await write(raw);const before=posts;await reload();await expect(page.locator('#draft-recovery')).toBeVisible();await expect(page.locator('#draft-retry')).toBeDisabled();await expect(page.locator('#draft-form [name=name]')).toBeDisabled();assert.equal(await read(),raw);assert.equal(posts,before);checks+=2;await clear();
 }
 // A valid saved command is immutable even if script changes the hidden form.
 const malformed=await fresh();malformed.body={...malformed.body,name:'Recovery response dress',idempotency_key:crypto.randomUUID()};malformed.body_digest=sha(JSON.stringify(malformed.body));await write(JSON.stringify(malformed));await reload();
 const beforeMalformed=(await api(cat+'/products')).data.total,beforePosts=posts,sent=[];
 await page.evaluate(()=>{document.querySelector('#draft-form [name=name]').value='Changed after unknown save';document.getElementById('draft-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));});
 await expect(page.locator('#draft-error')).toContainText('Resolve the saved draft recovery');assert.equal(posts,beforePosts);checks++;
 let corrupt=true;const pattern='**'+cat+'/products';
 await page.route(pattern,async route=>{
  if(route.request().method()!=='POST')return route.continue();sent.push(route.request().postDataJSON());const response=await route.fetch();
  if(corrupt){assert.equal(response.status(),201);corrupt=false;return route.fulfill({response,contentType:'application/json',body:'{}'});}return route.fulfill({response});
 });
 await page.getByRole('button',{name:'Retry saved draft',exact:true}).click();await expect(page.locator('#draft-recovery-error')).toContainText('did not confirm a valid draft');assert.ok(await read());
 await reload();assert.equal(sent.length,1);await page.getByRole('button',{name:'Retry saved draft',exact:true}).click();await expect(page.locator('#detail-heading')).toHaveText('Recovery response dress');
 assert.equal(sent.length,2);assert.deepEqual(sent[0],sent[1]);assert.equal(sent[0].name,malformed.body.name);assert.equal((await api(cat+'/products')).data.total,beforeMalformed+1);assert.equal(await read(),null);checks+=5;await page.unroute(pattern);
 // Failure to persist before sending must send no POST at all.
 const restricted=await owner.newPage();let restrictedPosts=0;restricted.on('request',r=>{if(r.method()==='POST'&&r.url()===base+cat+'/products')restrictedPosts++;});
 await restricted.addInitScript(({prefix})=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(String(key).startsWith(prefix))throw new DOMException('Synthetic storage denial','QuotaExceededError');return original.call(this,key,value);};},{prefix});
 await restricted.goto(base+workspace);await restricted.locator('#workspace').waitFor({state:'visible'});await restricted.getByRole('link',{name:'Add product',exact:true}).click();
 await restricted.locator('#draft-form [name=name]').fill('Must never be sent');await restricted.locator('#draft-form [name=price]').fill('123.45');await restricted.locator('#draft-reviewed').check();await restricted.getByRole('button',{name:'Save reviewed draft',exact:true}).click();
 await expect(restricted.locator('#draft-recovery-message')).toContainText('could not preserve');assert.equal(restrictedPosts,0);checks++;await restricted.close();
 // API-provided public link only: validate destination and keep feature-off hidden.
 const settings=(await api(cat+'/storefront')).data;let supplied=base+'/stores/'+settings.slug;
 await page.route('**'+cat+'/storefront',async route=>{if(route.request().method()!=='GET')return route.continue();const response=await route.fetch(),data=await response.json();return route.fulfill({response,json:{...data,public_storefront_url:supplied}});});
 await reload();await expect(page.getByRole('link',{name:'Open storefront',exact:true})).toHaveAttribute('href',supplied);checks++;
 for(const bad of ['javascript:alert(1)','https://user:password@example.invalid/stores/'+settings.slug,'https://example.invalid/other','https://example.invalid/stores/'+settings.slug+'?private=1']){supplied=bad;await reload();assert.equal(await page.locator('#public-storefront').isHidden(),true);checks++;}
 await page.unroute('**'+cat+'/storefront');
 // Same user gets a different native session: old recovery is withheld before POST.
 await write(JSON.stringify(await fresh()));await reload();const sameUserBefore=posts;
 const replacement=await page.request.post(base+'/api/v1/auth/login',{headers:{Origin:base},data:{email,password}});assert.equal(replacement.status(),200);
 await page.getByRole('button',{name:'Retry saved draft',exact:true}).click();await expect(page.locator('#workspace')).toBeHidden();assert.equal(await read(),null);assert.equal(await page.locator('#draft-recovery-facts').textContent(),'');assert.equal(posts,sameUserBefore);checks+=2;
 await reload();
 // Create a second real business and grant this same owner a membership there.
 const other=await context(),otherPage=await other.newPage();const otherEmail=`recovery-other-${crypto.randomUUID()}@example.com`;
 const signed=await otherPage.request.post(base+'/api/v1/auth/signup',{headers:{Origin:base},data:{email:otherEmail,password,business_name:'Other recovery business'}});assert.equal(signed.status(),201);const foreignSession=await signed.json(),foreignBid=foreignSession.businesses[0].id;
 const invitation=await otherPage.request.post(base+`/api/v1/businesses/${foreignBid}/invitations`,{headers:{Origin:base,'X-CSRF-Token':foreignSession.csrf_token},data:{email,role:'manager'}});assert.equal(invitation.status(),201);
 const accepted=await page.request.post(base+'/api/v1/auth/invitations/accept',{headers:{Origin:base},data:{email,password,token:(await invitation.json()).invitation_url.split('=')[1]}});assert.equal(accepted.status(),200);
 await reload();const scoped=JSON.stringify(await fresh());await write(scoped);const foreignWorkspace=base+`/v1/businesses/${foreignBid}/catalogue`;
 await page.goto(foreignWorkspace);await page.locator('#workspace').waitFor({state:'visible'});assert.equal(await page.locator('#draft-recovery').isHidden(),true);assert.equal(await page.locator('#draft-recovery-facts').textContent(),'');assert.equal(await read(),scoped);checks++;
 const foreignKey=prefix+session.user_id+':'+foreignBid;await write(scoped,foreignKey);await page.reload();await page.locator('#workspace').waitFor({state:'visible'});await expect(page.locator('#draft-recovery-message')).toContainText('different sign-in or business');assert.equal(await read(foreignKey),null);assert.equal(await page.locator('#draft-recovery-facts').textContent(),'');checks++;
 // An expired/revoked browser session clears local recovery on the 401 path.
 await reload();const before401=posts;const now=(await api('/api/v1/auth/session')).data;assert.equal((await page.request.post(base+'/api/v1/auth/logout',{headers:{Origin:base,'X-CSRF-Token':now.csrf_token}})).status(),200);
 await page.getByRole('button',{name:'Retry saved draft',exact:true}).click();await expect(page.locator('#workspace')).toBeHidden();assert.equal(await read(),null);assert.equal(await page.locator('#draft-recovery-facts').textContent(),'');assert.equal(posts,before401);checks++;
 // A different valid user in the same browser cannot reuse the previous command.
 assert.equal((await page.request.post(base+'/api/v1/auth/login',{headers:{Origin:base},data:{email,password}})).status(),200);await reload();await write(JSON.stringify(await fresh()));await reload();const beforeForeignUser=posts;
 assert.equal((await page.request.post(base+'/api/v1/auth/login',{headers:{Origin:base},data:{email:otherEmail,password}})).status(),200);
 await page.getByRole('button',{name:'Retry saved draft',exact:true}).click();await expect(page.locator('#workspace')).toBeHidden();assert.equal(await read(),null);assert.equal(await page.locator('#draft-recovery-facts').textContent(),'');assert.equal(posts,beforeForeignUser);checks++;
 await other.close();page.off('request',postListener);return checks;
}
