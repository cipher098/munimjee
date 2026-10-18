/* Exact local intent and acknowledgement checks. No transport or authority. */
export const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
export const HASH = /^[a-f0-9]{64}$/;
const operations = new Set(['rule_create', 'rule_update', 'rule_disable', 'comment_close', 'enquiry_close']);
export function stable(value) {
  const ordered = input => Array.isArray(input) ? input.map(ordered) : input && typeof input === 'object' ? Object.fromEntries(Object.keys(input).sort().map(key => [key, ordered(input[key])])) : input;
  return JSON.stringify(ordered(value)).replace(/[\u007f-\uffff]/g, char => '\\u' + char.charCodeAt(0).toString(16).padStart(4, '0'));
}
export async function digest(value) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(stable(value))))].map(value => value.toString(16).padStart(2, '0')).join('');
}
function text(value, maximum, minimum = 0) { return typeof value === 'string' && value.length <= maximum && value.trim().length >= minimum && !/[\u0000\ud800-\udfff]/u.test(value); }
function keys(value, expected) { return value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === expected.split(',').sort().join(','); }
export function validFacts(value) {
  return keys(value, 'name,enabled,media_id,keywords,product_id,private_reply,public_reply') && text(value.name, 100, 1) && typeof value.enabled === 'boolean' && /^\d{1,100}$/.test(value.media_id) && UUID.test(value.product_id) && Array.isArray(value.keywords) && value.keywords.length >= 1 && value.keywords.length <= 30 && value.keywords.every(item => text(item, 60, 1)) && text(value.private_reply, 700, 1) && (value.public_reply === null || text(value.public_reply, 500, 1));
}
export function validIntent(value, business) {
  if (!value || !operations.has(value.operation) || !UUID.test(value.body?.idempotency_key) || !HASH.test(value.request_hash) || !text(value.summary, 1000, 1)) return false;
  const base = `/api/v1/businesses/${business}`, operation = value.operation, body = value.body;
  if (operation === 'rule_create' || operation === 'rule_update') {
    if (!keys(body, 'idempotency_key,facts,expected_fingerprint') || !validFacts(body.facts)) return false;
    return operation === 'rule_create' ? value.resource === null && body.expected_fingerprint === null && value.path === `${base}/comment-automation/rules` && value.method === 'POST' : UUID.test(value.resource) && HASH.test(body.expected_fingerprint) && value.path === `${base}/comment-automation/rules/${value.resource}` && value.method === 'PUT';
  }
  if (!UUID.test(value.resource) || !HASH.test(body.expected_fingerprint) || value.method !== 'POST') return false;
  if (operation === 'rule_disable') return keys(body, 'idempotency_key,expected_fingerprint') && value.path === `${base}/comment-automation/rules/${value.resource}/disable`;
  if (!keys(body, 'idempotency_key,expected_fingerprint,confirmed,reason') || body.confirmed !== true || !text(body.reason, 1000, 10)) return false;
  return value.path === (operation === 'comment_close' ? `${base}/comment-automation/events/${value.resource}/reviews` : `${base}/whatsapp/enquiries/${value.resource}/close`);
}
export function validReceipt(value, intent) {
  return UUID.test(value?.command_id) && value.idempotency_key === intent.body.idempotency_key && value.operation === intent.operation && value.request_hash === intent.request_hash && typeof value.replayed === 'boolean' && keys(value.result, 'resource_id,fingerprint') && UUID.test(value.result.resource_id) && HASH.test(value.result.fingerprint) && (intent.resource === null || value.result.resource_id === intent.resource);
}
export function validRule(value) {
  return UUID.test(value?.id) && HASH.test(value.fingerprint) && UUID.test(value.product_id) && text(value.name,100,1) && typeof value.enabled==='boolean' && (value.media_id===null||/^\d{1,100}$/.test(value.media_id)) && Array.isArray(value.keywords) && value.keywords.length<=30 && value.keywords.every(item=>text(item,60,1)) && text(value.private_reply,700,1) && (value.public_reply===null||text(value.public_reply,500));
}
