/* Native design editor. Durable same-command recovery is fenced by sign-in + tenant. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), form = $('design-form');
  const businessId = location.pathname.split('/')[3], endpoint = `/api/v1/businesses/${businessId}/theme-settings`;
  const PREFIX = 'munimjee.v1.theme-command:', UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const texts = {brand_tagline:80,hero_eyebrow:60,hero_headline:100,hero_intro:300,collection_heading:100,story_heading:100,story_body:1000};
  let session, access, record, owner, fingerprint, storageKey, pending = null, busy = false, blocked = false, dirty = false;
  let generation = 0, terminal = false, preparing = false, sending = false;
  function assertLive(epoch) {if(terminal || epoch!==generation)throw Object.assign(Error('This page sign-in ended. Sign in again.'),{stale:true});}
  const api = window.V1.api;
  const exact = (x, keys) => x && typeof x === 'object' && !Array.isArray(x) && Object.keys(x).length === keys.length && keys.every(k => Object.hasOwn(x,k));
  const digest = async x => [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(x)))].map(v=>v.toString(16).padStart(2,'0')).join('');
  const canEdit = () => access?.capabilities.includes('business.write');
  function validConfig(c) {
    return exact(c,['theme','palette',...Object.keys(texts),'show_story','show_categories']) && ['editorial','catalogue','video'].includes(c.theme) && ['rose','forest','indigo'].includes(c.palette) && ['show_story','show_categories'].every(k=>typeof c[k]==='boolean') && Object.entries(texts).every(([k,max])=>typeof c[k]==='string' && c[k].length<=max && !/[<>\x00-\x08\x0b-\x1f\x7f]/.test(c[k]));
  }
  function validRecord(r) {return exact(r,['version','draft','published','published_revision','published_at']) && Number.isInteger(r.version) && r.version>=0 && validConfig(r.draft) && (r.published===null||validConfig(r.published)) && Number.isInteger(r.published_revision) && r.published_revision>=0 && r.published_revision<=r.version && (r.published_at===null||typeof r.published_at==='string');}
  function sync() {
    $('design-fields').disabled = !canEdit() || busy || blocked || Boolean(pending);
    $('publish').disabled = dirty || !record?.version;
    $('reload').disabled = busy || Boolean(pending);
    $('retry').disabled = busy || blocked || !pending || !canEdit();
    $('recovery').hidden = !pending && !blocked;
    $('role-note').hidden = canEdit();
    if(record) $('design-state').textContent = `${dirty?'Unsaved changes':record.published?'Published design saved':'Draft · no published design'} · version ${record.version}`;
    $('preview-note').textContent = dirty ? 'Unsaved changes · save the draft to update this preview' : 'Saved draft · illustrative layout · checkout unavailable';
  }
  function clearPrivate() {
    terminal=true;generation++;
    try {for(let i=sessionStorage.length-1;i>=0;i--){const key=sessionStorage.key(i);if(key?.startsWith(PREFIX))sessionStorage.removeItem(key);}} catch (_) {}
    pending=null;blocked=true;record=null;access=null;$('workspace').hidden=true;
    $('preview').src='about:blank';form.reset();$('business-name').textContent='';
    $('design-state').textContent='Sign in required';$('notice').textContent='';$('recovery-note').textContent='';
    $('access-needed').hidden=false;
  }
  function showError(error) {
    if(error.stale)return;
    if(error.status===401 || error.identityChanged)clearPrivate();
    $('error').textContent=error.message;
  }
  async function identity(write=false, epoch=generation) {
    assertLive(epoch);
    const current=await window.V1.session();assertLive(epoch);
    const currentAccess=current.businesses?.find(b=>b.id===businessId);
    const currentFingerprint=current.csrf_token?await digest(current.csrf_token):null;assertLive(epoch);
    if(current.user_id!==owner || !currentAccess || currentFingerprint!==fingerprint) {
      clearPrivate();throw Object.assign(Error('Your sign-in or business access changed. Sign in again.'),{identityChanged:true});
    }
    access=currentAccess;
    if(write&&!canEdit())throw Object.assign(Error('Your current role cannot edit designs. Ask a manager to review this saved action.'),{status:403});
  }
  function storeIntent(command) {
    const raw=JSON.stringify(command);
    try {sessionStorage.setItem(storageKey,raw);if(sessionStorage.getItem(storageKey)!==raw)throw Error();}
    catch (_) {throw Error('Browser session storage is unavailable. No new action was sent. Enable it and reload.');}
  }
  function removeIntent() {
    sessionStorage.removeItem(storageKey);
    if(sessionStorage.getItem(storageKey)!==null)throw Error('The saved recovery action could not be cleared. Keep this page open and retry after enabling session storage.');
  }
  async function decode(raw) {
    if(typeof raw!=='string'||raw.length>20000)throw Error('Saved recovery is invalid. Reload the saved design in a new sign-in before editing.');
    let c;try{c=JSON.parse(raw);}catch(_){throw Error('Saved recovery cannot be read. Sign in again before editing.');}
    if(!exact(c,['format','user_id','business_id','session_digest','created_at','operation','body','body_digest'])||c.format!==1)throw Error('Saved recovery format is invalid. Sign in again before editing.');
    if(c.user_id!==owner||c.business_id!==businessId||c.session_digest!==fingerprint)throw Object.assign(Error('A saved action belongs to another sign-in. Its details have been withheld. Sign in again before editing.'),{identityChanged:true});
    const date=Date.parse(c.created_at), b=c.body;
    if(!Number.isFinite(date)||date>Date.now()+300000||Date.now()-date>7*86400000||!['save','publish'].includes(c.operation)||!exact(b,c.operation==='save'?['expected_version','idempotency_key','config']:['expected_version','idempotency_key'])||!UUID.test(b.idempotency_key)||!Number.isInteger(b.expected_version)||b.expected_version<0||b.expected_version>2000000000||(c.operation==='save'&&!validConfig(b.config))||(c.operation==='publish'&&b.expected_version<1)||c.body_digest!==await digest(JSON.stringify(b)))throw Error('Saved action is expired or changed. Sign in again and review the saved design before editing.');
    return c;
  }
  function recovery() { $('recovery-note').textContent = pending ? `The ${pending.operation==='save'?'draft save':'design publication'} may already have completed. Retry this exact saved action to confirm it. Reloading does not send it automatically.` : 'Recovery cannot be verified. Sign in again and review the saved design before editing.';sync(); }
  function populate(value) {
    if(!validRecord(value))throw Error('The saved design response is incomplete. Reload before editing.');
    record=value;
    for(const [key,v] of Object.entries(value.draft)) {
      if(key==='theme') [...form.elements.theme].forEach(input=>input.checked=input.value===v);
      else if(typeof v==='boolean')form.elements[key].checked=v;
      else form.elements[key].value=v;
    }
    dirty=false;
    $('preview').src=endpoint+'/preview?v='+record.version;
    sync();
  }
  async function load() {
    if(terminal||busy||pending)return;
    const epoch=generation;busy=true;blocked=true;sync();$('error').textContent='';$('notice').textContent='';
    try {await identity(false,epoch);const data=await api(endpoint);await identity(false,epoch);assertLive(epoch);populate(data);blocked=false;$('notice').textContent='Saved design loaded.';}
    catch(error){showError(error);}finally{if(!terminal&&epoch===generation){busy=false;sync();}}
  }
  async function send() {
    if(!pending||blocked||terminal||sending||preparing)return;
    const epoch=generation; sending=true;busy=true;sync();$('error').textContent='';$('notice').textContent='';
    try {
      await identity(true,epoch);
      const saved=await decode(sessionStorage.getItem(storageKey));assertLive(epoch);
      if(JSON.stringify(saved)!==JSON.stringify(pending))throw Error('Recovery changed in this window. Sign in again before continuing.');
      const result=await api(endpoint+(pending.operation==='publish'?'/publish':''),{method:pending.operation==='save'?'PUT':'POST',body:pending.body});
      await identity(false,epoch);assertLive(epoch);
      if(!validRecord(result))throw Error('The action result is incomplete. Retry the saved action to confirm it.');
      const current=await api(endpoint);await identity(false,epoch);assertLive(epoch);
      if(!validRecord(current))throw Error('The current design response is incomplete. Retry the saved action to confirm it.');
      const operation=pending.operation;removeIntent();pending=null;populate(current);
      $('notice').textContent=operation==='save'?'Draft saved. Public design is unchanged.':'Saved design published. Store visibility, product activation and checkout settings are unchanged.';
    } catch(error) {
      if(!terminal&&epoch===generation&&error.status>=400&&error.status<500&&error.status!==401) {
        try {removeIntent();pending=null;} catch (_) {blocked=true;}
        if(error.status===409){blocked=true;$('recovery-note').textContent='This design changed elsewhere. Reload the saved design before editing.';}
      }
      showError(error);
    } finally {sending=false;if(!terminal&&epoch===generation){busy=false;if(pending)recovery();sync();}}
  }
  async function start(operation) {
    if(busy||blocked||pending||!canEdit()||terminal)return;
    const epoch=generation;busy=true;preparing=true;sync();$('error').textContent='';$('notice').textContent='';
    try {
      await identity(true,epoch);
      const body={expected_version:record.version,idempotency_key:crypto.randomUUID()};
      if(operation==='save') {
        const config={theme:form.elements.theme.value,palette:form.elements.palette.value};
        for(const key of Object.keys(texts))config[key]=form.elements[key].value.trim();
        for(const key of ['show_story','show_categories'])config[key]=form.elements[key].checked;
        if(!validConfig(config))throw Error('Use plain text without markup, and check the field lengths.');
        body.config=config;
      }
      const command={format:1,user_id:owner,business_id:businessId,session_digest:fingerprint,created_at:new Date().toISOString(),operation,body,body_digest:await digest(JSON.stringify(body))};
      assertLive(epoch);storeIntent(command);pending=command;recovery();preparing=false;await send();
    }catch(error){showError(error);}finally{preparing=false;if(!terminal&&epoch===generation){busy=false;sync();}}
  }
  form.addEventListener('submit',event=>{event.preventDefault();if(form.reportValidity())start('save');});
  form.addEventListener('input',()=>{dirty=true;sync();});
  $('publish').addEventListener('click',()=>start('publish'));
  $('retry').addEventListener('click',send);
  $('reload').addEventListener('click',load);
  window.addEventListener('pagehide',()=>{$('preview').removeAttribute('src');});
  function checkCurrentIdentity(){if(owner&&!terminal)identity(false).then(sync).catch(showError);}
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkCurrentIdentity();});
  window.addEventListener('focus',checkCurrentIdentity);
  (async()=>{
    try {
      session=await window.V1.session();access=session.businesses?.find(b=>b.id===businessId);
      if(!access||session.auth_method!=='v1_user'||!session.csrf_token)throw Object.assign(Error('Sign in with your own V1 account to open store design.'),{status:401});
      owner=session.user_id;fingerprint=await digest(session.csrf_token);storageKey=PREFIX+owner+':'+businessId;
      $('catalogue-link').href=`/v1/businesses/${businessId}/catalogue`;
      const epoch=generation,data=await api(endpoint);await identity(false,epoch);assertLive(epoch);
      $('business-name').textContent=access.name||'Your business';populate(data);
      $('workspace').hidden=false;
      try {const raw=sessionStorage.getItem(storageKey);if(raw!==null){pending=await decode(raw);assertLive(epoch);recovery();}}
      catch(error){blocked=true;if(error.identityChanged)clearPrivate();showError(error);recovery();}
      sync();
    }catch(error){showError(error);$('access-needed').hidden=false;}
  })();
})();
