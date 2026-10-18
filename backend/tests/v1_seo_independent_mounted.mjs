// Actual mounted HTTP only. No browser/provider/domain acceptance is implied.
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {writeFile, mkdir} from 'node:fs/promises';

const port = process.env.MUNIMJEE_SEO_QA_PORT;
assert.match(port ?? '', /^[1-9][0-9]{3,4}$/);
assert(Number(port) >= 1024 && Number(port) <= 65535);
const origin = `http://127.0.0.1:${port}`;
const checks = [];
let cookies = '';
let csrf = '';
function check(name, truth) { assert(truth, name); checks.push(name); }
async function request(path, {method = 'GET', body, headers = {}} = {}) {
  assert(path.startsWith('/') && !path.startsWith('//') && !path.includes('\\'));
  const response = await fetch(origin + path, {method, redirect: 'manual', signal: AbortSignal.timeout(5000),
    headers: {Origin: origin, ...(cookies ? {Cookie: cookies} : {}),
      ...(csrf ? {'X-CSRF-Token': csrf} : {}), ...(body ? {'Content-Type': 'application/json'} : {}), ...headers},
    ...(body ? {body: JSON.stringify(body)} : {})});
  const set = response.headers.getSetCookie();
  if (set.length) {
    const existing = new Map(cookies.split('; ').filter(Boolean).map(x => x.split(/=(.*)/s).slice(0, 2)));
    for (const value of set) { const [name, val] = value.split(';')[0].split(/=(.*)/s); existing.set(name, val); }
    cookies = [...existing].map(([name, val]) => `${name}=${val}`).join('; ');
    csrf = existing.get('v1_csrf') ?? '';
  }
  return response;
}
async function json(path, method, body, status) {
  const response = await request(path, {method, body});
  check(`${method} ${path.split('/').slice(-1)[0]} status ${status}`, response.status === status);
  return response.json();
}
async function seed(slug, activate = true) {
  const user = await json('/api/v1/auth/signup', 'POST', {email: `${randomUUID()}@example.com`,
    password: 'synthetic-mounted-qa-password', business_name: 'Independent SEO synthetic'}, 201);
  const business = user.businesses[0].id;
  const prefix = `/api/v1/businesses/${business}/catalogue`;
  const store = {name: 'Independent SEO synthetic', slug, description: 'Synthetic only', currency: 'INR',
    shipping_fee: 0, cod_enabled: true, published: true, shipping_policy: 'Synthetic policy', return_policy: 'Synthetic policy'};
  await json(prefix + '/storefront', 'PUT', store, 200);
  const draft = await json(prefix + '/products', 'POST', {idempotency_key: randomUUID(), seller_reviewed: true,
    name: 'Independent QA dress', description: 'Synthetic catalogue facts', photo_urls: [],
    skus: [{options: {Size: 'M'}, price_minor: 12300, currency: 'INR', stock_available: 3, active: true}]}, 201);
  if (activate) await json(`${prefix}/products/${draft.product.product_id}/activate`, 'POST', {
    seller_reviewed: true, expected_mapping_revision: draft.mapping_revision,
    expected_legacy_fingerprint: draft.legacy_fingerprint}, 200);
  await json(prefix + '/checkout-policy', 'PUT', {checkout_enabled: true}, 200);
  return {prefix, store, product: draft.product.product_id, sku: draft.skus[0].sku_id};
}

try {
  // The lease-holding parent has already received its child's bound marker.
  check('actual main listener ready', (await request('/health')).ok);
  const foreign = await seed('qa-seo-foreign');
  const first = await seed('qa-seo-tara');
  const draft = await json(first.prefix + '/products', 'POST', {idempotency_key: randomUUID(), seller_reviewed: true,
    name: 'Private unactivated draft', description: 'Synthetic private draft', photo_urls: [],
    skus: [{options: {Size: 'L'}, price_minor: 1, currency: 'INR', stock_available: 1, active: true}]}, 201);
  const index = await request('/sitemap.xml', {headers: {Host: 'attacker.example.test', 'X-Forwarded-Host': 'attacker.example.test'}});
  const indexText = await index.text();
  check('index bounded canonical origins', index.status === 200 && indexText.includes(origin + '/sitemap-store-qa-seo-tara.xml') && !indexText.includes('attacker'));
  const sitemap = await request('/sitemap-store-qa-seo-tara.xml');
  const xml = await sitemap.text();
  check('sitemap contains current native product', sitemap.status === 200 && xml.includes(first.product));
  check('sitemap excludes foreign and draft', !xml.includes(foreign.product) && !xml.includes(draft.product.product_id));
  check('sitemap root scope and namespace', xml.includes('http://www.sitemaps.org/schemas/sitemap/0.9') && xml.includes(origin + '/stores/qa-seo-tara</loc>'));
  const redirect = await request('/legacy-qa-tara');
  check('reviewed synthetic redirect', redirect.status === 308 && redirect.headers.get('location') === origin + '/stores/qa-seo-tara');
  for (const path of ['/legacy-qa-tara?token=synthetic', '/%6cegacy-qa-tara', '/legacy-qa-tara/']) {
    const refused = await request(path);
    check('exact path/query refusal ' + path, refused.status === 404 && !refused.headers.has('location'));
  }
  const placed = await json('/api/v1/storefronts/qa-seo-tara/checkout', 'POST', {idempotency_key: randomUUID(),
    customer: {name: 'Synthetic buyer', phone: '9876543210', email: null},
    address: {line1: 'Synthetic street', line2: '', city: 'Bengaluru', state: 'Karnataka', postal_code: '560001', country: 'IN'},
    items: [{sku_id: first.sku, quantity: 1}], note: '', payment_method: 'cod', whatsapp_updates_opt_in: false}, 201);
  await json(first.prefix + '/storefront', 'PUT', {...first.store, published: false}, 200);
  check('revoked sitemap disappears', (await request('/sitemap-store-qa-seo-tara.xml')).status === 404);
  check('revoked redirect disappears', (await request('/legacy-qa-tara')).status === 404);
  const orderPath = `/api/v1/storefronts/qa-seo-tara/orders/${placed.id}`;
  check('private order still needs capability', (await request(orderPath)).status === 404);
  check('old capability works after unpublish', (await request(orderPath, {headers: {Authorization: 'Bearer ' + placed.access_token}})).status === 200);
  const shell = await request(`/stores/qa-seo-tara/orders/${placed.id}`);
  const shellText = await shell.text();
  check('order shell remains private and usable', shell.status === 200 && shell.headers.get('x-robots-tag') === 'noindex, nofollow' && !shellText.includes(placed.access_token));
  const after = await (await request('/sitemap.xml')).text();
  check('index revocation preserves foreign tenant', !after.includes('/sitemap-store-qa-seo-tara.xml') && after.includes('/sitemap-store-qa-seo-foreign.xml'));
  await mkdir('artifacts/v1/seo-independent-qa', {recursive: true});
  await writeFile('artifacts/v1/seo-independent-qa/mounted-actual.json', JSON.stringify({
    evidence: 'actual migrated main app HTTP', synthetic: true, checks, passed: true,
    gates: ['real seller URL inventory', 'provider/domain authority', 'physical device', 'migration reconciliation', 'rollback rehearsal']}, null, 2) + '\n');
  console.log(`Mounted actual-main HTTP checks passed: ${checks.length}`);
} catch (error) {
  console.error('Mounted SEO QA failed: ' + (error instanceof assert.AssertionError ? error.message : error?.name ?? 'unknown'));
  process.exitCode = 1;
}
