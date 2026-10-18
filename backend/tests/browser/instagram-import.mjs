/* Actual app/native/PG + real adapter with synthetic Graph/CDN transport only. */
import assert from 'node:assert/strict';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const {chromium,expect}=await import(process.env.PLAYWRIGHT_MODULE?pathToFileURL(process.env.PLAYWRIGHT_MODULE).href:new URL('../../../frontend/storefront/node_modules/@playwright/test/index.mjs',import.meta.url).href);
const base='http://127.0.0.1:8158',output=new URL('../../../artifacts/v1/instagram-owned-integration/',import.meta.url);
await mkdir(output,{recursive:true});const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1050}}),external=[],errors=[];
await context.route('**/*',route=>route.request().url().startsWith(base+'/')?route.continue():(external.push(route.request().url()),route.abort()));
const page=await context.newPage();page.setDefaultTimeout(12000);page.on('pageerror',error=>errors.push(error.message));let checks=0;
try{
 for(let n=0;n<60;n++){try{await page.goto(base+'/v1');break;}catch(e){if(n===59)throw e;await new Promise(r=>setTimeout(r,200));}}
 await page.locator('#access-form [name=business_name]').fill('Indigo source review');await page.getByLabel('Email',{exact:true}).fill(`original-${crypto.randomUUID()}@example.com`);await page.getByLabel(/^Password/).fill('synthetic-original-password');await page.getByRole('button',{name:'Create account',exact:true}).click();await page.getByRole('heading',{name:'Indigo source review',exact:true}).waitFor();
 const session=await(await page.request.get(base+'/api/v1/auth/session')).json(),bid=session.businesses[0].id,root=`/api/v1/businesses/${bid}/imports`,headers={Origin:base,'X-CSRF-Token':session.csrf_token};checks++;
 await page.goto(base+`/v1/businesses/${bid}/imports`);await expect(page.locator('#workspace')).toBeVisible();await expect(page.locator('#instagram-form')).toBeHidden();await expect(page.locator('#instagram-status')).toContainText('Connect a current');checks+=2;
 assert.equal((await page.request.post(base+`/__owned-test/businesses/${bid}/connect`,{headers})).status(),200);await page.reload();await expect(page.locator('#instagram-form')).toBeVisible();checks+=2;
 let dropped=false;const bodies=[];
 await page.route('**'+root+'/jobs',async route=>{if(route.request().method()!=='POST')return route.continue();bodies.push(route.request().postDataJSON());if(!dropped){dropped=true;const response=await route.fetch();assert.equal(response.status(),202);await route.abort('failed');}else await route.continue();});
 await page.locator('#instagram-media').fill('180000000000071');await page.locator('#instagram-consent').check();await page.getByRole('button',{name:'Retrieve original for review',exact:true}).click();await expect(page.locator('#recovery')).toBeVisible();await expect(page.locator('#recovery-error')).not.toBeEmpty();checks++;
 await page.reload();await expect(page.locator('#recovery-facts')).toContainText('Retrieve owned Instagram original');assert.equal(bodies.length,1);await page.locator('#retry-command').click();await expect(page.locator('#recovery')).toBeHidden();assert.deepEqual(bodies[0],bodies[1]);checks+=3;
 const jobs=await(await page.request.get(base+root+'/jobs')).json();assert.equal(jobs.length,1);assert.equal(JSON.stringify(jobs).includes('credential_hash'),false);assert.equal(JSON.stringify(jobs).includes('synthetic-only'),false);checks+=3;
 const run=await page.request.post(base+`/__owned-test/businesses/${bid}/jobs/${jobs[0].job_id}/run`,{headers});assert.equal(run.status(),200);assert.equal((await run.json()).processed,true);checks+=2;
 await page.locator('#refresh').click();await expect(page.locator('.candidate-select')).toHaveCount(1);await page.locator('.candidate-select').click();await expect(page.locator('#candidate-originals a')).toHaveCount(1);await expect(page.locator('#fact-stock')).toHaveValue('');await expect(page.locator('#fact-price')).toHaveValue('');await expect(page.locator('#fact-title')).toHaveValue('');checks+=4;
 const candidates=(await(await page.request.get(base+root+'/candidates')).json()).items;assert.equal(candidates[0].candidate.state,'review_required');assert.equal(candidates[0].candidate.extracted.stock,null);assert.equal(JSON.stringify(candidates).includes('publish now'),false);checks+=3;
 const manifest=await(await page.request.get(base+root+'/candidates/'+candidates[0].candidate_id+'/originals')).json();assert.equal(manifest.items.length,1);checks++;
 const original=await page.request.get(base+root+'/candidates/'+candidates[0].candidate_id+'/originals/'+manifest.items[0].asset_id);assert.equal(original.status(),200);assert.match(original.headers()['cache-control'],/no-store/);assert.match(original.headers()['content-disposition'],/^attachment/);assert.equal(createHash('sha256').update(await original.body()).digest('hex'),manifest.items[0].sha256);checks+=4;
 await page.screenshot({path:new URL('desktop-private-original.png',output).pathname,fullPage:true});await page.setViewportSize({width:390,height:844});await page.locator('#originals-heading').scrollIntoViewIfNeeded();await page.screenshot({path:new URL('mobile-original-review.png',output).pathname});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks++;
 const status=await(await page.request.get(base+'/__owned-test/status')).json();assert.deepEqual(status.synthetic_requests,{graph:2,asset:1});checks++;
 assert.equal((await page.request.post(base+'/api/v1/auth/logout',{headers})).status(),200);await page.bringToFront();await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await expect(page.locator('#workspace')).toBeHidden();assert.equal(await page.locator('#candidate-originals a').count(),0);await expect(page.locator('#candidate-evidence')).toBeEmpty();checks+=3;await page.screenshot({path:new URL('mobile-session-ended.png',output).pathname});
 assert.deepEqual(external,[]);assert.deepEqual(errors,[]);checks+=2;
 await writeFile(new URL('browser-results.json',output),JSON.stringify({checks,external,errors,scope:'Actual app.main/PG0053/native browser, real owned adapter with explicitly synthetic Graph/CDN transport; no real provider/API permission evidence.'},null,2)+'\n');console.log(`${checks} actual mounted owned-original checks passed`);
}finally{await browser.close();}
