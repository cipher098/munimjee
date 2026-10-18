import assert from 'node:assert/strict';import test from 'node:test';import vm from 'node:vm';import {readFileSync} from 'node:fs';
const data=JSON.parse(readFileSync(new URL('../../../docs/contracts/activity-v1/unavailable-report.json',import.meta.url)));
const source=readFileSync(new URL('../../static/analytics_activity.js',import.meta.url),'utf8');
const document={getElementById:()=>({addEventListener(){}}),addEventListener(){}};
const window={addEventListener(){}};
vm.runInNewContext(source.split(' const until=new Date();')[0]+' window.review={validReport,validReceipt,commandValid};})();',
 {window,document,location:{pathname:`/v1/businesses/${data.business_id}/analytics`},Date,URLSearchParams});
test('strict activity view binds business/dates and preserves unavailable nulls',()=>{
 assert(window.review.validReport(data,data.from_date,data.to_date));
 for(const variant of ['extra','foreign','zero','money','attribution']){const value=structuredClone(data);
  if(variant==='extra')value.customer={phone:'private'};
  if(variant==='foreign')value.business_id='00000000-0000-4000-8000-000000000000';
  if(variant==='zero')value.conversion.percentage='0.00';
  if(variant==='money')value.production_orders.currency_totals=[{currency:'INR',placed_order_value_minor:1200,online_paid_minor:'0',cod_collected_minor:'0',captured_review_minor:'0'}];
  if(variant==='attribution')value.attribution='guessed';
  assert.equal(window.review.validReport(value,data.from_date,data.to_date),false,variant);
 }
});
test('conversion must be bounded exact supported context fraction',()=>{
 const value=structuredClone(data);value.coverage.state='available';value.coverage.reasons=[];value.conversion={numerator:1,denominator:3,percentage:'33.33',window_minutes:30,unavailable_reason:null};
 assert(window.review.validReport(value,data.from_date,data.to_date));value.conversion.percentage='33.34';assert(!window.review.validReport(value,data.from_date,data.to_date));value.conversion.numerator=4;assert(!window.review.validReport(value,data.from_date,data.to_date));
});
test('policy acknowledgement binds exact key mode expected revision and business',()=>{
 const body={expected_revision:2,idempotency_key:'11111111-1111-4111-8111-111111111111',mode:'live',first_party_measurement_acknowledged:true};
 assert(window.review.commandValid(body));assert(!window.review.commandValid({...body,first_party_measurement_acknowledged:1}));
 const receipt={contract_version:'activity-policy-receipt.v1',business_id:data.business_id,idempotency_key:body.idempotency_key,mode:'live',applied_revision:3,accepted_at:'2026-10-18T00:00:00Z',replayed:false};
 assert(window.review.validReceipt(receipt,body));assert(!window.review.validReceipt({...receipt,applied_revision:2},body));assert(!window.review.validReceipt({...receipt,idempotency_key:crypto.randomUUID()},body));
});
test('partial channel observations never manufacture delivery, resolution or empty-family zero',()=>{
 const partial=JSON.parse(readFileSync(new URL('../../../docs/contracts/activity-v1/channel-partial-report.json',import.meta.url)));
 assert(window.review.validReport(partial,partial.from_date,partial.to_date));
 for(const variant of ['delivery','resolution','duplicate','empty-family','zero','test-only']){
  const value=structuredClone(partial),h=value.channel_activity;
  if(variant==='delivery')h.automation_outcomes.delivered=1;
  if(variant==='resolution')h.automation_outcomes.resolved_enquiries=1;
  if(variant==='duplicate')h.included_source_kinds.push('wa_outbound');
  if(variant==='empty-family')h.included_source_kinds=['instagram_ingress'];
  if(variant==='zero')h.enquiry_messages=0;
  if(variant==='test-only')h.reason='no_production_observations';
  assert.equal(window.review.validReport(value,value.from_date,value.to_date),false,variant);
 }
});
