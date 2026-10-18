/* Native payment configuration. Secret values never enter messages or storage. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const businessId = location.pathname.split('/')[3];
  const endpoint = `/api/v1/businesses/${businessId}/payments/razorpay`;
  const PREFIX = 'munimjee.v1.gateway-intent:';
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const REVISION = /^[a-f0-9]{64}$/;
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value,k));
  let context = null, config = null, pending = null, recoveryInvalid = false;
  let storageKey = null, ended = false, saving = false, loading = false, checking = false;
  let replacement = false, recoveryRead = false, loadEpoch = 0;
  const localError = message => Object.assign(new Error(message), {userMessage:message});
  async function digest(value) {return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(v=>v.toString(16).padStart(2,'0')).join('');}
  async function api(path,options={}) {
    const controller = new AbortController(), timer = setTimeout(()=>controller.abort(),10000);
    try {return await window.V1.api(path,{...options,signal:controller.signal,redirect:'error'});}
    finally {clearTimeout(timer);}
  }
  function eraseSecrets() {$('api-secret').value='';$('webhook-secret').value='';}
  function erasePrivate() {
    $('settings-form').reset();eraseSecrets();$('account-summary').replaceChildren();$('account-status').textContent='';
    for(const id of ['recovery-message','recovery-current','recovery-error','save-status'])$(id).textContent='';
    $('catalogue-link').removeAttribute('href');$('checkout-link').removeAttribute('href');
    $('webhook-url').value='';$('key-id').value='';$('form-error').textContent='';
    $('workspace').hidden=true;$('settings-fields').disabled=true;config=null;
  }
  function removeMarker() {
    if(!storageKey)return;
    try {sessionStorage.removeItem(storageKey);if(sessionStorage.getItem(storageKey)!==null)throw Error();}
    catch (_) {throw localError('Browser recovery could not be cleared. Enable session storage before making another change.');}
  }
  function closeAccess(message, clearMarker=false) {
    if(ended)return;ended=true;loadEpoch++;erasePrivate();
    if(clearMarker)try {removeMarker();} catch (_) { /* A different identity never reads this marker. */ }
    pending=null;recoveryInvalid=false;$('business-name').textContent='Payment setup';
    loading=false;checking=false;$('notice').textContent='';$('page-error').textContent='';$('loading').textContent='';
    $('access-message').textContent=message;$('access-needed').hidden=false;
    $('refresh').disabled=true;$('logout').hidden=true;$('catalogue-link').hidden=true;
  }
  function currentCookieMatches() {
    if(!context)return true;
    try {return document.cookie.split(';').map(v=>v.trim()).some(v=>v.startsWith('v1_csrf=')&&decodeURIComponent(v.slice(8))===context.csrf);}
    catch (_) {return false;}
  }
  async function identity() {
    if(ended)throw localError('Your sign-in or access changed.');
    const session=await api('/api/v1/auth/session');
    if(ended)throw localError('Your sign-in or access changed.');
    const business=session?.businesses?.find(value=>value.id===businessId);
    if(!UUID.test(session?.user_id)||typeof session.csrf_token!=='string'||!session.csrf_token||session.csrf_token.length>200||!business||typeof business.name!=='string'||!Array.isArray(business.capabilities)) {
      closeAccess('Your sign-in or business access changed. Open payment setup again from your business.',true);throw localError('Your sign-in or access changed.');
    }
    if(context&&(session.user_id!==context.userId||session.csrf_token!==context.csrf)) {
      closeAccess('Your sign-in changed. Open payment setup again from your business.',true);throw localError('Your sign-in changed.');
    }
    if(!business.capabilities.includes('business.write')) {
      closeAccess('Payment setup requires owner or manager access. Ask a business owner to update your role.',true);throw localError('Payment setup requires owner or manager access.');
    }
    if(!context) {
      const fingerprint=await digest(session.csrf_token);
      if(ended)throw localError('Your sign-in or access changed.');
      if(context&&(context.userId!==session.user_id||context.csrf!==session.csrf_token)) {
        closeAccess('Your sign-in changed. Open payment setup again from your business.',true);throw localError('Your sign-in changed.');
      }
      if(!context){context={userId:session.user_id,csrf:session.csrf_token,fingerprint};storageKey=PREFIX+context.userId+':'+businessId;}
    }
    if(ended)throw localError('Your sign-in or access changed.');
    $('business-name').textContent=business.name;$('logout').hidden=false;
    $('catalogue-link').href=`/v1/businesses/${businessId}/catalogue`;$('catalogue-link').hidden=false;
    return session;
  }
  function validConfig(value) {
    if(!exact(value,['configured','enabled','mode','key_id','webhook_url','encryption_ready','configuration_revision','connection_verification'])||
       !['configured','enabled','encryption_ready'].every(k=>typeof value[k]==='boolean')||!['test','live'].includes(value.mode)||
       typeof value.key_id!=='string'||value.key_id.length>100||!REVISION.test(value.configuration_revision)||value.connection_verification!=='not_performed'||
       (value.configured?!new RegExp('^rzp_'+value.mode+'_[A-Za-z0-9]+$').test(value.key_id):(value.key_id!==''||value.enabled))||typeof value.webhook_url!=='string'||value.webhook_url.length>4096)return false;
    try {const url=new URL(value.webhook_url);return !url.username&&!url.password&&!url.search&&!url.hash&&url.pathname===`/webhooks/razorpay/${businessId}`&&(url.protocol==='https:'||(url.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(url.hostname)));}catch(_){return false;}
  }
  function storeMarker(marker) {
    const raw=JSON.stringify(marker);
    try {sessionStorage.setItem(storageKey,raw);if(sessionStorage.getItem(storageKey)!==raw)throw Error();}
    catch (_) {throw localError('Enable browser session storage before saving payment settings. No new save was sent.');}
  }
  function readMarker() {
    let raw;try {raw=sessionStorage.getItem(storageKey);}catch(_){recoveryInvalid=true;return;}
    if(raw===null)return;
    try {
      if(raw.length>2048)throw Error();const value=JSON.parse(raw),created=Date.parse(value.created_at);
      if(!exact(value,['version','user_id','business_id','session_fingerprint','created_at','expected_revision','intended','state'])||value.version!==1||value.user_id!==context.userId||value.business_id!==businessId||value.session_fingerprint!==context.fingerprint||!REVISION.test(value.expected_revision)||!Number.isFinite(created)||created>Date.now()+5000||Date.now()-created>7*86400000||!['sending','uncertain'].includes(value.state)||!exact(value.intended,['key_id','mode','enabled'])||!['test','live'].includes(value.intended.mode)||typeof value.intended.enabled!=='boolean'||typeof value.intended.key_id!=='string'||value.intended.key_id.length>100||!new RegExp('^rzp_'+value.intended.mode+'_[A-Za-z0-9]+$').test(value.intended.key_id))throw Error();
      pending=value;
    }catch(_){recoveryInvalid=true;}
  }
  function recoveryActive() {return Boolean(pending)||recoveryInvalid;}
  function secretControls() {
    if(!config)return;
    const both=!config.configured||replacement||$('mode').value!==config.mode;
    const apiNeeded=both||$('key-id').value.trim()!==config.key_id;
    if(apiNeeded)$('replace-api').checked=true;
    if(both)$('replace-webhook').checked=true;
    for(const [kind,forced] of [['api',apiNeeded],['webhook',both]]) {
      const checkbox=$('replace-'+kind), input=$(kind==='api'?'api-secret':'webhook-secret');
      $('replace-'+kind+'-label').hidden=!config.configured||replacement;
      checkbox.disabled=forced;
      const selected=forced||checkbox.checked;
      $(kind==='api'?'api-secret-label':'webhook-secret-label').hidden=!selected;
      input.disabled=!selected;input.required=selected;
      if(!selected)input.value='';
    }
    $('keep-secrets').hidden=!config.configured||replacement;
    $('replacement-review-label').hidden=!replacement;$('replacement-review').required=replacement;
  }
  function sync() {
    const locked=ended||saving||loading||checking||!config||!config.encryption_ready||(recoveryActive()&&!replacement);
    $('settings-fields').disabled=locked;$('refresh').disabled=ended||saving||loading||checking;
    $('check-current').disabled=ended||saving||loading||checking;
    $('replace-current').disabled=ended||saving||loading||checking||!recoveryRead||!config?.encryption_ready;
    $('editor').hidden=!config||(recoveryActive()&&!replacement)||!config.encryption_ready;
    $('workspace').hidden=ended||!config||document.hidden||checking;
    $('recovery').hidden=!recoveryActive();
    $('loading').textContent=ended?'':loading?'Loading payment settings…':checking?'Checking your current access…':'';
    $('save').textContent=saving?'Saving…':replacement?'Save replacement credentials':'Save payment setup';
    $('settings-form').setAttribute('aria-busy',saving?'true':'false');
  }
  function fillForm() {
    eraseSecrets();$('mode').value=config.mode;$('key-id').value=config.key_id;$('gateway-enabled').checked=config.enabled;
    $('replace-api').checked=false;$('replace-webhook').checked=false;$('replacement-review').checked=false;
    $('editor-heading').textContent=replacement?'Replace current credentials':config.configured?'Update payment setup':'Add credentials';
    $('editor-description').textContent=replacement?'Enter both secrets again. This creates a new conditional replacement; it does not retry the earlier save.':'Use the key ID, API secret and webhook secret from your Razorpay account.';
    secretControls();
  }
  function render() {
    $('account-status').textContent=config.configured?'Credentials configured':'Not configured';
    $('account-summary').replaceChildren();
    for(const [label,value] of [['Mode',config.configured?(config.mode==='test'?'Test':'Live'):'Not set'],['Key ID',config.key_id||'Not set'],['Gateway preference',config.enabled?'Allowed for online checkout':'Paused']]) {
      const term=document.createElement('dt'),detail=document.createElement('dd');term.textContent=label;detail.textContent=value;$('account-summary').append(term,detail);
    }
    $('webhook-url').value=config.webhook_url;$('webhook-area').hidden=false;
    $('checkout-link').href=`/v1/businesses/${businessId}/catalogue#checkout-section`;$('checkout-link').hidden=false;
    $('page-error').textContent=config.encryption_ready?'':'The server is not ready to store payment credentials. Ask your business owner to contact support before entering secrets.';
    $('recovery-message').textContent=recoveryInvalid?'This browser has incomplete or different-sign-in recovery details. Their contents have been withheld. Check current settings before replacing credentials.':pending?'The earlier save may have completed. Its secrets were erased from this page and were not stored. A status check cannot confirm whether those secret changes saved.':'';
    $('recovery-current').textContent=recoveryRead?'Current public settings are shown above. If you need to change credentials, choose Replace current credentials and enter both secrets again.':'';
    fillForm();sync();
  }
  function accessFailure(error) {
    if(error.status===401||error.status===403)closeAccess('Your sign-in or access changed. Open payment setup again from your business.',true);
  }
  async function loadSettings(recover=false) {
    if(ended||saving)return;
    const epoch=++loadEpoch;loading=true;replacement=false;recoveryRead=false;eraseSecrets();sync();
    $('page-error').textContent='';$('form-error').textContent='';$('recovery-error').textContent='';
    try {
      await identity();if(ended||epoch!==loadEpoch)return;
      if(!pending&&!recoveryInvalid)readMarker();
      const data=await api(endpoint);await identity();if(ended||epoch!==loadEpoch)return;
      if(!validConfig(data))throw localError('Current payment settings could not be verified. Refresh or contact your business owner.');
      config=data;recoveryRead=Boolean(recover&&recoveryActive());render();
    }catch(error){accessFailure(error);if(!ended&&epoch===loadEpoch){config=null;erasePrivate();$('page-error').textContent=error.userMessage||'Payment settings could not be loaded. Refresh to check your current access and try again.';}}
    finally {if(epoch===loadEpoch){loading=false;sync();}}
  }
  function capture() {
    const mode=$('mode').value,key_id=$('key-id').value.trim();
    if(!['test','live'].includes(mode)||!new RegExp('^rzp_'+mode+'_[A-Za-z0-9]+$').test(key_id)||key_id.length>100)throw localError('Enter a key ID that matches the selected test or live mode.');
    const body={key_id,mode,enabled:$('gateway-enabled').checked,expected_revision:config.configuration_revision};
    for(const [kind,field,min] of [['api','key_secret',8],['webhook','webhook_secret',16]]) {
      const selected=!$(kind==='api'?'api-secret':'webhook-secret').disabled;
      if(selected){const secret=$(kind==='api'?'api-secret':'webhook-secret').value.trim();if(secret.length<min||secret.length>500)throw localError(`Enter the ${kind==='api'?'API':'webhook'} secret with ${min}–500 characters.`);body[field]=secret;}
    }
    if(replacement&&!$('replacement-review').checked)throw localError('Confirm that you reviewed the current settings before replacing both secrets.');
    return body;
  }
  async function save(event) {
    event.preventDefault();if(ended||saving||loading||checking||!config||(recoveryActive()&&!replacement))return;
    let body;try {body=capture();}catch(error){$('form-error').textContent=error.userMessage||'Check the entered settings.';return;}
    eraseSecrets();saving=true;$('notice').textContent='';$('form-error').textContent='';$('save-status').textContent='';sync();
    let sent=false;
    try {
      await identity();if(ended)return;
      const marker={version:1,user_id:context.userId,business_id:businessId,session_fingerprint:context.fingerprint,created_at:new Date().toISOString(),expected_revision:body.expected_revision,intended:{key_id:body.key_id,mode:body.mode,enabled:body.enabled},state:'sending'};
      storeMarker(marker);pending=marker;recoveryInvalid=false;sent=true;
      if(ended)return;
      const result=await api(endpoint,{method:'PUT',body});await identity();if(ended)return;
      if(!validConfig(result)||!result.configured||result.key_id!==body.key_id||result.mode!==body.mode||result.enabled!==body.enabled||((body.key_secret||body.webhook_secret)&&result.configuration_revision===body.expected_revision))throw localError('The save response could not be verified.');
      removeMarker();pending=null;recoveryInvalid=false;replacement=false;recoveryRead=false;config=result;
      render();$('notice').textContent='Payment settings saved. A Razorpay connection was not checked.';
    }catch(error){
      accessFailure(error);if(ended)return;
      if(error.status===409&&error.code==='gateway_config_stale') {
        try {removeMarker();pending=null;recoveryInvalid=false;}catch(_){recoveryInvalid=true;}
        replacement=false;config=null;erasePrivate();$('page-error').textContent='Payment settings changed while you were editing. Refresh, review the current settings and enter new secrets again if needed.';
      }else if(sent) {
        if(pending){pending.state='uncertain';try{storeMarker(pending);}catch(_){}}
        replacement=false;recoveryRead=false;
        $('recovery-message').textContent=error.status===409?'Pending online orders or another configuration change may prevent replacement. Check saved settings and resolve pending orders before replacing credentials.':'The save result is unknown. Check saved settings before choosing an explicit replacement. No secret value or save body was stored.';
        $('recovery-current').textContent='';$('recovery-error').textContent='';
      }else {$('form-error').textContent=error.userMessage||'Your current access could not be confirmed. Refresh before entering secrets again.';}
    }finally {
      if(body){body.key_secret=null;body.webhook_secret=null;body=null;}
      saving=false;eraseSecrets();sync();
    }
  }
  async function recheck() {
    if(ended||!context||checking)return;
    if(!currentCookieMatches()){closeAccess('Your sign-in changed. Open payment setup again from your business.',true);return;}
    checking=true;sync();
    try {await identity();}catch(error){accessFailure(error);if(!ended)closeAccess('Your current sign-in could not be confirmed. Open payment setup again from your business.');}
    finally {checking=false;sync();}
  }
  $('settings-form').addEventListener('submit',event=>{save(event).catch(()=>closeAccess('Payment setup could not continue safely. Open it again from your business.'));});
  $('refresh').addEventListener('click',()=>{loadSettings(recoveryActive()).catch(()=>closeAccess('Open payment setup again from your business.'));});
  $('check-current').addEventListener('click',()=>{loadSettings(true).catch(()=>closeAccess('Open payment setup again from your business.'));});
  $('replace-current').addEventListener('click',()=>{if(!config||!recoveryRead||ended||saving)return;replacement=true;fillForm();sync();$('editor').scrollIntoView({block:'start'});$('key-id').focus();});
  for(const id of ['mode','key-id','replace-api','replace-webhook'])$(id).addEventListener(id==='key-id'?'input':'change',secretControls);
  $('logout').addEventListener('click',async()=>{closeAccess('Signing out…');try{await api('/api/v1/auth/logout',{method:'POST'});try{removeMarker();}catch(_){}$('access-message').textContent='Signed out. Return to business setup to sign in again.';}catch(_){$('access-message').textContent='Sign-out could not be confirmed. Return to business setup to check your session.';}});
  window.addEventListener('focus',recheck);window.addEventListener('pageshow',recheck);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){$('workspace').hidden=true;$('settings-fields').disabled=true;}else recheck();});
  window.addEventListener('pagehide',()=>{eraseSecrets();$('workspace').hidden=true;});
  loadSettings().catch(()=>closeAccess('Open payment setup again from your business.'));
})();
