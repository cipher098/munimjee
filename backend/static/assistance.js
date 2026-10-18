/* Existing memberships only. Commands survive an unknown response, never sign-ins. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), rawApi=window.V1.api;
  const PREFIX='munimjee.v1.assistance-command:', UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const exact=(x,keys)=>object(x)&&Object.keys(x).length===keys.length&&keys.every(k=>Object.hasOwn(x,k));
  const failure=message=>new Error(message);
  let identity=null, ended=false, selected=null, detail=null, pending=null, corrupt=false, authority=[];
  let pageEpoch=0, detailEpoch=0, busy=false, checking=false, recheckPending=false, page=null, cursors=[null], pageIndex=0;
  let requested=location.pathname.match(/^\/v1\/businesses\/([a-f0-9-]+)\/assistance$/i)?.[1]||null;
  const fingerprint=async value=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(v=>v.toString(16).padStart(2,'0')).join('');
  function eraseCommands() {
    try {for(let i=sessionStorage.length-1;i>=0;i--){const key=sessionStorage.key(i);if(key?.startsWith(PREFIX))sessionStorage.removeItem(key);}}catch(_){}
  }
  function end(message,clear=true) {
    if(ended)return;ended=true;pageEpoch++;detailEpoch++;if(clear)eraseCommands();
    identity=null;selected=null;detail=null;page=null;pending=null;corrupt=false;authority=[];
    for(const id of ['business-list','steps','checks','assignee'])$(id).replaceChildren();
    for(const id of ['business-heading','business-intro','lead-name','lead-help','recovery-message','recovery-error','notice','page-label'])$(id).textContent='';
    $('assignment-reviewed').checked=false;$('private-content').hidden=true;$('detail-content').hidden=true;
    $('assignment-form').hidden=true;$('recovery').hidden=true;$('loading').textContent='';
    $('global-error').textContent=message;$('session-ended').hidden=false;$('logout').hidden=true;
  }
  function cookieMatches() {
    if(!identity)return true;
    try{return document.cookie.split(';').map(s=>s.trim()).some(s=>s.startsWith('v1_csrf=')&&decodeURIComponent(s.slice(8))===identity.csrf);}catch(_){return false;}
  }
  async function session() {
    if(ended)throw failure('Your sign-in ended.');
    if(!cookieMatches()){end('Your sign-in changed. Reopen onboarding after signing in.');throw failure('Your sign-in changed.');}
    let value;
    try{value=await rawApi('/api/v1/auth/session');}catch(error){if(error.status===401)end('Your sign-in ended. Reopen onboarding after signing in.');throw error;}
    if(ended)throw failure('Your sign-in ended.');
    if(!cookieMatches()){end('Your sign-in changed. Reopen onboarding after signing in.');throw failure('Your sign-in changed.');}
    if(!UUID.test(value?.user_id)||typeof value.csrf_token!=='string'||!value.csrf_token||!Array.isArray(value.businesses))throw failure('Your current sign-in could not be checked.');
    const hash=await fingerprint(value.csrf_token);
    if(ended)throw failure('Your sign-in ended.');
    if(!cookieMatches()){end('Your sign-in changed. Reopen onboarding after signing in.');throw failure('Your sign-in changed.');}
    if(identity&&(identity.user!==value.user_id||identity.hash!==hash)){end('Your sign-in changed. Reopen onboarding after signing in.');throw failure('Your sign-in changed.');}
    if(!identity)identity={user:value.user_id,hash,csrf:value.csrf_token};
    authority=value.businesses;
    if(page){
      page.items=page.items.filter(item=>authority.some(b=>b.id===item.business_id&&b.capabilities?.includes('readiness.read')));
      renderList();
    }
    if(selected&&!value.businesses.some(b=>b.id===selected&&b.capabilities?.includes('readiness.read'))){end('Your business access changed. Reopen onboarding with your current access.');throw failure('Your access changed.');}
    if(detail&&!value.businesses.find(b=>b.id===selected)?.capabilities?.includes('members.manage')){
      detail.can_assign=false;$('assignee').replaceChildren();$('assignment-form').hidden=true;
      $('lead-help').textContent='A business owner can assign an existing owner or manager as the onboarding lead.';
    }
    if(detail){detail.role=authority.find(b=>b.id===selected).role;$('business-intro').textContent=`Your access: ${detail.role}. Actions use your own account.`;}
    if(detail&&!value.businesses.find(b=>b.id===selected)?.capabilities?.includes('business.write')){
      detail.steps=detail.steps.map(step=>step.id==='payments'?{...step,action_url:null}:step);
      $('steps').querySelectorAll('a[href$="/payments"]').forEach(link=>link.remove());
    }
    return value;
  }
  async function api(path,options={}) {
    await session();if(ended)throw failure('Your sign-in ended.');
    if(!cookieMatches()){end('Your sign-in changed. Reopen onboarding after signing in.');throw failure('Your sign-in changed.');}
    let result;
    try{result=await rawApi(path,{...options,redirect:'error'});}catch(error){if(error.status===401)end('Your sign-in ended. Reopen onboarding after signing in.');throw error;}
    await session();if(ended)throw failure('Your sign-in ended.');return result;
  }
  function key(bid){return PREFIX+identity.user+':'+bid+':'+identity.hash;}
  function validBody(operation,body) {
    return operation==='open'?exact(body,['idempotency_key'])&&UUID.test(body.idempotency_key):operation==='assignment'&&
      exact(body,['idempotency_key','expected_version','assignee_user_id','reviewed'])&&UUID.test(body.idempotency_key)&&
      Number.isInteger(body.expected_version)&&body.expected_version>=0&&body.expected_version<=2000000000&&
      (body.assignee_user_id===null||UUID.test(body.assignee_user_id))&&body.reviewed===true;
  }
  function readIntent(bid) {
    pending=null;corrupt=false;
    let raw;try{raw=sessionStorage.getItem(key(bid));}catch(_){corrupt=true;return;}
    if(raw===null)return;
    try{
      if(raw.length>4096)throw failure('Invalid recovery');const x=JSON.parse(raw),created=Date.parse(x.created_at);
      if(!exact(x,['version','user_id','business_id','session_fingerprint','created_at','operation','body'])||x.version!==1||x.user_id!==identity.user||x.business_id!==bid||x.session_fingerprint!==identity.hash||!Number.isFinite(created)||created>Date.now()+5000||Date.now()-created>7*86400000||!validBody(x.operation,x.body))throw failure('Invalid recovery');
      pending=x;
    }catch(_){corrupt=true;}
  }
  function persist(command) {
    const encoded=JSON.stringify(command),storageKey=key(command.business_id);
    try{sessionStorage.setItem(storageKey,encoded);if(sessionStorage.getItem(storageKey)!==encoded)throw failure('Storage failed');}
    catch(_){throw failure('Enable browser session storage before saving an action. No new action was sent.');}
  }
  function clear(command) {
    const storageKey=key(command.business_id),stored=sessionStorage.getItem(storageKey);
    if(stored!==JSON.stringify(command))throw failure('Recovery details changed. Keep this action for review.');
    sessionStorage.removeItem(storageKey);if(sessionStorage.getItem(storageKey)!==null)throw failure('The saved action could not be cleared.');
  }
  function validBusiness(x) {
    return x?.contract_version==='assistance-business.v1'&&UUID.test(x.business_id)&&typeof x.name==='string'&&
      ['owner','manager','staff','viewer'].includes(x.role)&&typeof x.can_assign==='boolean'&&Number.isInteger(x.assignment?.version)&&
      x.assignment.version>=0&&(x.assignment.assignee_user_id===null||UUID.test(x.assignment.assignee_user_id))&&
      typeof x.assignment.eligible==='boolean'&&Array.isArray(x.steps)&&x.steps.length===6&&Array.isArray(x.channel_checks)&&
      x.onboarding_complete===false&&x.steps.every(s=>['ready_local','action_required','pending_external'].includes(s.status)&&typeof s.label==='string'&&typeof s.reason==='string'&&(s.action_url===null||safeLink(s.action_url,x.business_id)));
  }
  function safeLink(value,bid) {
    if(typeof value!=='string')return false;
    if(value===`/v1?business=${bid}#profile`)return true;
    return ['imports','catalogue','channels','payments'].some(s=>value===`/v1/businesses/${bid}/${s}`);
  }
  function sync() {
    $('private-content').hidden=ended||!identity||document.hidden||checking;
    $('refresh').disabled=busy||checking||ended;$('filter').disabled=busy||checking||ended;
    $('previous').disabled=busy||pageIndex===0;$('next').disabled=busy||!page?.next_after;
    $('save-assignment').disabled=busy||Boolean(pending)||corrupt||!detail?.can_assign;
    $('assignee').disabled=busy||Boolean(pending)||corrupt;$('assignment-reviewed').disabled=busy||Boolean(pending)||corrupt;
    $('retry').disabled=busy||!pending||corrupt||(pending?.operation==='assignment'&&!detail?.can_assign);
    $('recovery').hidden=!pending&&!corrupt;
    $('recovery-message').textContent=corrupt?'This browser has incomplete recovery details. No new assignment can be sent from this page. Reopen this business with your owner to review its current lead.':pending?.operation==='assignment'?'The earlier lead assignment may have saved. Check it again using the same reviewed action before starting another.':'The earlier workspace opening may have saved. Check the same action again to confirm its audit entry.';
  }
  function renderList() {
    $('business-list').replaceChildren();$('business-empty').hidden=page.items.length!==0;
    for(const item of page.items){const li=document.createElement('li'),button=document.createElement('button'),name=document.createElement('span'),small=document.createElement('small');button.type='button';button.className='business-choice';name.textContent=item.name;small.textContent=item.assignment.eligible?`Lead: ${item.assignment.display_name||'Assigned team member'}`:item.assignment.assignee_user_id?'Lead needs reassignment':'No onboarding lead';button.append(name,small);button.setAttribute('aria-current',item.business_id===selected?'true':'false');button.addEventListener('click',()=>openBusiness(item.business_id));li.append(button);$('business-list').append(li);}
    $('page-label').textContent=`Page ${pageIndex+1}`;sync();
  }
  function renderDetail() {
    $('business-heading').textContent=detail.name;$('business-intro').textContent=`Your access: ${detail.role}. Actions use your own account.`;
    $('lead-name').textContent=detail.assignment.eligible?(detail.assignment.display_name||'Assigned team member'):detail.assignment.assignee_user_id?'The assigned person is no longer an active owner or manager.':'No onboarding lead assigned.';
    $('lead-help').textContent=detail.can_assign?'Choose an owner or manager already on this business team. Assigning a lead does not grant any access.':'A business owner can assign an existing owner or manager as the onboarding lead.';
    $('steps').replaceChildren();
    for(const step of detail.steps){const li=document.createElement('li'),heading=document.createElement('h4'),status=document.createElement('span'),reason=document.createElement('p');heading.textContent=step.label;status.className='step-status';status.textContent={ready_local:'Saved locally',action_required:'Needs action',pending_external:'Live check pending'}[step.status];heading.append(status);reason.textContent=step.reason;li.append(heading,reason);if(step.action_url){const link=document.createElement('a');link.href=step.action_url;link.textContent=`Open ${step.label.toLowerCase()}`;li.append(link);}$('steps').append(li);}
    $('checks').replaceChildren();
    for(const channel of ['instagram','whatsapp']){const row=detail.channel_checks.find(c=>c.channel===channel),li=document.createElement('li');li.textContent=`${channel==='instagram'?'Instagram':'WhatsApp'}: ${row?.checked_at?`local check recorded ${new Date(row.checked_at).toLocaleString()}`:'no local check recorded'}. Provider approval not evaluated.`;$('checks').append(li);}
    $('detail-content').hidden=false;$('assignee').replaceChildren();$('assignment-reviewed').checked=false;$('assignment-form').hidden=true;sync();
  }
  async function loadDetail(bid,epoch) {
    const result=await api(`/api/v1/businesses/${bid}/assistance`);
    if(ended||epoch!==detailEpoch||selected!==bid)return;
    if(!validBusiness(result)||result.business_id!==bid)throw failure('The business details could not be verified.');
    const current=authority.find(b=>b.id===bid);
    result.role=current.role;result.can_assign=result.can_assign&&current.capabilities.includes('members.manage');
    if(!current.capabilities.includes('business.write'))result.steps=result.steps.map(step=>step.id==='payments'?{...step,action_url:null}:step);
    detail=result;readIntent(bid);renderDetail();
    if(!detail.can_assign)return;
    const candidates=await api(`/api/v1/businesses/${bid}/assistance/assignees`);
    if(ended||epoch!==detailEpoch||selected!==bid||!detail.can_assign)return;
    if(candidates?.business_id!==bid||!Array.isArray(candidates.items)||!candidates.items.every(c=>UUID.test(c.user_id)&&typeof c.label==='string'&&['owner','manager'].includes(c.role)))throw failure('The current team list could not be verified.');
    $('assignee').replaceChildren();const empty=document.createElement('option');empty.value='';empty.textContent='No lead assigned';$('assignee').append(empty);
    for(const candidate of candidates.items){const option=document.createElement('option');option.value=candidate.user_id;option.textContent=`${candidate.label} (${candidate.role})`;$('assignee').append(option);}
    $('assignee').value=detail.assignment.eligible?detail.assignment.assignee_user_id||'':'';$('assignment-form').hidden=false;sync();
  }
  async function loadBoard() {
    if(ended)return;const epoch=++pageEpoch;$('loading').textContent='Loading your businesses…';$('global-error').textContent='';
    try{const query=new URLSearchParams({limit:'20',assigned_to_me:String($('filter').value==='mine')});if(cursors[pageIndex])query.set('after',cursors[pageIndex]);const result=await api('/api/v1/assistance/businesses?'+query);
      if(ended||epoch!==pageEpoch)return;
      if(result?.contract_version!=='assistance-page.v1'||!Array.isArray(result.items)||result.items.length>20||!result.items.every(validBusiness)||(result.next_after!==null&&!UUID.test(result.next_after)))throw failure('Your business list could not be verified.');
      result.items=result.items.filter(item=>authority.some(b=>b.id===item.business_id&&b.capabilities?.includes('readiness.read')));
      page=result;renderList();if(requested){const bid=requested;requested=null;await openBusiness(bid);}
    }catch(error){if(!ended&&epoch===pageEpoch){$('global-error').textContent=error.message||'Your businesses could not be loaded.';}}
    finally{if(!ended&&epoch===pageEpoch){$('loading').textContent='';sync();}}
  }
  async function send(command,epoch) {
    const bid=command.business_id,operation=command.operation;
    try{const result=await api(`/api/v1/businesses/${bid}/assistance/${operation==='open'?'open':'assignment'}`,{method:operation==='open'?'POST':'PUT',body:command.body});
      if(result?.contract_version!=='assistance-command.v1'||result.business_id!==bid||result.idempotency_key!==command.body.idempotency_key||result.operation!==operation||result.workspace_url!==`/v1/businesses/${bid}/assistance`||typeof result.replayed!=='boolean'||(operation==='assignment'&&(result.assignee_user_id!==command.body.assignee_user_id||result.version!==command.body.expected_version+1)))throw failure('The action response could not be verified. Keep the saved action and check it again.');
      clear(command);
      if(ended||epoch!==detailEpoch||selected!==bid)return;
      pending=null;corrupt=false;await loadDetail(bid,epoch);
      if(ended||epoch!==detailEpoch||selected!==bid)return;
      $('notice').textContent=operation==='assignment'?'Lead assignment confirmed. Current business details are shown below.':'Workspace opening recorded under your own account.';
    }catch(error){if(ended)return;
      if(error.status===409&&error.code==='assistance_assignment_stale'){
        clear(command);if(epoch!==detailEpoch||selected!==bid)return;pending=null;await loadDetail(bid,epoch);if(epoch===detailEpoch)$('notice').textContent='The lead changed before this action could save. Review the current assignment before choosing again.';
      }else if(epoch===detailEpoch&&selected===bid){$('recovery-error').textContent=error.message||'The action result is unknown. Check the saved action again.';}
    }
  }
  async function openBusiness(bid) {
    if(ended||busy||!UUID.test(bid))return;
    const epoch=++detailEpoch;selected=bid;detail=null;pending=null;corrupt=false;busy=true;
    $('detail-content').hidden=true;$('assignee').replaceChildren();$('business-heading').textContent='Opening business…';$('business-intro').textContent='';$('notice').textContent='';$('recovery-error').textContent='';sync();
    try{await session();if(ended||epoch!==detailEpoch)return;readIntent(bid);
      history.replaceState(null,'',`/v1/businesses/${bid}/assistance`);if(page)renderList();
      await loadDetail(bid,epoch);
      if(ended||epoch!==detailEpoch)return;
      if(!pending&&!corrupt){const command={version:1,user_id:identity.user,business_id:bid,session_fingerprint:identity.hash,created_at:new Date().toISOString(),operation:'open',body:{idempotency_key:crypto.randomUUID()}};persist(command);pending=command;await send(command,epoch);}
      if(!ended&&epoch===detailEpoch)$('business-heading').focus();
    }catch(error){if(!ended&&epoch===detailEpoch){$('global-error').textContent=error.message||'The business could not be opened.';}}
    finally{busy=false;sync();}
  }
  $('assignment-form').addEventListener('submit',async event=>{
    event.preventDefault();if(ended||busy||!detail?.can_assign||pending||corrupt||!$('assignment-reviewed').checked)return;
    const bid=selected,epoch=detailEpoch,body={idempotency_key:crypto.randomUUID(),expected_version:detail.assignment.version,assignee_user_id:$('assignee').value||null,reviewed:true};busy=true;$('notice').textContent='';$('recovery-error').textContent='';sync();
    try{await session();if(ended||epoch!==detailEpoch||!detail.can_assign)return;const command={version:1,user_id:identity.user,business_id:bid,session_fingerprint:identity.hash,created_at:new Date().toISOString(),operation:'assignment',body};persist(command);pending=command;await send(command,epoch);}
    catch(error){if(!ended&&epoch===detailEpoch)$('recovery-error').textContent=error.message;}
    finally{busy=false;sync();}
  });
  $('retry').addEventListener('click',async()=>{if(ended||busy||!pending||corrupt||(pending.operation==='assignment'&&!detail?.can_assign))return;busy=true;sync();const command=pending,epoch=detailEpoch;try{await send(command,epoch);}catch(error){if(!ended&&epoch===detailEpoch)$('recovery-error').textContent=error.message;}finally{busy=false;sync();}});
  $('refresh').addEventListener('click',async()=>{await loadBoard();if(selected&&!ended){const epoch=++detailEpoch;try{await loadDetail(selected,epoch);}catch(error){if(!ended)$('global-error').textContent=error.message;}}});
  $('filter').addEventListener('change',()=>{cursors=[null];pageIndex=0;loadBoard();});
  $('previous').addEventListener('click',()=>{if(pageIndex){pageIndex--;loadBoard();}});
  $('next').addEventListener('click',()=>{if(page?.next_after){cursors[++pageIndex]=page.next_after;loadBoard();}});
  $('logout').addEventListener('click',async()=>{end('Signing out…');try{await rawApi('/api/v1/auth/logout',{method:'POST'});$('global-error').textContent='Signed out.';}catch(_){$('global-error').textContent='Sign-out could not be confirmed. Return to business setup to check your session.';}});
  async function recheck(){if(ended)return;if(checking){recheckPending=true;return;}checking=true;sync();try{await session();}catch(error){if(!ended)end('Your current sign-in could not be checked. Reopen onboarding to check the saved action again.',false);}finally{checking=false;sync();if(recheckPending&&!ended){recheckPending=false;recheck();}}}
  window.addEventListener('focus',recheck);window.addEventListener('pageshow',recheck);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)$('private-content').hidden=true;else recheck();});
  window.addEventListener('pagehide',()=>{$('private-content').hidden=true;});
  loadBoard();
})();
