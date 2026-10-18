/* Read-only native order cohorts; no customer facts, credentials or stored reports. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id),bid=location.pathname.split('/')[3];
  const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i,DAY=/^\d{4}-\d{2}-\d{2}$/;
  const MONEY=/^(0|[1-9][0-9]*)$/,CURRENCY=/^[A-Z]{3}$/;
  const payments=['pending','collected','cancelled','paid','expired','review_required'],fulfillments=['pending','confirmed','packed','shipped','delivered','cancelled'];
  const countKeys=['placed','online_paid','cod_collected','payment_review','cancelled','expired','unclassified_test_activity'];
  const unavailableKeys=['visits','product_views','enquiries','checkout_starts','conversion_rate','attribution','completed_refunds_minor','payment_fees_minor','net_revenue_minor','settlement_period_cashflow'];
  const exact=(x,keys)=>x!==null&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).length===keys.length&&keys.every(k=>Object.hasOwn(x,k));
  const count=x=>Number.isSafeInteger(x)&&x>=0;
  let context=null,ended=false,checking=false,recheckPending=false,loading=false,report=null,currentQuery=null;
  let epoch=0,sessionIssued=0,sessionApplied=0,latestSession=null;
  async function api(path,options={}){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);try{return await window.V1.api(path,{...options,signal:controller.signal,redirect:'error'});}finally{clearTimeout(timer);}}
  function clearReport(){report=null;for(const id of ['counts','money','daily','orders'])$(id).replaceChildren();for(const id of ['cohort-label','test-note','page-label'])$(id).textContent='';$('report').hidden=true;}
  function end(message){if(ended)return;ended=true;epoch++;clearReport();$('filters').reset();context=null;latestSession=null;currentQuery=null;$('business-name').textContent='Purchases and payments';$('orders-link').removeAttribute('href');$('orders-link').hidden=true;$('workspace').hidden=true;$('logout').hidden=true;$('error').textContent='';$('loading').textContent='';$('access-message').textContent=message;$('access-needed').hidden=false;sync();}
  function cookie(){try{return document.cookie.split(';').map(x=>x.trim()).filter(x=>x.startsWith('v1_csrf=')).map(x=>decodeURIComponent(x.slice(8)))[0]||null;}catch(_){return null;}}
  async function session(){
    if(ended)throw Error('Ended');const sequence=++sessionIssued;
    if(context&&cookie()!==context.csrf){end('Your sign-in changed. Reopen analytics from business setup.');throw Error('Changed');}
    let value=await api('/api/v1/auth/session');if(ended)throw Error('Ended');
    if(!UUID.test(value?.user_id)||typeof value.csrf_token!=='string'||!value.csrf_token||!Array.isArray(value.businesses))throw Error('Invalid session');
    if(sequence<sessionApplied)value=latestSession;
    if(cookie()!==value.csrf_token||(context&&(context.user!==value.user_id||context.csrf!==value.csrf_token))){end('Your sign-in changed. Reopen analytics from business setup.');throw Error('Changed');}
    const business=value.businesses.find(b=>b.id===bid);
    if(!business||!Array.isArray(business.capabilities)||!business.capabilities.includes('analytics.read')){end('Your current role does not include analytics for this business. Ask its owner to review your access.');throw Error('Access changed');}
    if(ended)throw Error('Ended');
    context={user:value.user_id,csrf:value.csrf_token};if(sequence>=sessionApplied){sessionApplied=sequence;latestSession=value;}
    $('business-name').textContent=business.name;$('logout').hidden=false;$('orders-link').href=`/v1/businesses/${bid}/catalogue#orders`;$('orders-link').hidden=false;
    return value;
  }
  function sync(){
    $('workspace').hidden=ended||!context||document.hidden||checking;
    $('filter-fields').disabled=ended||!context||checking;
    $('refresh').disabled=ended||!context||checking||loading;
    $('previous').disabled=ended||loading||checking||!report||report.filters.page<=1;
    $('next').disabled=ended||loading||checking||!report?.has_next;
    $('loading').textContent=ended?'':checking?'Checking your current access…':loading?'Loading order facts…':'';
  }
  function dates(){const end=new Date();end.setUTCHours(0,0,0,0);end.setUTCDate(end.getUTCDate()+1);const start=new Date(end);start.setUTCDate(start.getUTCDate()-30);$('from-date').value=start.toISOString().slice(0,10);$('to-date').value=end.toISOString().slice(0,10);}
  function capture(){
    const start=$('from-date').value,end=$('to-date').value,days=(Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000;
    if(!DAY.test(start)||!DAY.test(end)||!Number.isInteger(days)||days<1||days>366)throw Error('Choose 1–366 UTC dates. The end date is not included.');
    return {from_date:start,to_date:end,payment_status:$('payment-status').value||null,fulfillment_status:$('fulfillment-status').value||null,payment_method:$('payment-method').value||null,include_gateway_test:$('include-test').checked,page:1,page_size:25};
  }
  function valid(data,query){
    if(!exact(data,['contract_version','business_id','generated_at','metric_basis','data_scope','filters','counts','currency_totals','daily','orders','has_next','known_gateway_test_excluded','unavailable'])||data.contract_version!=='seller-analytics.v1'||data.business_id!==bid||data.metric_basis!=='order_created_utc_current_states'||data.data_scope!=='commerce_orders_only'||!Number.isFinite(Date.parse(data.generated_at))||!exact(data.filters,Object.keys(query))||!Object.keys(query).every(k=>data.filters[k]===query[k])||!exact(data.counts,countKeys)||!countKeys.every(k=>count(data.counts[k]))||typeof data.has_next!=='boolean'||!count(data.known_gateway_test_excluded)||!exact(data.unavailable,unavailableKeys)||!unavailableKeys.every(k=>data.unavailable[k]===null))return false;
    if(!Array.isArray(data.currency_totals)||data.currency_totals.length>100||!data.currency_totals.every(row=>exact(row,['currency','placed_order_value_minor','online_paid_minor','cod_collected_minor','captured_review_minor'])&&CURRENCY.test(row.currency)&&Object.keys(row).filter(k=>k!=='currency').every(k=>typeof row[k]==='string'&&MONEY.test(row[k])&&row[k].length<=40)))return false;
    if(!Array.isArray(data.daily)||data.daily.length!==((Date.parse(query.to_date)-Date.parse(query.from_date))/86400000)||!data.daily.every((row,i)=>exact(row,['date','placed','cancelled'])&&row.date===new Date(Date.parse(query.from_date)+i*86400000).toISOString().slice(0,10)&&count(row.placed)&&count(row.cancelled)))return false;
    return Array.isArray(data.orders)&&data.orders.length<=query.page_size&&data.orders.every(row=>exact(row,['order_id','created_at','currency','total_minor','payment_method','payment_status','fulfillment_status','test_classification'])&&UUID.test(row.order_id)&&Number.isFinite(Date.parse(row.created_at))&&CURRENCY.test(row.currency)&&typeof row.total_minor==='string'&&MONEY.test(row.total_minor)&&['cod','razorpay'].includes(row.payment_method)&&payments.includes(row.payment_status)&&fulfillments.includes(row.fulfillment_status)&&['known_gateway_test','known_gateway_live','unclassified'].includes(row.test_classification));
  }
  function money(currency,minor){if(currency!=='INR')return `${currency} ${BigInt(minor).toLocaleString()} minor units`;const value=BigInt(minor);return `INR ${(value/100n).toLocaleString('en-IN')}.${(value%100n).toString().padStart(2,'0')}`;}
  function cell(row,value){const td=document.createElement('td');td.textContent=value;row.append(td);}
  function render(){
    const f=report.filters;$('cohort-label').textContent=`Orders placed from ${f.from_date} through ${f.to_date} (end excluded), UTC. Current states as of ${new Date(report.generated_at).toISOString().replace('T',' ').slice(0,19)} UTC.`;
    $('test-note').textContent=`${report.known_gateway_test_excluded.toLocaleString()} known Razorpay test orders excluded. ${report.counts.unclassified_test_activity.toLocaleString()} included orders have no reliable test marker. ${f.include_gateway_test?'Known test orders are included in these results.':'Other test activity may remain.'}`;
    for(const [key,label] of [['placed','Orders placed'],['online_paid','Online paid (confirmed)'],['cod_collected','COD collected'],['payment_review','Needs payment review'],['cancelled','Cancelled (payment or fulfillment)'],['expired','Expired payment state']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=report.counts[key].toLocaleString();$('counts').append(dt,dd);}
    for(const item of report.currency_totals){const tr=document.createElement('tr');cell(tr,item.currency);for(const key of ['placed_order_value_minor','online_paid_minor','cod_collected_minor','captured_review_minor'])cell(tr,money(item.currency,item[key]));$('money').append(tr);}
    $('money-empty').hidden=report.currency_totals.length!==0;
    for(const day of [...report.daily].reverse()){const tr=document.createElement('tr');cell(tr,day.date);cell(tr,day.placed.toLocaleString());cell(tr,day.cancelled.toLocaleString());$('daily').append(tr);}
    for(const order of report.orders){const tr=document.createElement('tr');cell(tr,order.order_id.slice(0,8));tr.firstElementChild.title=order.order_id;cell(tr,new Date(order.created_at).toISOString().replace('T',' ').slice(0,19));cell(tr,money(order.currency,order.total_minor));cell(tr,order.payment_method==='cod'?'COD':'Razorpay');cell(tr,{paid:'Paid (recorded state)',collected:'COD collected',review_required:'Review required'}[order.payment_status]||order.payment_status);cell(tr,order.fulfillment_status);cell(tr,{known_gateway_test:'Gateway test',known_gateway_live:'Gateway live',unclassified:'Unknown'}[order.test_classification]);$('orders').append(tr);}
    $('empty').hidden=report.orders.length!==0;$('order-table').hidden=report.orders.length===0;$('page-label').textContent=`Page ${f.page} · ${report.counts.placed.toLocaleString()} included orders`;$('report').hidden=false;sync();
  }
  async function load(query){
    if(ended)return;const ownEpoch=++epoch;currentQuery={...query};loading=true;clearReport();$('error').textContent='';sync();
    try{await session();if(ended||ownEpoch!==epoch)return;const params=new URLSearchParams();for(const [key,value] of Object.entries(query))if(value!==null)params.set(key,String(value));const data=await api(`/api/v1/businesses/${bid}/analytics?${params}`);await session();if(ended||ownEpoch!==epoch)return;if(!valid(data,query))throw Error('Invalid report');report=data;render();}
    catch(error){if(error.status===401||error.status===403||error.status===404)end('Your sign-in or business access changed. Reopen analytics from business setup.');if(!ended&&ownEpoch===epoch){clearReport();$('error').textContent=error.status===422?'Choose a supported date range and filters, then apply them again.':'Analytics could not be checked. Refresh results to try again.';}}
    finally{if(ownEpoch===epoch){loading=false;sync();}}
  }
  $('filters').addEventListener('submit',event=>{event.preventDefault();try{load(capture());}catch(error){clearReport();$('error').textContent=error.message;}});
  $('last-30').addEventListener('click',dates);$('refresh').addEventListener('click',()=>{if(currentQuery)load(currentQuery);});
  $('previous').addEventListener('click',()=>{if(report&&report.filters.page>1)load({...currentQuery,page:report.filters.page-1});});
  $('next').addEventListener('click',()=>{if(report?.has_next)load({...currentQuery,page:report.filters.page+1});});
  $('logout').addEventListener('click',async()=>{end('Signing out…');try{await api('/api/v1/auth/logout',{method:'POST'});$('access-message').textContent='Signed out. Return to business setup to sign in again.';}catch(_){$('access-message').textContent='Sign-out could not be confirmed. Return to business setup to check your session.';}});
  async function recheck(){if(ended)return;if(checking){recheckPending=true;return;}checking=true;sync();try{await session();}catch(_){if(!ended)end('Your current sign-in could not be checked. Reopen analytics from business setup.');}finally{checking=false;sync();if(recheckPending&&!ended){recheckPending=false;recheck();}}}
  window.addEventListener('focus',recheck);window.addEventListener('pageshow',recheck);document.addEventListener('visibilitychange',()=>{if(document.hidden)$('workspace').hidden=true;else recheck();});window.addEventListener('pagehide',()=>{$('workspace').hidden=true;});
  dates();load(capture());
})();
