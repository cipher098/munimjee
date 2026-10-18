import {UUID,HASH,stable,digest,validFacts,validIntent,validReceipt,validRule,validReelDetail,validReelIntent,validReelReceipt,validReelRejection} from './comment_operator_contract.js';

const $=id=>document.getElementById(id), business=location.pathname.split('/')[3];
const base=`/api/v1/businesses/${business}`, comments=`${base}/comment-automation`, enquiries=`${base}/whatsapp/enquiries`, prefix='munimjee.v1.comment-command:';
const reelEnquiries=`${base}/whatsapp/reel-enquiries`,reelPrefix='munimjee.v1.reel-command:';
let reelIntent=null,reelStorageKey=null,sessionScope=null;
let identity=null,storageKey=null,ended=false,generation=0,selectionEpoch=0,listEpoch=0,canManage=false,busy=false,intent=null,journalBlocked=false;
let sessionCounter=0,sessionApplied=0;
let viewReady=false;
let tab='events',cursor=null,nextCursor=null,pages=[],selected=null,editing=null,previewRule=null,productCursor=null,productsStarted=false;
const rules=new Map(),products=new Map();
const csrfCookie=()=>{try{return document.cookie.split(';').map(value=>value.trim()).find(value=>value.startsWith('v1_csrf='))?.slice(8)||null;}catch{return null;}};
const explanations={
  legacy_binding_unverified:'This saved action has no verified source-account record.', source_generation_changed:'The account authorization changed after this comment was saved.',
  automation_paused:'Automated sending is paused.', account_access_not_checked:'Check current account access before enabling future replies.',
  business_unavailable:'This business is currently unavailable.', source_binding_unavailable:'Account authorization needs attention.', configuration_unavailable:'The channel setup is incomplete.',
  rule_configuration_changed:'The rule or its reply changed before this action could run.', product_context_unavailable:'The linked product or storefront is unavailable.',
  product_context_unbound:'This rule does not have an explicit matching post.', product_context_ambiguous:'More than one product matches this comment.',
  activated_context_requires_review:'Static comment replies for this catalogue product are not supported.', source_time_unverified:'The comment creation time could not be verified.',
  source_too_old:'This comment is outside the local eligibility limit.', activated_inferred_context:'Needs a manual reply: this follow-up has no explicit product reference.'
};
const explain=code=>explanations[code]||'This result needs review. Check the original conversation before deciding.';
const date=value=>value?new Date(value).toLocaleString():'Not recorded';
const node=(tag,text,className)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(className)value.className=className;return value;};
function current(value){if(!ended&&identity&&csrfCookie()!==identity.split(':')[1])fence('Your sign-in changed. Private facts were cleared.');if(ended||generation!==value)throw Error('Your access changed. Private facts were cleared.');}
function fence(message,removeStorage=true){
  if(ended)return;ended=true;generation++;selectionEpoch++;listEpoch++;canManage=false;selected=null;editing=null;previewRule=null;intent=null;reelIntent=null;rules.clear();products.clear();
  $('workspace').hidden=true;$('business-name').textContent='';for(const id of ['records','detail-meta','detail-content','detail-block','preview-result','recovery-summary','notice','readiness','page-label','reel-meta','reel-message','reel-source','reel-eligibility','reel-recovery-summary','reel-error'])$(id).replaceChildren();
  for(const dialog of document.querySelectorAll('dialog')){if(dialog.open)dialog.close();}
  for(const form of document.querySelectorAll('form'))form.reset();$('rule-product').replaceChildren();$('reel-product').replaceChildren();
  for(const input of document.querySelectorAll('input,textarea'))input.value='';
  for(const control of document.querySelectorAll('#workspace button,dialog button,input,select,textarea'))control.disabled=true;
  if(removeStorage&&storageKey)try{sessionStorage.removeItem(storageKey);}catch{}
  if(removeStorage&&reelStorageKey)try{sessionStorage.removeItem(reelStorageKey);}catch{}
  $('error').textContent=message;$('signin').hidden=false;
}
function controls(){
  const blocked=busy||ended||Boolean(intent)||Boolean(reelIntent)||journalBlocked||!viewReady;
  $('new-rule').hidden=tab!=='rules'||!canManage;$('new-rule').disabled=blocked;$('retry').disabled=busy||!canManage||ended||journalBlocked;
  $('review-form').hidden=!selected?.can_close||!canManage;$('close-review').disabled=blocked;
  $('save-rule').disabled=blocked||!canManage;$('disable-rule').disabled=blocked||!canManage;$('rule-form').hidden=!canManage;
  $('preview-form').hidden=!canManage;$('refresh').disabled=busy||ended;
  for(const element of document.querySelectorAll('#rule-form input,#rule-form textarea,#rule-form select'))element.disabled=blocked||!canManage;
  for(const button of document.querySelectorAll('.record-actions button'))button.disabled=busy||ended||(button.dataset.manage==='true'&&!canManage);
  $('reel-retry').disabled=busy||ended||!canManage||journalBlocked;
  $('reel-form').hidden=!canManage||!selected?.can_manage||selected?.kind!=='reels';
  const reelBlocked=blocked||!canManage||!selected?.eligibility?.can_link||!$('reel-product').value||!$('reel-confirm').checked;
  $('reel-product').disabled=blocked||!canManage;$('reel-confirm').disabled=blocked||!canManage;
  $('reel-link-only').disabled=reelBlocked;$('reel-resume').disabled=reelBlocked||!selected?.eligibility?.can_resume;
}
async function session(write=false){
  const g=generation,sequence=++sessionCounter;current(g);let value;
  try{value=await window.V1.session();}catch(error){fence(error.status===401?'Your sign-in ended. Private facts were cleared.':'Your sign-in could not be checked. Reload to review your saved action.',error.status===401);throw error;}
  current(g);
  if(sequence<sessionApplied)throw Error('A newer sign-in check finished. Refresh before continuing.');
  sessionApplied=sequence;
  if(!UUID.test(value?.user_id)||typeof value.csrf_token!=='string'||!value.csrf_token||value.csrf_token!==csrfCookie()){fence('A current native sign-in is required. Private facts were cleared.');throw Error('Native sign-in required');}
  const binding=`${value.user_id}:${value.csrf_token}`;
  if(identity&&identity!==binding){fence('Your sign-in changed. Private facts were cleared.');throw Error('The native session changed');}
  identity=binding;const membership=value.businesses?.find(item=>item.id===business);
  if(!membership?.capabilities?.includes('inbox.read')){fence('Your inbox access ended. Private facts were cleared.');throw Error('Current inbox access is required');}
  const previousManage=canManage;canManage=membership.capabilities.includes('automation.manage');
  if(previousManage&&!canManage&&(tab==='reels'||reelIntent||selected?.kind==='reels')){fence('Your review permission changed. Private facts were cleared.');throw Error('Current review permission is required');}
  controls();
  if(write&&!canManage)throw Error('An owner or manager must review this action.');
  return value;
}
async function api(path,options={}){
  const g=generation,write=Boolean(options.method&&options.method!=='GET');await session(write);current(g);
  const frozenBody=write&&path.startsWith(reelEnquiries+'/')&&path.endsWith('/link')?stable(options.body):null;
  let value;try{value=await window.V1.api(path,options);}catch(error){if(error.status===401)fence('Your sign-in ended. Private facts were cleared.');else if(error.status===403)await session();if(frozenBody!==null&&error.status===409&&error.code==='reel_operator_pre_mutation_rejection'){current(g);error.reel_request_path=path;error.reel_request_body=frozenBody;}throw error;}
  current(g);await session(write);current(g);return value;
}
function renderIntent(){$('recovery').hidden=!intent;$('recovery-summary').textContent=intent?.summary||'';controls();}
async function prepare(operation,resource,path,method,body,summary){
  const g=generation,saved={format:1,user:identity.split(':')[0],business,at:Date.now(),operation,resource,path,method,body,summary};
  saved.request_hash=await digest({operation,resource_id:resource,body});saved.digest=await digest({...saved});current(g);
  if(!validIntent(saved,business))throw Error('The exact saved action could not be verified. Nothing was sent.');
  const raw=JSON.stringify(saved);try{sessionStorage.setItem(storageKey,raw);if(sessionStorage.getItem(storageKey)!==raw)throw Error();}catch{throw Error('Session storage is unavailable. No action was sent.');}
  current(g);intent=saved;renderIntent();
}
async function recover(){
  const g=generation;let raw;try{raw=sessionStorage.getItem(storageKey);}catch{journalBlocked=true;throw Error('Saved actions cannot be checked. No new action will be sent.');}
  if(!raw)return;
  try{if(raw.length>15000)throw Error();const saved=JSON.parse(raw),claimed=saved.digest;delete saved.digest;
    if(saved.format!==1||saved.user!==identity.split(':')[0]||saved.business!==business||saved.at>Date.now()+60000||Date.now()-saved.at>86400000||!Number.isFinite(saved.at)||!validIntent(saved,business)||claimed!==await digest(saved)||saved.request_hash!==await digest({operation:saved.operation,resource_id:saved.resource,body:saved.body}))throw Error();
    current(g);intent={...saved,digest:claimed};renderIntent();
  }catch(error){journalBlocked=true;controls();throw Error('The saved action cannot be verified. Review its history with an owner before starting another one.');}
}
function validEvent(row){return UUID.test(row?.id)&&typeof row.text==='string'&&HASH.test(row.fingerprint)&&typeof row.can_close==='boolean'&&Array.isArray(row.actions)&&row.actions.every(action=>['private','public'].includes(action.kind)&&typeof action.body==='string'&&['not_attempted','not_confirmed','provider_accepted'].includes(action.delivery_state));}
function validEnquiry(row){return UUID.test(row?.id)&&UUID.test(row.inbound_message_id)&&typeof row.message==='string'&&typeof row.customer_name==='string'&&typeof row.customer_ref==='string'&&row.reason==='activated_inferred_context'&&HASH.test(row.fingerprint)&&typeof row.can_close==='boolean';}
function delivery(value){return value==='provider_accepted'?'Provider accepted · delivery not confirmed':value==='not_attempted'?'No send attempted':'Send result not confirmed · check Instagram';}
function button(label,action,manage=false){const result=node('button',label,'button secondary');result.type='button';result.dataset.manage=String(manage);result.addEventListener('click',()=>action().catch(onError));return result;}
async function loadCurrent(){
  const epoch=++listEpoch,kind=tab,state=kind==='rules'?'all':$('state').value,params=new URLSearchParams({state,limit:'20'});if(cursor)params.set('cursor',cursor);
  $('list-state').textContent='Loading saved activity…';$('error').textContent='';
  if(kind==='reels'){await loadReels(epoch);return;}
  const value=await api(`${kind==='enquiries'?enquiries:comments+'/'+kind}?${params}`);
  if(epoch!==listEpoch||kind!==tab)return;
  if(!Array.isArray(value?.items)||value.items.length>20||typeof value.can_manage!=='boolean'||!(value.next_cursor===null||typeof value.next_cursor==='string'))throw Error('The saved list could not be verified.');
  if(value.items.some(row=>kind==='rules'?!validRule(row):kind==='events'?!validEvent(row):!validEnquiry(row)))throw Error('The saved list contains an unconfirmed result.');
  $('records').replaceChildren();rules.clear();nextCursor=value.next_cursor;
  for(const row of value.items){const article=node('article',undefined,'record'),facts=node('div'),actions=node('div',undefined,'record-actions');
    if(kind==='rules'){rules.set(row.id,row);facts.append(node('h3',row.name),node('p',row.enabled?'Saved as enabled · current sending checks still apply':'Disabled'),node('small',`Post reference: ${row.media_id||'Not explicitly linked'} · Keywords: ${row.keywords.join(', ')}`));if(canManage){actions.append(button('Edit rule',()=>editRule(row),true));if(row.media_id)actions.append(button('Preview only',()=>preview(row),true));}}
    else if(kind==='events'){facts.append(node('h3',row.text||'Comment with no text'),node('p',row.actions.length?row.actions.map(action=>`${action.kind==='private'?'Private':'Public'} reply: ${delivery(action.delivery_state)}`).join('\n'):'No reply action is saved here.','status-line'),node('small',row.reason?explain(row.reason):row.eligibility_reason?explain(row.eligibility_reason):'Saved comment activity'));actions.append(button(row.review?'View review':'Review comment',()=>openDetail(row.id,'events')));}
    else{facts.append(node('h3',row.customer_name||`Customer •${row.customer_ref}`),node('p',row.message),node('small',explain(row.reason)));actions.append(button(row.review?'View review':'Review enquiry',()=>openDetail(row.id,'enquiries')));}
    if(kind!=='rules')facts.append(node('small',`${date(row.created_at)}${row.review?' · Closed after review':''}`));article.append(facts,actions);$('records').append(article);
  }
  $('list-state').textContent=value.items.length?'':kind==='enquiries'?'No inferred follow-ups need review in this view.':kind==='rules'?'No comment rules yet. Start with a specific Instagram post and product.':'No saved comments match this view.';
  $('previous').disabled=pages.length===0;$('next').disabled=!nextCursor;$('page-label').textContent=`Page ${pages.length+1}`;viewReady=true;controls();
}
async function load(){try{await loadCurrent();}catch(error){invalidateReads();throw error;}}
async function openDetail(id,kind){
  const epoch=++selectionEpoch,row=await api(`${kind==='events'?comments+'/events':enquiries}/${id}`);if(epoch!==selectionEpoch)return;
  if(row.id!==id||!(kind==='events'?validEvent(row):validEnquiry(row)))throw Error('The selected review could not be verified.');
  selected={...row,kind};$('detail-title').textContent=kind==='events'?'Review comment':'Review WhatsApp enquiry';$('detail-meta').textContent=`${date(row.created_at)}${kind==='events'?` · Post reference: ${row.media_id}`:''}`;$('detail-content').replaceChildren();
  $('detail-content').append(node('p',kind==='events'?row.text:`${row.customer_name||'Customer'} •${row.customer_ref}\n${row.message}`));
  for(const action of row.actions||[]){const section=node('section',undefined,'delivery');section.append(node('strong',`${action.kind==='private'?'Private':'Public'} reply · ${delivery(action.delivery_state)}`),node('p',action.body));if(action.reason)section.append(node('small',explain(action.reason)));$('detail-content').append(section);}
  if(row.review)$('detail-content').append(node('p',`Closed after review · ${date(row.review.created_at)}\n${row.review.reason}\nThe original delivery result is unchanged.`));
  $('detail-block').textContent=kind==='enquiries'?explain(row.reason):row.can_close?'Check the original conversation. Closing records this review and sends nothing.':'This item is already reviewed, still running, or your role cannot close it. Its send result remains unchanged.';
  $('review-form').reset();$('review-error').textContent='';controls();$('detail-dialog').showModal();
}
async function send(){
  if(!intent||busy||ended||journalBlocked)return;busy=true;renderIntent();$('error').textContent='';const saved=intent;
  try{const value=await api(saved.path,{method:saved.method,body:saved.body});if(saved!==intent||!validReceipt(value,saved))throw Error('The exact saved action was not confirmed. Keep it and check again.');
    if(saved.operation.startsWith('rule_')){const row=await api(`${comments}/rules/${value.result.resource_id}`);if(!validRule(row)||row.id!==value.result.resource_id||row.fingerprint!==value.result.fingerprint||(saved.operation==='rule_disable'?row.enabled!==false:stable(Object.fromEntries(Object.keys(saved.body.facts).map(key=>[key,row[key]])))!==stable(saved.body.facts)))throw Error('The accepted rule and current rule do not match. Keep the saved action and inspect history.');}
    else{const row=await api(`${saved.operation==='comment_close'?comments+'/events':enquiries}/${saved.resource}`);if(row.id!==saved.resource||!row.review)throw Error('The review result could not be confirmed. Keep the saved action.');}
    if(saved!==intent)throw Error('The saved action changed.');sessionStorage.removeItem(storageKey);intent=null;renderIntent();for(const dialog of document.querySelectorAll('dialog'))if(dialog.open)dialog.close();selected=null;editing=null;
    $('notice').textContent=saved.operation.startsWith('rule_')?'Rule change confirmed. Earlier saved replies were not replayed.':'Review recorded. No new reply was sent; the original delivery result is unchanged.';await load();
  }catch(error){if(!ended&&error.code==='comment_operator_context_changed'){sessionStorage.removeItem(storageKey);intent=null;renderIntent();$('notice').textContent='This action was not accepted. Refresh and review the current facts before deciding again.';}if(!ended){invalidateReads();$('error').textContent=error.message;}}
  finally{busy=false;renderIntent();}
}
async function command(operation,resource,path,method,body,summary){if(busy||intent||reelIntent||ended||journalBlocked||!viewReady)return;busy=true;controls();let ready=false;try{await session(true);await prepare(operation,resource,path,method,body,summary);ready=true;}catch(error){if(!ended)$('error').textContent=error.message;}finally{busy=false;controls();}if(ready)await send();}
async function loadProducts(){
  const value=await api(`${comments}/products${productCursor?'?cursor='+encodeURIComponent(productCursor):''}`);
  if(!Array.isArray(value?.items)||value.items.some(row=>!UUID.test(row.id)||typeof row.name!=='string'||typeof row.activated!=='boolean'))throw Error('The product list could not be verified.');
  for(const row of value.items){if(products.has(row.id))throw Error('The product list changed. Reload before selecting a product.');products.set(row.id,row);const option=node('option',`${row.name}${row.activated?' · static replies unavailable':''}`);option.value=row.id;$('rule-product').append(option);}
  productsStarted=true;productCursor=value.next_cursor;$('more-products').hidden=!productCursor;
}
async function editRule(row=null){
  const epoch=++selectionEpoch;await session(true);if(epoch!==selectionEpoch)return;
  if(!productsStarted)await loadProducts();if(epoch!==selectionEpoch)return;
  editing=row;$('rule-form').reset();$('rule-title').textContent=row?'Edit comment rule':'Create comment rule';$('rule-error').textContent='';
  if(row){for(const [key,id] of Object.entries({name:'rule-name',media_id:'rule-media',product_id:'rule-product',private_reply:'rule-private',public_reply:'rule-public'}))$(id).value=row[key]||'';$('rule-keywords').value=row.keywords.join(', ');$('rule-enabled').checked=row.enabled;}
  $('disable-rule').hidden=!row;controls();$('rule-dialog').showModal();
}
async function preview(row){const epoch=++selectionEpoch;await session(true);if(epoch!==selectionEpoch)return;previewRule=row;$('preview-form').reset();$('preview-result').textContent='A preview checks a saved rule. It never sends a reply.';$('preview-dialog').showModal();}
function invalidateReads(){if(ended)return;viewReady=false;selectionEpoch++;listEpoch++;selected=null;editing=null;previewRule=null;rules.clear();products.clear();productsStarted=false;productCursor=null;nextCursor=null;
  for(const id of ['records','detail-meta','detail-content','detail-block','preview-result','page-label','reel-meta','reel-message','reel-source','reel-eligibility','reel-error'])$(id).replaceChildren();
  for(const dialog of document.querySelectorAll('dialog'))if(dialog.open)dialog.close();for(const form of document.querySelectorAll('form'))form.reset();
  $('rule-product').replaceChildren(node('option','Choose a product'));$('rule-product').firstElementChild.value='';$('list-state').textContent='Current activity could not be checked. Refresh before starting another action.';$('previous').disabled=true;$('next').disabled=true;controls();
  $('reel-product').replaceChildren(node('option','Choose a product'));$('reel-product').firstElementChild.value='';
}
const reelSourceNames={message_link:'Explicit message link',referral_link:'Explicit referral link',quoted_message:'Quoted message reference',recent_message:'Inferred follow-up',unknown:'Reference needs review'};
function clearReelDetail(){if(selected?.kind==='reels')selected=null;for(const id of ['reel-meta','reel-message','reel-source','reel-eligibility','reel-error'])$(id).replaceChildren();$('reel-form').reset();$('reel-product').replaceChildren();}
function reelReason(reason){return ({inferred_context:'This follow-up is inferred. Link only; no reply can be requested.',activated_inferred_context:'This follow-up is inferred. Link only; no reply can be requested.',resume_not_requested:'No reply was requested.',reply_window_closed:'The reply window has closed.',opted_out:'This customer has opted out.',automation_paused:'Automated replies are paused.',newer_customer_message:'A newer customer message needs review.',reply_already_attempted:'A reply was already claimed or attempted. Its result is unchanged.',account_changed:'The receiving account changed. Refresh before deciding.',product_busy:'This product is being edited. Refresh and review again.'})[reason]||explain(reason);}
function renderReelIntent(){$('reel-recovery').hidden=!reelIntent;$('reel-recovery-summary').textContent=reelIntent?.summary||'';controls();}
async function recoverReel(){
  const g=generation;let raw;try{raw=sessionStorage.getItem(reelStorageKey);}catch{journalBlocked=true;throw Error('Saved link actions cannot be checked. No new action will be sent.');}
  if(!raw)return;
  try{if(raw.length>10000)throw Error();const saved=JSON.parse(raw),claimed=saved.digest;delete saved.digest;
    if(Object.keys(saved).sort().join(',')!==['format','user','business','session_scope','at','operation','resource','path','method','body','summary','request_hash'].sort().join(',')||saved.format!==1||saved.user!==identity.split(':')[0]||saved.business!==business||saved.session_scope!==sessionScope||!Number.isFinite(saved.at)||saved.at>Date.now()+60000||Date.now()-saved.at>86400000||!validReelIntent(saved,business)||claimed!==await digest(saved)||saved.request_hash!==await digest({business_id:business,inbound_id:saved.resource,body:saved.body}))throw Error();
    current(g);reelIntent={...saved,digest:claimed};renderReelIntent();
  }catch{journalBlocked=true;controls();throw Error('The saved link action cannot be verified. Review its history before starting another action.');}
}
async function loadReels(epoch){
  viewReady=false;selectionEpoch++;selected=null;$('reel-dialog').close();$('reel-form').reset();$('reel-product').replaceChildren();for(const id of ['records','reel-meta','reel-message','reel-source','reel-eligibility','reel-error'])$(id).replaceChildren();controls();
  const params=new URLSearchParams({limit:'20'});if(cursor)params.set('cursor',cursor);
  const value=await api(`${reelEnquiries}?${params}`);if(epoch!==listEpoch||tab!=='reels')return;
  if(!value||Object.keys(value).sort().join(',')!=='can_manage,items,next_cursor'||!Array.isArray(value.items)||value.items.length>20||typeof value.can_manage!=='boolean'||!(value.next_cursor===null||typeof value.next_cursor==='string'&&value.next_cursor.length<=2048)||value.items.some(row=>!validReelDetail(row,business)))throw Error('The enquiry list could not be verified.');
  $('records').replaceChildren();rules.clear();nextCursor=value.next_cursor;
  for(const row of value.items){const article=node('article',undefined,'record'),facts=node('div'),actions=node('div',undefined,'record-actions');facts.append(node('h3',row.customer_name||`Customer •${row.customer_ref}`),node('p',row.message),node('small',`${date(row.received_at)} · ${reelSourceNames[row.source.classification]}`),node('small',row.eligibility.reason?reelReason(row.eligibility.reason):'Review this exact reel and select a product.'));actions.append(button('Review product link',()=>openReel(row.inbound_id)));article.append(facts,actions);$('records').append(article);}
  $('list-state').textContent=value.items.length?'':'No unresolved reel references need review in this view.';$('previous').disabled=pages.length===0;$('next').disabled=!nextCursor;$('page-label').textContent=`Page ${pages.length+1}`;viewReady=true;controls();
}
async function openReel(inbound){
  const epoch=++selectionEpoch,row=await api(`${reelEnquiries}/${inbound}`);if(epoch!==selectionEpoch)return;
  if(row.inbound_id!==inbound||!validReelDetail(row,business))throw Error('The selected enquiry could not be verified.');
  selected={...row,kind:'reels'};$('reel-form').reset();$('reel-confirm').checked=false;$('reel-error').textContent='';
  $('reel-meta').textContent=`${row.customer_name||'Customer'} · •${row.customer_ref} · Account ${row.account_hint} · ${date(row.received_at)}`;
  $('reel-message').replaceChildren(node('p',row.message));$('reel-source').textContent=`${reelSourceNames[row.source.classification]}${row.source.url?' · '+row.source.url:''}`;
  $('reel-eligibility').textContent=row.eligibility.reason?reelReason(row.eligibility.reason):'Review the exact source and product. Sending eligibility is checked again before dispatch.';
  const placeholder=node('option','Choose a product');placeholder.value='';$('reel-product').replaceChildren(placeholder);
  for(const product of row.products){const option=node('option',product.name);option.value=product.id;$('reel-product').append(option);}
  $('reel-product').value='';controls();$('reel-dialog').showModal();
}
async function prepareReel(action){
  if(busy||intent||reelIntent||ended||journalBlocked||!viewReady)return;
  const row=selected,product=$('reel-product').value;if(row?.kind!=='reels'||!row.can_manage||!row.eligibility.can_link||!$('reel-confirm').checked||!row.products.some(item=>item.id===product)||action==='link_and_resume'&&!row.eligibility.can_resume)return;
  busy=true;controls();let ready=false;const g=generation;
  try{await session(true);current(g);if(selected!==row)throw Error('The selected enquiry changed. Review it again.');
    const body={idempotency_key:crypto.randomUUID(),action,product_id:product,shortcode:row.source.shortcode,expected_fingerprint:row.fingerprint,expected_connection_version:row.connection_version,confirmed:true};
    const saved={format:1,user:identity.split(':')[0],business,session_scope:sessionScope,at:Date.now(),operation:'reel_link',resource:row.inbound_id,path:`${reelEnquiries}/${row.inbound_id}/link`,method:'POST',body,summary:`${action==='link_only'?'Link only':'Link and request one eligible reply'} · ${row.products.find(item=>item.id===product).name}\nReel ${body.shortcode} · One selected enquiry`.slice(0,1000)};
    saved.request_hash=await digest({business_id:business,inbound_id:saved.resource,body});saved.digest=await digest(saved);current(g);
    if(!validReelIntent(saved,business))throw Error('The exact link action could not be verified. Nothing was sent.');
    const raw=JSON.stringify(saved);try{sessionStorage.setItem(reelStorageKey,raw);if(sessionStorage.getItem(reelStorageKey)!==raw)throw Error();}catch{throw Error('Session storage is unavailable. No action was sent.');}
    current(g);reelIntent=saved;ready=true;renderReelIntent();
  }catch(error){if(!ended)$('reel-error').textContent=error.message;}finally{busy=false;controls();}
  if(ready)await sendReel();
}
async function sendReel(){
  if(!reelIntent||busy||ended||journalBlocked)return;busy=true;renderReelIntent();const saved=reelIntent;
  try{const value=await api(saved.path,{method:saved.method,body:saved.body});if(saved!==reelIntent||!validReelReceipt(value,saved))throw Error('The exact saved link action was not confirmed. Keep it and check again.');
    sessionStorage.removeItem(reelStorageKey);reelIntent=null;renderReelIntent();selected=null;$('reel-dialog').close();
    $('notice').textContent=value.result.resume==='queued'?'Mapping saved. One reply was queued for current sending checks; delivery is not confirmed.':value.result.resume==='held'?`Mapping saved. No reply was queued. ${reelReason(value.result.reason)}`:'Mapping saved. No reply was requested.';await load();
  }catch(error){if(!ended&&saved===reelIntent&&validReelRejection(error,saved)){sessionStorage.removeItem(reelStorageKey);reelIntent=null;renderReelIntent();$('notice').textContent='This link action was not accepted. Refresh and review the current facts.';}if(!ended){invalidateReads();$('error').textContent=error.message;}}
  finally{busy=false;renderReelIntent();}
}
function onError(error){if(!ended){invalidateReads();$('error').textContent=error.message;}}
$('review-form').addEventListener('submit',event=>{event.preventDefault();if(!selected||!$('review-confirm').checked)return;const row=selected,operation=row.kind==='events'?'comment_close':'enquiry_close';command(operation,row.id,row.kind==='events'?`${comments}/events/${row.id}/reviews`:`${enquiries}/${row.id}/close`,'POST',{idempotency_key:crypto.randomUUID(),expected_fingerprint:row.fingerprint,confirmed:true,reason:$('review-reason').value.trim()},`Close review without send · ${row.kind==='events'?row.text:row.message}`.slice(0,1000)).catch(onError);});
$('rule-form').addEventListener('submit',event=>{event.preventDefault();const row=editing,facts={name:$('rule-name').value.trim(),enabled:$('rule-enabled').checked,media_id:$('rule-media').value.trim(),product_id:$('rule-product').value,keywords:[...new Set($('rule-keywords').value.split(',').map(value=>value.trim()))],private_reply:$('rule-private').value.trim(),public_reply:$('rule-public').value.trim()||null};if(!validFacts(facts)){ $('rule-error').textContent='Check the explicit post, product and bounded reply fields.';return;}command(row?'rule_update':'rule_create',row?.id||null,`${comments}/rules${row?'/'+row.id:''}`,row?'PUT':'POST',{idempotency_key:crypto.randomUUID(),facts,expected_fingerprint:row?.fingerprint||null},`${row?'Update':'Create'} rule · ${facts.name}\nPost ${facts.media_id} · ${products.get(facts.product_id)?.name||'Selected product'}\n${facts.enabled?'Enable future matches':'Keep disabled'}`).catch(onError);});
$('disable-rule').addEventListener('click',()=>{if(editing)command('rule_disable',editing.id,`${comments}/rules/${editing.id}/disable`,'POST',{idempotency_key:crypto.randomUUID(),expected_fingerprint:editing.fingerprint},`Disable rule · ${editing.name}`).catch(onError);});
$('preview-form').addEventListener('submit',async event=>{event.preventDefault();if(!previewRule||busy)return;const epoch=selectionEpoch,row=previewRule;try{const value=await api(`${comments}/preview`,{method:'POST',body:{rule_id:row.id,text:$('preview-text').value,media_id:row.media_id}});if(epoch!==selectionEpoch||previewRule!==row)return;if(value?.sends!==false||typeof value.matches!=='boolean')throw Error('The preview could not be verified.');$('preview-result').textContent=`${value.matches?'Keyword and post match':'No keyword/post match'}\n${value.withheld_reason?explain(value.withheld_reason):'Eligibility still depends on the actual incoming comment and current checks.'}\nPrivate copy: ${value.private_reply}\n${value.public_reply?'Public copy: '+value.public_reply:''}\nNo message was sent.`;}catch(error){if(!ended)$('preview-result').textContent=error.message;}});
for(const id of ['detail','rule','preview','reel'])$(id+'-close').addEventListener('click',()=>{selectionEpoch++;$(id+'-dialog').close();if(id==='reel'){clearReelDetail();controls();}});
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{if(busy||ended)return;clearReelDetail();tab=button.dataset.tab;cursor=null;pages=[];selectionEpoch++;selected=null;$('filter-label').hidden=tab==='rules'||tab==='reels';$('list-heading').textContent=tab==='events'?'Review saved comment replies':tab==='rules'?'Rules for specific posts':tab==='reels'?'Review one product enquiry':'Follow-ups needing a person';$('list-description').textContent=tab==='reels'?'Choose one message. A shared product link can inform future enquiries; a reply request applies only to the message you review.':tab==='enquiries'?'Inferred context is only a suggestion. Review here sends no customer message.':tab==='rules'?'Save or preview a static rule. Activated catalogue products remain withheld.':'A provider receipt confirms acceptance, not delivery. Reviewing never sends another reply.';document.querySelectorAll('[data-tab]').forEach(item=>item===button?item.setAttribute('aria-current','page'):item.removeAttribute('aria-current'));controls();load().catch(onError);}));
$('reel-link-only').addEventListener('click',()=>prepareReel('link_only'));
$('reel-resume').addEventListener('click',()=>prepareReel('link_and_resume'));
$('reel-confirm').addEventListener('change',controls);
$('reel-product').addEventListener('change',()=>{$('reel-confirm').checked=false;controls();});
$('reel-retry').addEventListener('click',sendReel);
$('reel-form').addEventListener('submit',event=>event.preventDefault());
$('new-rule').addEventListener('click',()=>editRule().catch(onError));$('more-products').addEventListener('click',()=>loadProducts().catch(onError));$('retry').addEventListener('click',send);
$('refresh').addEventListener('click',()=>load().catch(onError));$('state').addEventListener('change',()=>{cursor=null;pages=[];load().catch(onError);});
$('next').addEventListener('click',()=>{if(nextCursor){pages.push(cursor);cursor=nextCursor;load().catch(onError);}});$('previous').addEventListener('click',()=>{if(pages.length){cursor=pages.pop();load().catch(onError);}});
let checking=false;async function refocus(){if(ended||checking||!identity)return;checking=true;$('workspace').hidden=true;try{await session();}catch(error){onError(error);}finally{checking=false;if(!ended&&!document.hidden)$('workspace').hidden=false;}}
window.addEventListener('focus',refocus);window.addEventListener('pageshow',refocus);window.addEventListener('pagehide',()=>{$('workspace').hidden=true;});document.addEventListener('visibilitychange',()=>{if(document.hidden)$('workspace').hidden=true;else refocus();});
(async()=>{try{if(!UUID.test(business))throw Error('Open comments from an authorized business.');const g=generation,me=await session();sessionScope=await digest(me.csrf_token);storageKey=prefix+me.user_id+':'+business+':'+sessionScope;reelStorageKey=reelPrefix+me.user_id+':'+business+':'+sessionScope;current(g);try{await recover();await recoverReel();}catch(error){onError(error);}const overview=await api(comments);if(overview.business_id!==business||typeof overview.business_name!=='string')throw Error('This business could not be verified.');$('business-name').textContent=overview.business_name;$('back').href=`/v1?business=${encodeURIComponent(business)}`;$('readiness').textContent=overview.readiness_reason?explain(overview.readiness_reason):'Local account access is checked. Provider permissions and real delivery are not certified here.';await load();current(g);$('workspace').hidden=false;controls();}catch(error){onError(error);}})();
