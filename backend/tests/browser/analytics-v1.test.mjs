/* Pure checks for exact money and the private read contract; no server/DB. */
import assert from 'node:assert/strict';import test from 'node:test';import vm from 'node:vm';import {readFileSync} from 'node:fs';
const fixture=JSON.parse(readFileSync(new URL('../../../docs/contracts/analytics-v1/mixed-read.json',import.meta.url),'utf8'));
const source=readFileSync(new URL('../../static/analytics_v1.js',import.meta.url),'utf8');
const node=()=>({addEventListener(){}}),window={V1:{api(){throw Error('No network allowed');}},addEventListener(){}},document={getElementById:node,addEventListener(){}};
assert.ok(source.includes('  dates();load(capture());'));
vm.runInNewContext(source.replace('  dates();load(capture());','  window.review={money,valid};'),{window,document,location:{pathname:`/v1/businesses/${fixture.business_id}/analytics`},URLSearchParams,Date,Intl});
test('INR minor units above Number safe range are formatted without rounding',()=>{
 assert.equal(window.review.money('INR','9007199254740993'),'INR 9,00,71,99,25,47,409.93');
 assert.equal(window.review.money('INR','1'),'INR 0.01');
});
test('other currencies remain exact minor units without a guessed fraction or exchange rate',()=>{
 assert.equal(window.review.money('USD','15'),'USD 15 minor units');
});
test('report validation binds the current filters and refuses secret or inexact extra values',()=>{
 assert.equal(window.review.valid(fixture,fixture.filters),true);
 for(const change of ['query','secret','numeric']){const data=structuredClone(fixture);
  if(change==='query')data.filters.payment_status='paid';
  if(change==='secret')data.orders[0].customer={name:'Private'};
  if(change==='numeric')data.currency_totals[0].online_paid_minor=9007199254740992;
  assert.equal(window.review.valid(data,fixture.filters),false);
 }
});
