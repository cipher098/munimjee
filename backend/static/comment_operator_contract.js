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

const reelActions = new Set(['link_only', 'link_and_resume']);
const reelSources = new Set(['message_link', 'referral_link', 'quoted_message', 'recent_message', 'unknown']);
const reelCode = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const reasonCode = value => value === null || typeof value === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(value);
const version = value => Number.isSafeInteger(value) && value >= 0;
function reelProducts(value) {
  return Array.isArray(value) && value.length <= 50 && new Set(value.map(row => row?.id)).size === value.length && value.every(row => keys(row, 'id,name') && UUID.test(row.id) && text(row.name, 300, 1));
}
export function validReelDetail(value, business) {
  if (!keys(value, 'business_id,inbound_id,message,received_at,customer_name,customer_ref,account_hint,source,connection_version,fingerprint,matches,products,eligibility,can_manage') || value.business_id !== business || !UUID.test(value.inbound_id) || !text(value.message, 10000) || !text(value.received_at, 64, 1) || !Number.isFinite(Date.parse(value.received_at)) || !text(value.customer_name, 300) || !text(value.customer_ref, 4) || !text(value.account_hint, 50) || !version(value.connection_version) || !HASH.test(value.fingerprint) || typeof value.can_manage !== 'boolean' || !reelProducts(value.matches) || !reelProducts(value.products)) return false;
  const source = value.source, eligibility = value.eligibility;
  if (!keys(source, 'classification,shortcode,url') || !reelSources.has(source.classification) || !keys(eligibility, 'can_link,can_resume,reason') || typeof eligibility.can_link !== 'boolean' || typeof eligibility.can_resume !== 'boolean' || !reasonCode(eligibility.reason)) return false;
  if (source.shortcode === null || source.url === null) return source.shortcode === null && source.url === null && !eligibility.can_link && !eligibility.can_resume;
  if (!reelCode(source.shortcode) || typeof source.url !== 'string' || !new RegExp('^https://www\\.instagram\\.com/(reel|p|tv)/' + source.shortcode + '/$').test(source.url)) return false;
  return !eligibility.can_resume || eligibility.can_link && ['message_link', 'referral_link', 'quoted_message'].includes(source.classification);
}
export function validReelIntent(value, business) {
  const body = value?.body;
  return value?.operation === 'reel_link' && UUID.test(value.resource) && value.business === business && value.method === 'POST' && value.path === `/api/v1/businesses/${business}/whatsapp/reel-enquiries/${value.resource}/link` && HASH.test(value.request_hash) && text(value.summary, 1000, 1) && keys(body, 'idempotency_key,action,product_id,shortcode,expected_fingerprint,expected_connection_version,confirmed') && UUID.test(body.idempotency_key) && UUID.test(body.product_id) && reelActions.has(body.action) && reelCode(body.shortcode) && HASH.test(body.expected_fingerprint) && version(body.expected_connection_version) && body.confirmed === true;
}
export function validReelReceipt(value, intent) {
  if (!keys(value, 'business_id,inbound_id,command_id,idempotency_key,action,product_id,request_hash,result,replayed') || value.business_id !== intent.business || value.inbound_id !== intent.resource || !UUID.test(value.command_id) || value.idempotency_key !== intent.body.idempotency_key || value.action !== intent.body.action || value.product_id !== intent.body.product_id || value.request_hash !== intent.request_hash || typeof value.replayed !== 'boolean') return false;
  const result = value.result;
  if (!keys(result, 'mapping,resume,reason,outbound_id,mapping_fingerprint') || result.mapping !== 'saved' || !HASH.test(result.mapping_fingerprint) || !reasonCode(result.reason)) return false;
  if (result.resume === 'queued') return value.action === 'link_and_resume' && UUID.test(result.outbound_id) && result.reason === null;
  if (result.resume === 'not_requested') return value.action === 'link_only' && result.outbound_id === null;
  return result.resume === 'held' && value.action === 'link_and_resume' && result.outbound_id === null && result.reason !== null;
}
export function validReelRejection(error, intent) {
  const value = error?.detail;
  return error?.status === 409 && keys(value, 'code,business_id,inbound_id,idempotency_key,request_hash,accepted,reason') && value.code === 'reel_operator_pre_mutation_rejection' && value.accepted === false && value.business_id === intent.business && value.inbound_id === intent.resource && value.idempotency_key === intent.body.idempotency_key && value.request_hash === intent.request_hash && reasonCode(value.reason) && value.reason !== null;
}
