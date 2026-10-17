/* Native seller catalogue. APIs own tenant, prices, reservations and activation. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const businessId = location.pathname.split('/')[3];
  const root = `/api/v1/businesses/${businessId}`;
  const catalogue = root + '/catalogue';
  const api = window.V1.api;
  let access, store = null, productPage = 1, orderPage = 1, detail = null, detailEpoch = 0, orderEpoch = 0;
  let draftCommand = null, productsLoad = 0, ordersLoad = 0;
  let draftBlocked = false, ownerId = null, sessionFingerprint = null, intentStorageKey = null;
  const INTENT_PREFIX = 'munimjee.v1.catalogue-draft:';
  const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const exactKeys = (value, keys) => isObject(value) && Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value,k));
  const boundedInteger = value => Number.isInteger(value) && value >= 0 && value <= 2000000000;
  async function digest(value) {
    const bytes = await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));
    return [...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');
  }
  function storageRead() {
    try {return sessionStorage.getItem(intentStorageKey);} catch (_) {throw Error('Browser session storage is unavailable. No new draft request can be sent. Enable session storage, then reload.');}
  }
  function persistIntent(command) {
    const value = JSON.stringify(command);
    try {sessionStorage.setItem(intentStorageKey,value);if(sessionStorage.getItem(intentStorageKey)!==value)throw Error();}
    catch (_) {throw Error('The browser could not preserve this save for recovery. No new draft request was sent. Enable session storage, then reload.');}
  }
  function removeIntent() {
    try {sessionStorage.removeItem(intentStorageKey);if(sessionStorage.getItem(intentStorageKey)!==null)throw Error();}
    catch (_) {throw Error('The browser could not clear recovery state. Keep this page open and retry the saved draft after enabling session storage.');}
  }
  function validDraftBody(body) {
    return exactKeys(body,['name','description','photo_urls','skus','seller_reviewed','idempotency_key']) &&
      typeof body.name==='string' && body.name.trim().length>0 && body.name.length<=200 &&
      typeof body.description==='string' && body.description.length<=10000 &&
      Array.isArray(body.photo_urls) && body.photo_urls.length<=30 && body.photo_urls.every(v=>typeof v==='string'&&v.length<=2048) &&
      body.seller_reviewed===true && UUID_PATTERN.test(body.idempotency_key) &&
      Array.isArray(body.skus) && body.skus.length>0 && body.skus.length<=500 && body.skus.every(sku=>
        exactKeys(sku,['options','price_minor','currency','stock_available','active']) && isObject(sku.options) &&
        Object.keys(sku.options).length<=10 && Object.entries(sku.options).every(([k,v])=>k.trim()&&k.length<=64&&typeof v==='string'&&v.trim()&&v.length<=200) &&
        boundedInteger(sku.price_minor) && sku.currency==='INR' && (sku.stock_available===null||boundedInteger(sku.stock_available)) && typeof sku.active==='boolean');
  }
  async function decodeIntent(raw) {
    if(typeof raw!=='string'||raw.length>2000000)throw Error('Saved recovery state is invalid. Review saved products and contact your business owner before starting another draft.');
    let command;try{command=JSON.parse(raw);}catch(_){throw Error('Saved recovery state cannot be read. Review saved products and contact your business owner before starting another draft.');}
    if(!exactKeys(command,['version','user_id','business_id','session_fingerprint','created_at','body','body_digest'])||command.version!==1)throw Error('Saved recovery state has an unsupported format. Review saved products before signing in again.');
    if(command.user_id!==ownerId||command.business_id!==businessId||command.session_fingerprint!==sessionFingerprint){const e=Error('Saved recovery belongs to a different sign-in or business. Its details have been withheld. Review saved products before signing in again.');e.identityMismatch=true;throw e;}
    const created=Date.parse(command.created_at);
    if(typeof command.created_at!=='string'||!Number.isFinite(created)||created>Date.now()+300000||Date.now()-created>7*86400000)throw Error('This saved intent is too old or has an invalid date. Review saved products and ask your business owner to reconcile it before starting again.');
    if(!validDraftBody(command.body)||command.body_digest!==await digest(JSON.stringify(command.body)))throw Error('Saved draft details changed or are incomplete. Review saved products and ask your business owner to reconcile the save.');
    return command;
  }
  function syncDraftUI() {
    const blocked=draftBlocked||Boolean(draftCommand);
    $('draft-fields').disabled=!can('catalogue.write')||!store||blocked;
    $('new-product').hidden=!can('catalogue.write')||!store||blocked;
    $('add-product-link').hidden=!can('catalogue.write')||!store||blocked;
    $('draft-recovery').hidden=!blocked;
    $('draft-retry').disabled=!draftCommand||draftBlocked||!can('catalogue.write')||!store;
  }
  function blockIntent(message) {
    draftBlocked=true;draftCommand=null;$('draft-recovery-facts').replaceChildren();$('draft-recovery-message').textContent=message;syncDraftUI();
  }
  function showIntent() {
    $('draft-recovery-message').textContent='This save may already have completed. The exact reviewed details below are preserved for this sign-in. Retry the saved draft to confirm the result; a reload will not submit it automatically.';
    const facts=$('draft-recovery-facts');facts.replaceChildren(el('h3',draftCommand.body.name),el('p',draftCommand.body.description));
    const list=el('ul');for(const sku of draftCommand.body.skus)list.append(el('li',`${optionsName(sku)} · ${money(sku.price_minor)} · ${sku.stock_available===null?'Quantity untracked':sku.stock_available+' available'} · ${sku.active?'For sale after activation':'Not for sale'}`));facts.append(list);syncDraftUI();
  }
  function clearIntentForIdentity() {
    if(intentStorageKey)try{sessionStorage.removeItem(intentStorageKey);}catch(_){}
    draftCommand=null;draftBlocked=true;$('draft-recovery-facts').replaceChildren();$('draft-recovery-error').textContent='';$('draft-recovery').hidden=true;
  }
  async function initializeIntent(session) {
    ownerId=session.user_id;intentStorageKey=INTENT_PREFIX+ownerId+':'+businessId;
    try{sessionFingerprint=await digest(session.csrf_token);const raw=storageRead();if(raw!==null){draftCommand=await decodeIntent(raw);showIntent();}}
    catch(error){if(error.identityMismatch)try{removeIntent();}catch(_){}blockIntent(error.message);}
  }
  async function assertDraftIdentity() {
    const session=await window.V1.session(),current=session.businesses?.find(b=>b.id===businessId);
    if(session.user_id!==ownerId||!current||!session.csrf_token||await digest(session.csrf_token)!==sessionFingerprint){clearIntentForIdentity();throw Object.assign(Error('Your sign-in or business access changed. Sign in again before continuing.'),{status:401});}
    if(!current.capabilities.includes('catalogue.write')){access=current;syncDraftUI();throw Object.assign(Error('Your current role cannot save catalogue drafts. Ask a manager to review the pending save.'),{status:403});}
  }
  function validDraftResponse(record) {
    return isObject(record)&&isObject(record.product)&&typeof record.product.name==='string'&&record.product.name.length>0&&typeof record.product.description==='string'&&Array.isArray(record.product.skus)&&record.product.skus.length>0&&record.product.skus.every(s=>s.product_id===record.product.product_id&&UUID_PATTERN.test(s.sku_id))&&record.product.business_id===businessId&&UUID_PATTERN.test(record.product.product_id)&&
      ['catalogue.v1','catalogue.v2'].includes(record.product.contract_version)&&['legacy','sku'].includes(record.inventory_mode)&&
      Number.isInteger(record.mapping_revision)&&record.mapping_revision>0&&/^[a-f0-9]{64}$/.test(record.legacy_fingerprint)&&
      Array.isArray(record.issues)&&record.issues.every(v=>typeof v==='string')&&Array.isArray(record.skus)&&record.skus.length>0&&
      record.skus.every(sku=>UUID_PATTERN.test(sku.sku_id)&&isObject(sku.options)&&boundedInteger(sku.price_minor)&&sku.currency==='INR'&&(sku.stock_available===null||boundedInteger(sku.stock_available))&&typeof sku.active==='boolean');
  }
  async function sendSavedDraft(firstAttempt=false) {
    if(!draftCommand||draftBlocked)throw Error('There is no verified draft intent to retry.');
    await assertDraftIdentity();
    try{const saved=await decodeIntent(storageRead());if(JSON.stringify(saved)!==JSON.stringify(draftCommand))throw Error('Saved draft intent changed. Reload and review its recovery state before continuing.');}
    catch(error){blockIntent(error.message);throw error;}
    let record;
    try{record=await api(catalogue+'/products',{method:'POST',body:draftCommand.body});}
    catch(error){
      if(error.status===401){clearIntentForIdentity();throw error;}
      if(firstAttempt&&error.status>=400&&error.status<500){removeIntent();draftCommand=null;syncDraftUI();}
      throw error;
    }
    if(!validDraftResponse(record))throw Error('The response did not confirm a valid draft in this business. Keep the saved intent and retry to confirm its result.');
    removeIntent();draftCommand=null;syncDraftUI();$('draft-recovery-error').textContent='';$('draft-editor').open=false;$('draft-form').reset();$('sku-rows').replaceChildren();newSKU();productPage=1;
    await loadProducts();await openProduct(record.product.product_id);$('notice').textContent='Reviewed draft confirmed. Activation is a separate action.';
  }
  const can = capability => Boolean(access?.capabilities.includes(capability));
  const el = (tag, value, className) => {const node = document.createElement(tag); if (value !== undefined) node.textContent = value; if (className) node.className = className; return node;};
  const money = value => new Intl.NumberFormat('en-IN', {style:'currency',currency:'INR'}).format(value / 100);
  const decimal = value => (value / 100).toFixed(2);
  function minor(value, limit=2000000000) {
    if (!/^\d+(\.\d{1,2})?$/.test(value.trim())) throw Error('Enter a price with at most two decimal places.');
    const [whole, fraction=''] = value.trim().split('.');
    const result = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
    if (!Number.isSafeInteger(result) || result > limit) throw Error('This amount is above the supported limit.');
    return result;
  }
  function available(input, untracked) {
    if (untracked.checked) return null;
    if (!/^\d+$/.test(input.value) || !Number.isSafeInteger(Number(input.value)) || Number(input.value) > 2000000000) throw Error('Enter a whole available quantity from 0 to 2,000,000,000.');
    return Number(input.value);
  }
  function button(label, action, kind='secondary') {const node=el('button',label,`button ${kind}`);node.type='button';node.addEventListener('click',action);return node;}
  function setError(id, error) {
    $(id).textContent = error instanceof TypeError ? "We could not confirm the response. Check your connection, then retry the same action." : error.message;
    if (error.status === 401) {clearIntentForIdentity();$('workspace').hidden=true;$('access-needed').hidden=false;$('global-error').textContent='Your session ended. Sign in again to continue.';}
  }
  async function busy(form, errorId, action) {
    if (form.dataset.busy) return;
    const contextEpoch=['activation-form','inventory-form'].includes(form.id)?detailEpoch:null;
    form.dataset.busy='true';form.setAttribute('aria-busy','true');$(errorId).textContent='';
    const controls=[...form.querySelectorAll('button')], prior=controls.map(n=>n.disabled);controls.forEach(n=>n.disabled=true);
    try {await action();} catch(error) {if(contextEpoch===null||contextEpoch===detailEpoch)setError(errorId,error);} finally {controls.forEach((n,i)=>n.disabled=prior[i]);form.removeAttribute('aria-busy');delete form.dataset.busy;}
  }
  function labelInput(parent, caption, name, value='', attributes={}) {
    const label=el('label',caption), input=document.createElement('input');input.name=name;input.value=value;
    for (const [key,v] of Object.entries(attributes)) {if(typeof v==='boolean')input[key]=v;else input.setAttribute(key,v);}
    label.append(input);parent.append(label);return input;
  }
  function check(parent, caption, name, checked=false) {
    const label=el('label',undefined,'check'),input=document.createElement('input');input.type='checkbox';input.name=name;input.checked=checked;label.append(input,el('span',caption));parent.append(label);return input;
  }
  function newSKU() {
    const row=el('fieldset',undefined,'sku-editor');row.append(el('legend',`Option combination ${$('sku-rows').children.length+1}`));
    const grid=el('div',undefined,'form-grid');row.append(grid);
    labelInput(grid,'Price (₹)','price','',{required:true,inputmode:'decimal',pattern:'[0-9]+([.][0-9]{1,2})?'});
    const stock=labelInput(grid,'Available quantity','stock','0',{required:true,inputmode:'numeric',pattern:'[0-9]+'});
    const untracked=check(grid,'Do not track quantity','untracked');untracked.addEventListener('change',()=>{stock.disabled=untracked.checked;stock.required=!untracked.checked;});
    check(grid,'Available for sale after activation','active',true);
    const options=el('div',undefined,'option-list');row.append(options);
    const actions=el('div',undefined,'sku-actions');actions.append(button('Add an option',()=>{
      if (options.children.length>=10) return;
      const pair=el('div',undefined,'option-pair');
      labelInput(pair,'Option name','option-name','',{required:true,maxlength:'64',placeholder:'e.g. Size'});
      labelInput(pair,'Option value','option-value','',{required:true,maxlength:'200',placeholder:'e.g. Medium'});
      pair.append(button('Remove option',()=>pair.remove()));options.append(pair);
    }),button('Remove combination',()=>{if($('sku-rows').children.length>1)row.remove();}));row.append(actions);
    $('sku-rows').append(row);
  }
  function readDraft() {
    const form=$('draft-form');const skus=[...$('sku-rows').children].map(row=>{
      const options=Object.create(null),seen=new Set();
      for(const pair of row.querySelectorAll('.option-pair')) {
        const name=pair.querySelector('[name=option-name]').value.trim(),value=pair.querySelector('[name=option-value]').value.trim();
        if(!name||!value||seen.has(name.toLowerCase()))throw Error('Give every option a unique name and a value.');
        seen.add(name.toLowerCase());options[name]=value;
      }
      return {options,price_minor:minor(row.querySelector('[name=price]').value),currency:'INR',stock_available:available(row.querySelector('[name=stock]'),row.querySelector('[name=untracked]')),active:row.querySelector('[name=active]').checked};
    });
    const photo=form.elements.photo_url.value.trim();
    return {name:form.elements.name.value.trim(),description:form.elements.description.value.trim(),photo_urls:photo?[photo]:[],skus,seller_reviewed:true};
  }
  async function loadStore() {
    const hadStore=Boolean(store);store=await api(catalogue+'/storefront');const form=$('store-form');
    if(!hadStore)$('store-editor').open=!store;
    $('role-note').hidden=can('catalogue.write');
    if(store)for(const [name,value] of Object.entries(store)){const input=form.elements.namedItem(name);if(!input)continue;if(input.type==='checkbox')input.checked=value;else input.value=name==='shipping_fee'?decimal(value):value||'';}
    if(!store) {form.elements.name.value=access.name;form.elements.cod_enabled.checked=false;}
    $('store-summary').textContent=store?`${store.published?'Published':'Not published'} · ${store.cod_enabled?'Cash on delivery on':'Cash on delivery off'}`:'Save a storefront to begin.';
    const publicLink=$('public-storefront');publicLink.hidden=true;publicLink.removeAttribute('href');
    if(store?.published&&typeof store.public_storefront_url==='string'){try{const url=new URL(store.public_storefront_url);if(!url.username&&!url.password&&(url.protocol==='https:'||(url.protocol==='http:'&&url.origin===location.origin))&&url.pathname==='/stores/'+store.slug&&!url.search&&!url.hash){publicLink.href=url.href;publicLink.hidden=false;}}catch(_){}}
    $('store-fields').disabled=!can('business.write');
    $('policy-fields').disabled=!can('catalogue.write')||!store;
    syncDraftUI();
    const policy=await api(catalogue+'/checkout-policy');$('checkout-enabled').checked=policy.checkout_enabled;
    $('policy-status').textContent=policy.checkout_enabled?'Checkout is enabled for activated products.':'Checkout is off.';
  }
  async function loadProducts() {
    if(!store){$('product-list').replaceChildren(el('p','Save your storefront details above to start a catalogue.','state'));$('product-page').textContent='';$('previous').disabled=$('next').disabled=true;return;}
    const epoch=++productsLoad, page=productPage;
    const data=await api(catalogue+`/products?page=${page}&page_size=12`);if(epoch!==productsLoad)return;
    $('product-list').replaceChildren();
    if(!data.items.length){$('product-list').append(el('p','No products yet. Add your first reviewed draft below.','state'));$('draft-editor').open=true;}
    for(const record of data.items){
      const product=record.product,row=el('article',undefined,'product-row'),copy=el('div');
      const pid=product?.product_id||record.product_id;
      copy.append(el('h3',product?.name||'Existing product awaiting catalogue preparation'));
      copy.append(el('p',record.inventory_mode==='sku'?'Active SKU inventory':product?.readiness==='reviewed'?'Reviewed draft · not activated':'Legacy inventory · allocation review needed','muted'));
      if(record.skus?.length)copy.append(el('p',`${record.skus.length} option combination${record.skus.length===1?'':'s'} · from ${money(Math.min(...record.skus.map(s=>s.price_minor)))}`,'money'));
      row.append(copy,button('Review product',()=>openProduct(pid).catch(e=>setError('products-error',e))));$('product-list').append(row);
    }
    $('product-page').textContent=`Page ${data.page} · ${data.total} products`;$('previous').disabled=productPage===1;$('next').disabled=productPage*data.page_size>=data.total;
  }
  function optionsName(sku){return Object.entries(sku.options).map(([k,v])=>`${k}: ${v}`).join(' · ')||'Standard';}
  function renderInventory(record){
    $('inventory-rows').replaceChildren();
    for(const sku of record.skus){
      const row=el('fieldset',undefined,'inventory-row');row.dataset.sku=sku.sku_id;row.append(el('legend',optionsName(sku)));
      labelInput(row,'Price (₹)','price',decimal(sku.price_minor),{required:true,inputmode:'decimal',pattern:'[0-9]+([.][0-9]{1,2})?'});
      const stock=labelInput(row,'Available quantity','stock',String(sku.stock_available??0),{required:sku.stock_available!==null,inputmode:'numeric',pattern:'[0-9]+'});
      const untracked=check(row,'Do not track quantity','untracked',sku.stock_available===null);stock.disabled=untracked.checked;
      untracked.addEventListener('change',()=>{stock.disabled=untracked.checked;stock.required=!untracked.checked;});check(row,'Available for sale','active',sku.active);
      $('inventory-rows').append(row);
    }
  }
  async function openProduct(pid, {scroll=true}={}) {
    const epoch=++detailEpoch;detail=null;$('activation-form').hidden=$('inventory-form').hidden=true;$('product-detail').hidden=false;$('detail-heading').textContent='Loading product…';
    $('detail-skus').replaceChildren();$('detail-description').textContent=$('detail-status').textContent=$('detail-issues').textContent='';$('legacy-help').hidden=true;
    $('activation-error').textContent=$('inventory-error').textContent='';$('activation-reviewed').checked=$('inventory-reviewed').checked=false;
    let record;
    try{record=await api(catalogue+`/products/${pid}`);}catch(error){if(epoch!==detailEpoch)return;if(error.status===401){setError('global-error',error);return;}$('detail-heading').textContent='Catalogue review needed';$('detail-status').textContent=error.message;$('legacy-help').hidden=false;return;}
    if(epoch!==detailEpoch)return;detail=record;
    $('detail-heading').textContent=record.product.name;$('detail-description').textContent=record.product.description;
    $('detail-status').textContent=record.inventory_mode==='sku'?'Active SKU inventory. Updates below change current sale quantities and prices.':record.product.readiness==='reviewed'?'Private reviewed draft. Check each option before activating.':'Legacy inventory. Seller allocation review is required before activation.';
    const table=el('table'),head=el('thead'),tr=el('tr');for(const name of ['Option','Price','Available','For sale'])tr.append(el('th',name));head.append(tr);table.append(head);const body=el('tbody');
    for(const sku of record.skus){const line=el('tr');for(const value of [optionsName(sku),money(sku.price_minor),sku.stock_available===null?'Untracked':String(sku.stock_available),sku.active?'Yes':'No'])line.append(el('td',value));body.append(line);}table.append(body);
    const wrap=el('div',undefined,'table-wrap');wrap.append(table);$('detail-skus').append(wrap);
    $('detail-issues').textContent=(record.issues||[]).join(' ');
    const reviewed=record.product.readiness==='reviewed'&&!record.issues.length;
    $('activation-form').hidden=!can('catalogue.write')||record.inventory_mode==='sku'||!reviewed;
    $('legacy-help').hidden=record.inventory_mode==='sku'||reviewed;
    $('inventory-form').hidden=!can('catalogue.write')||record.inventory_mode!=='sku';
    if(record.inventory_mode==='sku'&&can('catalogue.write'))renderInventory(record);
    if(scroll)$('product-detail').scrollIntoView({block:'start',behavior:'instant'});
  }
  async function mutationConflict(record,error,id){
    if(error.status===409&&detail?.product.product_id===record.product.product_id){await loadProducts();await openProduct(record.product.product_id,{scroll:false});$(id).textContent=error.message+' Current details have been reloaded. Review them before trying again.';return;}
    throw error;
  }
  async function loadOrders(){
    if(!can('orders.read')){$('orders').hidden=true;return;}
    const epoch=++ordersLoad, status=$('order-filter').value, page=orderPage;
    const data=await api(root+`/orders?page=${page}&page_size=10`+(status?'&status='+encodeURIComponent(status):''));if(epoch!==ordersLoad)return;
    $('order-list').replaceChildren();if(!data.items.length)$('order-list').append(el('p','No orders match this view.','state'));
    for(const order of data.items){const row=el('article',undefined,'order-row'),copy=el('div');copy.append(el('h3',order.number),el('p',`${order.customer.name} · ${money(order.total)}`),el('p',`${order.fulfillment_status} · payment ${order.payment_status}`,'muted'));row.append(copy,button('View order',()=>openOrder(order.id).catch(e=>setError('orders-error',e))));$('order-list').append(row);}
    $('order-page').textContent=`Page ${data.page} · ${data.total} orders`;$('orders-previous').disabled=orderPage===1;$('orders-next').disabled=orderPage*data.page_size>=data.total;
  }
  async function openOrder(id){
    const epoch=++orderEpoch,data=await api(root+`/orders/${id}`);if(epoch!==orderEpoch)return;
    const box=$('order-detail');box.replaceChildren();box.hidden=false;box.append(el('h3',data.number),el('p',`${data.fulfillment_status} · payment ${data.payment_status}`),el('p',`${data.customer.name} · ${data.customer.phone}`),el('p',[data.address.line1,data.address.line2,data.address.city,data.address.state,data.address.postal_code].filter(Boolean).join(', ')));
    for(const item of data.items)box.append(el('p',`${item.name||item.product_name||'Product'}${item.options?' · '+optionsName(item):''} × ${item.quantity} · ${money(item.unit_price*item.quantity)}`,'line-row'));
    box.append(el('p',`Order total ${money(data.total)}`,'money'));
    if(data.tracking_number)box.append(el('p',`${data.carrier||'Carrier'} · ${data.tracking_number}`));
    if(data.note)box.append(el('p','Customer note: '+data.note));
    const form=el('form'),error=el('p',undefined,'error');error.setAttribute('role','alert');const actions=el('div',undefined,'order-actions');form.append(actions,error);box.append(form);
    const parcelPath=`/v1/businesses/${businessId}/orders/${id}/parcel`;
    if(data.parcel_url===parcelPath){const link=el('a','Link or view parcel','button');link.href=parcelPath;actions.append(link);}
    const next={pending:'confirmed',confirmed:'packed',packed:'shipped',shipped:'delivered'}[data.fulfillment_status];
    if(can('orders.write')){
      let carrier,tracking,url;
      if(next==='shipped'){const fields=el('div',undefined,'form-grid');form.prepend(fields);carrier=labelInput(fields,'Carrier','carrier','',{maxlength:'100'});tracking=labelInput(fields,'Tracking number','tracking_number','',{maxlength:'200'});url=labelInput(fields,'Tracking URL (optional)','tracking_url','',{type:'url',maxlength:'2000'});}
      let pending=false;
      const transition=async status=>{
        if(pending)return;
        if(status==='shipped'&&!form.reportValidity())return;
        if(status==='cancelled'&&!window.confirm('Cancel this order and release its reserved stock? Paid orders will need refund review.'))return;
        pending=true;error.textContent='';actions.querySelectorAll('button').forEach(n=>n.disabled=true);
        try{await api(root+`/orders/${id}/transition`,{method:'POST',body:{status,...(status==='shipped'?{carrier:carrier.value||null,tracking_number:tracking.value||null,tracking_url:url.value||null}:{})}});if(epoch!==orderEpoch)return;await loadOrders();await openOrder(id);$('notice').textContent='Order updated.';}
        catch(e){if(epoch===orderEpoch){error.textContent=e.message+' Refresh the order before trying again.';if(e.status===401)setError('global-error',e);}}
        finally{pending=false;if(epoch===orderEpoch)actions.querySelectorAll('button').forEach(n=>n.disabled=false);}
      };
      if(next)actions.append(button({confirmed:'Confirm order',packed:'Mark packed',shipped:'Mark shipped',delivered:'Mark delivered'}[next],()=>transition(next),'primary'));
      if(['pending','confirmed','packed'].includes(data.fulfillment_status))actions.append(button('Cancel order',()=>transition('cancelled'),'danger'));
    }
    actions.append(button('Refresh order',()=>openOrder(id).catch(e=>setError('orders-error',e))));actions.append(button('Close order',()=>{orderEpoch++;box.hidden=true;box.replaceChildren();}));box.scrollIntoView({block:'start',behavior:'instant'});
  }
  $('store-form').addEventListener('submit',event=>{event.preventDefault();busy(event.currentTarget,'store-error',async()=>{
    const form=$('store-form'),body={};for(const name of ['name','slug','description','contact_email','contact_phone','shipping_policy','return_policy'])body[name]=form.elements[name].value.trim();
    body.logo_url=form.elements.logo_url.value.trim()||null;body.currency='INR';body.shipping_fee=minor(form.elements.shipping_fee.value,10000000);body.cod_enabled=form.elements.cod_enabled.checked;body.published=form.elements.published.checked;
    await api(catalogue+'/storefront',{method:'PUT',body});await loadStore();await loadProducts();$('store-saved').textContent='Saved';$('notice').textContent='Storefront saved.';
  });});
  $('policy-form').addEventListener('submit',event=>{event.preventDefault();busy(event.currentTarget,'policy-error',async()=>{const enabled=$('checkout-enabled').checked;await api(catalogue+'/checkout-policy',{method:'PUT',body:{checkout_enabled:enabled}});$('policy-status').textContent=enabled?'Checkout is enabled for activated products.':'Checkout is off.';$('notice').textContent='Checkout policy saved.';});});
  $('add-product-link').addEventListener('click',()=>{$('draft-editor').open=true;$('draft-form').elements.name.focus({preventScroll:true});});
  $('add-sku').addEventListener('click',()=>{if($('sku-rows').children.length<500)newSKU();});newSKU();
  $('draft-form').addEventListener('submit',event=>{event.preventDefault();busy(event.currentTarget,'draft-error',async()=>{
    if(draftCommand||draftBlocked)throw Error('Resolve the saved draft recovery above before starting another draft.');
    await assertDraftIdentity();
    try{
      if(storageRead()!==null)throw Error('A saved draft already needs recovery. Reload to review it before starting another draft.');
      const body={...readDraft(),idempotency_key:crypto.randomUUID()};
      const command={version:1,user_id:ownerId,business_id:businessId,session_fingerprint:sessionFingerprint,created_at:new Date().toISOString(),body,body_digest:await digest(JSON.stringify(body))};
      if(!validDraftBody(body))throw Error('Review the product fields before saving.');
      persistIntent(command);draftCommand=command;showIntent();
    }catch(error){blockIntent(error.message);throw error;}
    await sendSavedDraft(true);
  });});
  $('draft-retry').addEventListener('click',()=>busy($('draft-recovery'),'draft-recovery-error',()=>sendSavedDraft(false)));
  $('activation-form').addEventListener('submit',event=>{event.preventDefault();busy(event.currentTarget,'activation-error',async()=>{
    const record=detail, epoch=detailEpoch;if(!record)return;try{await api(catalogue+`/products/${record.product.product_id}/activate`,{method:'POST',body:{seller_reviewed:true,expected_mapping_revision:record.mapping_revision,expected_legacy_fingerprint:record.legacy_fingerprint}});await loadProducts();if(epoch===detailEpoch)await openProduct(record.product.product_id,{scroll:false});$('notice').textContent='Product activated. Store publication and checkout policy are unchanged.';}catch(error){await mutationConflict(record,error,'activation-error');}
  });});
  $('inventory-form').addEventListener('submit',event=>{event.preventDefault();busy(event.currentTarget,'inventory-error',async()=>{
    const record=detail, epoch=detailEpoch;if(!record)return;const rows=[...$('inventory-rows').children];const skus=rows.map(row=>{const original=record.skus.find(s=>s.sku_id===row.dataset.sku);return {...original,price_minor:minor(row.querySelector('[name=price]').value),stock_available:available(row.querySelector('[name=stock]'),row.querySelector('[name=untracked]')),active:row.querySelector('[name=active]').checked};});
    try{await api(catalogue+`/products/${record.product.product_id}/skus`,{method:'PUT',body:{seller_reviewed:true,expected_mapping_revision:record.mapping_revision,skus}});await loadProducts();if(epoch===detailEpoch)await openProduct(record.product.product_id,{scroll:false});$('notice').textContent='Inventory saved.';}catch(error){await mutationConflict(record,error,'inventory-error');}
  });});
  $('close-detail').addEventListener('click',()=>{detailEpoch++;detail=null;$('product-detail').hidden=true;});
  for(const [id,direction] of [['previous',-1],['next',1]])$(id).addEventListener('click',()=>{productPage=Math.max(1,productPage+direction);loadProducts().catch(e=>setError('products-error',e));});
  for(const [id,direction] of [['orders-previous',-1],['orders-next',1]])$(id).addEventListener('click',()=>{orderPage=Math.max(1,orderPage+direction);loadOrders().catch(e=>setError('orders-error',e));});
  $('order-filter').addEventListener('change',()=>{orderPage=1;orderEpoch++;$('order-detail').hidden=true;loadOrders().catch(e=>setError('orders-error',e));});
  $('refresh').addEventListener('click',()=>busy($('main'),'global-error',async()=>{await loadStore();await loadProducts();await loadOrders();if(detail)await openProduct(detail.product.product_id,{scroll:false});}));
  (async()=>{try{const session=await window.V1.session();access=session.businesses.find(b=>b.id===businessId);if(!session.csrf_token||!access)throw Object.assign(Error('This business is unavailable. Sign in with an account that has access.'),{status:401});$('business-name').textContent=access.name;await initializeIntent(session);await loadStore();await loadProducts();await loadOrders();$('workspace').hidden=false;}catch(e){setError('global-error',e);}finally{$('loading').hidden=true;}})();
})();
