/* Real API/browser checks. No mocked auth, profile, invitation or status DTOs. */
import {chromium, expect} from '../../../frontend/storefront/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const base = 'http://127.0.0.1:8012';
const output = new URL('../../../artifacts/v1/auth-wave2/', import.meta.url);
await mkdir(output, {recursive:true});
const browser = await chromium.launch({headless:true});
let checks = 0;
async function context(options={}) {
  const c = await browser.newContext(options);
  await c.route('**/*', route => route.request().url().startsWith(base + '/') ? route.continue() : route.abort());
  return c;
}
async function open(page) {
  for(let attempt=0;attempt<40;attempt++) {
    try {await page.goto(base+'/v1');return;} catch(e) {if(attempt===39)throw e; await new Promise(r=>setTimeout(r,250));}
  }
}
const password='synthetic-browser-password';
async function signup(page, label) {
  await open(page);
  await page.locator('#access-form [name=business_name]').fill(label);
  const email = `browser-${crypto.randomUUID()}@example.com`;
  await page.getByLabel('Email',{exact:true}).fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole('button',{name:'Create account',exact:true}).click();
  await page.getByRole('heading',{name:label,exact:true}).waitFor();
  await expect(page.locator('#setup-progress')).toHaveText('1 of 5 ready');checks++;
  return email;
}
try {
  const c=await context({viewport:{width:1365,height:1000}}), page=await c.newPage();
  page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const email=await signup(page,'Synthetic Atelier');
  await page.locator('#profile-form [name=name]').fill('Confirmed Atelier');
  await page.getByLabel('Support email').fill('support@example.com');
  await page.getByRole('button',{name:'Save business details'}).click();
  await page.locator('#profile-status').filter({hasText:'Business details saved.'}).waitFor();
  await expect(page.locator('#setup-progress')).toHaveText('2 of 5 ready');checks++;
  assert.match(await page.locator('#checklist').textContent(),/Approval pending/);checks++;
  await page.screenshot({path:new URL('desktop-profile.png',output).pathname,fullPage:true});
  const session=await (await page.request.get(base+'/api/v1/auth/session')).json();
  const bid=session.businesses[0].id;
  const wrong=await page.request.put(base+`/api/v1/businesses/${bid}/profile`,{headers:{Origin:base,'X-CSRF-Token':'wrong'},data:{expected_version:1,name:'Forged',business_type:'boutique',country:'IN'}});
  assert.equal(wrong.status(),403);checks++;
  const changed=await page.request.put(base+`/api/v1/businesses/${bid}/profile`,{headers:{Origin:base,'X-CSRF-Token':session.csrf_token},data:{expected_version:1,name:'Concurrent Update',business_type:'boutique',country:'IN'}});
  assert.equal(changed.status(),200);
  await page.getByRole('button',{name:'Save business details'}).click();
  await page.getByText('Business details changed; refresh before saving',{exact:true}).waitFor();checks++;
  await page.reload();await page.getByRole('heading',{name:'Concurrent Update',exact:true}).waitFor();
  const guestEmail=`viewer-${crypto.randomUUID()}@example.com`;
  await page.locator('#invite-form [name=email]').fill(guestEmail);
  await page.locator('#invite-form [name=role]').selectOption('viewer');
  await page.getByRole('button',{name:'Create invitation link'}).click();
  await page.locator('#invite-result').waitFor({state:'visible'});
  const inviteURL=await page.locator('#invite-link').inputValue();
  const guest=await context({viewport:{width:390,height:844}}), guestPage=await guest.newPage();
  await guestPage.goto(inviteURL);
  await guestPage.getByLabel('Email',{exact:true}).fill(guestEmail);
  await guestPage.getByLabel(/^Password/).fill(password);
  await guestPage.getByRole('button',{name:'Accept invitation'}).click();
  await guestPage.getByRole('heading',{name:'Concurrent Update',exact:true}).waitFor();
  assert.equal(await guestPage.locator('#profile-save').isDisabled(),true);
  assert.equal(await guestPage.locator('#team').isHidden(),true);checks++;
  assert.equal(await guestPage.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++;
  await guestPage.screenshot({path:new URL('mobile-viewer.png',output).pathname,fullPage:true});
  await guest.close();
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await page.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();
  await page.getByLabel('Email',{exact:true}).fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'Concurrent Update',exact:true}).waitFor();
  await expect(page.locator('#setup-progress')).toHaveText('2 of 5 ready');checks++;
  await page.getByRole('button',{name:'Sign out on all devices'}).click();
  await page.getByRole('heading',{name:'Welcome back',exact:true}).waitFor();checks++;
  await c.close();
  const mobile=await context({viewport:{width:390,height:844}}), mp=await mobile.newPage();
  await signup(mp,'Mobile Boutique');
  await mp.locator('#profile-form [name=name]').fill('Mobile Confirmed');
  await mp.getByRole('button',{name:'Save business details'}).click();
  await mp.locator('#profile-status').filter({hasText:'Business details saved.'}).waitFor();
  assert.equal(await mp.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++;
  await mp.screenshot({path:new URL('mobile-owner.png',output).pathname,fullPage:true});
  await mobile.close();assert.deepEqual(errors,[]);checks++;
  console.log(`PASS ${checks} real Chromium checks: desktop/mobile signup, saved/resumed profile, conflict, CSRF, invitation role, logout/all. No provider requests.`);
} finally {await browser.close();}
