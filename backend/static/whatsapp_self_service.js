/* Native owner WA setup. Codes/PINs/state/challenges never enter recovery. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), businessId=location.pathname.split('/')[3];
  const base='/api/v1/businesses/'+businessId+'/channels/whatsapp';
  const PREFIX='munimjee.v1.whatsapp-setup:';
  const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const ID=/^[0-9]{1,40}$/, HEX=/^[0-9a-f]{64}$/;
  const STATES=['pending','exchanging','exchange_unknown','awaiting_assets','awaiting_selection','setting_up','setup_unknown','attached','failed','cancelled','expired','stale'];
  const TEST_STATES=['awaiting_recipient','recipient_verified','queued','sending','accepted','sent','delivered','read','failed','unknown','expired','stale_connection'];
  const SIGNUP_LABELS={pending:'Ready to open Meta signup',exchanging:'Checking the authorization result',exchange_unknown:'Authorization result needs review',
    awaiting_assets:'Review the authorized account',awaiting_selection:'Choose a verified account',setting_up:'Registration result needs review',
    setup_unknown:'Registration result needs review',attached:'Account saved with automation paused',failed:'Setup could not be confirmed',
    cancelled:'Unclaimed setup cancelled',expired:'Setup expired',stale:'The connection changed; review current setup'};
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const exact=(v,keys)=>object(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
  const uuid=v=>typeof v==='string'&&UUID.test(v);
  const providerId=v=>typeof v==='string'&&ID.test(v);
  const fingerprint=v=>typeof v==='string'&&HEX.test(v);
  const version=v=>Number.isInteger(v)&&v>=0&&v<=2000000000;
  const date=v=>typeof v==='string'&&Number.isFinite(Date.parse(v))&&/(Z|[+-][0-9]{2}:[0-9]{2})$/.test(v);
  const localError=message=>Object.assign(new Error(message),{userMessage:message});
  let context=null, latestSession=null, sessionRequest=0, sessionApplied=0, epoch=0;
  let ended=false,busy=false,checking=false,readiness=null,signup=null,test=null,recipient=null,testSequence=0;
  let signupJournal=null,testJournal=null,journalInvalid=false,storageKey=null;
  let startResult=null,sdkLoaded=false,sdkLoading=null,consentOpen=false,loginEpoch=0,assetsHint=null,exchangeStarted=false,assetsSaving=false,choices=[];
  const controllers=new Set();
  async function digest(value) {return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(v=>v.toString(16).padStart(2,'0')).join('');}
  function cookieMatches() {
    if(!context)return true;
    try {return document.cookie.split(';').map(v=>v.trim()).some(v=>v.startsWith('v1_csrf=')&&decodeURIComponent(v.slice(8))===context.csrf);}
    catch(_){return false;}
  }
  function eraseSecrets() {
    $('registration-pin').value='';$('private-command').value='';
    $('recipient-phone').textContent='';$('recipient-window').textContent='';$('recipient-confirmed').checked=false;
    $('recipient-review').hidden=true;recipient=null;
  }
  function erasePrivate() {
    eraseSecrets();choices=[];signup=null;test=null;startResult=null;assetsHint=null;
    consentOpen=false;exchangeStarted=false;loginEpoch++;
    $('consent-form').reset();$('selection-form').reset();$('challenge-form').reset();$('send-form').reset();
    $('account-choice').replaceChildren(new Option('Choose an account',''));
    for(const id of ['connection-status','configuration-note','signup-status','test-status','choice-description','recovery-message'])$(id).textContent='';
    for(const id of ['sdk-ready','selection-section','challenge-area','recipient-review','recovery','check-test','prepare-new-test','owner-tools'])$(id).hidden=true;
    for(const id of ['consent-fields','selection-fields','challenge-fields','send-fields'])$(id).disabled=true;
    $('workspace').hidden=true;readiness=null;
  }
  function removeJournals() {
    if(!storageKey)return;
    try {sessionStorage.removeItem(storageKey);if(sessionStorage.getItem(storageKey)!==null)throw Error();}
    catch(_){throw localError('Browser recovery could not be cleared. Enable session storage before another action.');}
  }
  function end(message) {
    if(ended)return;ended=true;epoch++;sessionRequest++;latestSession=null;
    for(const controller of controllers)controller.abort();
    controllers.clear();erasePrivate();
    try {removeJournals();}catch(_){}
    signupJournal=null;testJournal=null;journalInvalid=false;context=null;
    $('business-name').textContent='WhatsApp setup';$('notice').textContent='';$('page-error').textContent='';$('loading').textContent='';
    $('channels-link').removeAttribute('href');$('channels-link').hidden=true;$('logout').hidden=true;$('refresh').disabled=true;
    $('access-message').textContent=message;$('access-needed').hidden=false;
  }
  async function api(path,options={}) {
    if(ended)throw localError('Your access ended.');
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
    controllers.add(controller);
    try {return await window.V1.api(path,{...options,signal:controller.signal,redirect:'error'});}
    finally {clearTimeout(timer);controllers.delete(controller);}
  }
  async function identity() {
    if(ended)throw localError('Your access ended.');
    const sequence=++sessionRequest,session=await api('/api/v1/auth/session');
    if(ended)throw localError('Your access ended.');
    if(sequence<sessionApplied) {
      if(!latestSession)throw localError('Check your current sign-in.');
      return latestSession;
    }
    const business=Array.isArray(session?.businesses)?session.businesses.find(v=>v?.id===businessId):null;
    if(!uuid(session?.user_id)||typeof session.csrf_token!=='string'||!session.csrf_token||session.csrf_token.length>200||!business||
      typeof business.name!=='string'||!Array.isArray(business.capabilities)||!business.capabilities.includes('inbox.read')||
      !['owner','manager','staff','viewer'].includes(business.role)) {
      end('Your sign-in or business access changed. Open setup again from your business.');throw localError('Your access changed.');
    }
    const fingerprint=await digest(session.csrf_token);
    if(ended)throw localError('Your access ended.');
    if(sequence<sessionApplied) {
      if(!latestSession)throw localError('Check your current sign-in.');
      return latestSession;
    }
    if(context&&(context.userId!==session.user_id||context.csrf!==session.csrf_token||context.role!==business.role)) {
      end('Your sign-in or role changed. Open setup again from your business.');throw localError('Your sign-in changed.');
    }
    if(!context){context={userId:session.user_id,csrf:session.csrf_token,fingerprint,role:business.role};storageKey=PREFIX+context.userId+':'+businessId+':'+fingerprint;}
    if(ended||!cookieMatches()) {
      end('Your sign-in changed. Open setup again from your business.');throw localError('Your sign-in changed.');
    }
    sessionApplied=sequence;latestSession=session;
    $('business-name').textContent=business.name;$('logout').hidden=false;
    $('channels-link').href='/v1/businesses/'+businessId+'/channels';$('channels-link').hidden=false;
    return session;
  }
  function owner() {return context?.role==='owner'&&!ended&&!document.hidden;}
  async function guard(requireOwner=false) {
    await identity();
    if(!ended&&!cookieMatches())end('Your sign-in changed. Open setup again from your business.');
    if(ended||document.hidden)throw localError('Check your current sign-in before continuing.');
    if(requireOwner&&!owner())throw localError('Only a business owner can authorize this action.');
  }
  function safeStart(v) {return exact(v,['idempotency_key','expected_connection_version','notice_reviewed'])&&uuid(v.idempotency_key)&&version(v.expected_connection_version)&&v.notice_reviewed===true;}
  function safeAssets(v) {return exact(v,['idempotency_key','event','waba_id','phone_number_id','provider_business_id'])&&uuid(v.idempotency_key)&&v.event==='FINISH'&&['waba_id','phone_number_id','provider_business_id'].every(k=>typeof v[k]==='string'&&ID.test(v[k]));}
  function safeTestStart(v) {return exact(v,['idempotency_key','expected_connection_version','recipient_authorized'])&&uuid(v.idempotency_key)&&version(v.expected_connection_version)&&v.recipient_authorized===true;}
  function safeSend(v) {return exact(v,['idempotency_key','expected_connection_version','recipient_authorized','recipient_contact_id','inbound_message_id','fixed_text_version'])&&uuid(v.idempotency_key)&&version(v.expected_connection_version)&&v.recipient_authorized===true&&uuid(v.recipient_contact_id)&&uuid(v.inbound_message_id)&&v.fixed_text_version==='wa-connection-test.v1';}
  function store() {
    if(!context||!storageKey||journalInvalid)throw localError('Check browser recovery before continuing.');
    const value={version:1,user_id:context.userId,business_id:businessId,session_fingerprint:context.fingerprint,
      created_at:new Date().toISOString(),signup:signupJournal,test:testJournal};
    const raw=JSON.stringify(value);
    try {sessionStorage.setItem(storageKey,raw);if(sessionStorage.getItem(storageKey)!==raw)throw Error();}
    catch(_){journalInvalid=true;throw localError('Enable browser session storage before another action. No new request was sent.');}
  }
  function readStorage() {
    let raw;try {raw=sessionStorage.getItem(storageKey);}catch(_){journalInvalid=true;return;}
    if(raw===null)return;
    try {
      if(raw.length>8192)throw Error();const value=JSON.parse(raw),created=Date.parse(value.created_at);
      if(!exact(value,['version','user_id','business_id','session_fingerprint','created_at','signup','test'])||value.version!==1||
        value.user_id!==context.userId||value.business_id!==businessId||value.session_fingerprint!==context.fingerprint||
        !Number.isFinite(created)||created>Date.now()+5000||Date.now()-created>86400000)throw Error();
      if(value.signup!==null&&(!exact(value.signup,['body','attempt_id','stage','assets','selection_key'])||!safeStart(value.signup.body)||
        value.signup.attempt_id!==null&&!uuid(value.signup.attempt_id)||!['start_unknown','prepared','consent_open','exchange_unknown','assets','selection_unknown','attached'].includes(value.signup.stage)||
        value.signup.assets!==null&&!safeAssets(value.signup.assets)||value.signup.selection_key!==null&&!uuid(value.signup.selection_key)))throw Error();
      if(value.test!==null&&(!exact(value.test,['body','test_id','stage','send_body'])||!safeTestStart(value.test.body)||
        value.test.test_id!==null&&!uuid(value.test.test_id)||!['start_unknown','challenge','send_unknown','queued'].includes(value.test.stage)||
        value.test.send_body!==null&&!safeSend(value.test.send_body)))throw Error();
      signupJournal=value.signup;testJournal=value.test;
    }catch(_){journalInvalid=true;}
  }
  function validReceipt(value,body,action,resourceId,choiceId=null) {
    return exact(value,['business_id','idempotency_key','action','expected_connection_version','resource_id','selected_choice_id'])&&
      value.business_id===businessId&&value.idempotency_key===body.idempotency_key&&value.action===action&&
      value.expected_connection_version===body.expected_connection_version&&value.resource_id===resourceId&&uuid(value.resource_id)&&
      value.selected_choice_id===choiceId;
  }
  function signupResult(value,body,action,attemptId,choiceId=null) {
    if(!exact(value,['contract_version','receipt','result'])||value.contract_version!=='whatsapp-signup-command.v1'||!validSignup(value.result)||
      value.result.attempt_id!==attemptId||!validReceipt(value.receipt,body,action,attemptId,choiceId))throw localError('The response does not confirm this exact signup action. Its original intent is retained.');
    return value.result;
  }
  function testResult(value,body,action,testId) {
    if(!exact(value,['contract_version','receipt','result'])||value.contract_version!=='whatsapp-test-command.v1'||!validTest(value.result)||
      value.result.test_id!==testId||!validReceipt(value.receipt,body,action,testId))throw localError('The response does not confirm this exact fixed test action. Its original intent is retained.');
    return value.result;
  }
  function validSignup(v) {
    return exact(v,['contract_version','business_id','attempt_id','status','connection_version','expires_at','choices','setup','provider_approval'])&&v.contract_version==='whatsapp-signup.v1'&&v.business_id===businessId&&uuid(v.attempt_id)&&version(v.connection_version)&&
      STATES.includes(v.status)&&date(v.expires_at)&&Array.isArray(v.choices)&&v.choices.length<=100&&v.choices.every(c=>exact(c,['choice_id','display_name','phone_hint'])&&uuid(c.choice_id)&&typeof c.display_name==='string'&&c.display_name.length<=160&&typeof c.phone_hint==='string'&&c.phone_hint.length<=50)&&
      exact(v.setup,['subscription','registration','billing'])&&['not_started','requesting','unknown','confirmed','failed'].includes(v.setup.subscription)&&['not_started','requesting','unknown','confirmed','failed'].includes(v.setup.registration)&&['unknown','external_action_required'].includes(v.setup.billing)&&v.provider_approval==='not_evaluated';
  }
  function validTest(v) {
    return exact(v,['contract_version','business_id','test_id','connection_version','status','recipient_hint','inbound_observed_at','message_id','provider_delivery_observed_at','delivery_confirmed','recorded_effect_status','can_prepare_new_test','is_current_generation','proof_source','message'])&&v.contract_version==='whatsapp-test.v1'&&v.business_id===businessId&&uuid(v.test_id)&&version(v.connection_version)&&TEST_STATES.includes(v.status)&&
      (v.recipient_hint===null||typeof v.recipient_hint==='string'&&v.recipient_hint.length<=50)&&typeof v.message==='string'&&v.message.length<=500&&typeof v.delivery_confirmed==='boolean'&&typeof v.is_current_generation==='boolean'&&['not_recorded','signed_provider_webhook','synthetic_fixture'].includes(v.proof_source)&&
      (v.recorded_effect_status===null||['queued','sending','unknown','accepted','sent','delivered','read','failed'].includes(v.recorded_effect_status))&&typeof v.can_prepare_new_test==='boolean'&&
      !(v.can_prepare_new_test&&['queued','sending','unknown'].includes(v.recorded_effect_status))&&
      !(v.can_prepare_new_test&&v.recorded_effect_status===null&&!['expired','stale_connection'].includes(v.status))&&
      (v.message_id===null||uuid(v.message_id))&&(v.inbound_observed_at===null||date(v.inbound_observed_at))&&
      (v.provider_delivery_observed_at===null||date(v.provider_delivery_observed_at))&&
      (!v.delivery_confirmed||['delivered','read'].includes(v.status)&&v.is_current_generation&&v.proof_source==='signed_provider_webhook'&&v.message_id&&v.inbound_observed_at&&v.provider_delivery_observed_at);
  }
  function validReadiness(v) {
    return exact(v,['contract_version','business_id','onboarding_available','connection_version','local_status','blockers','provider_approval','current_generation_test'])&&v.contract_version==='whatsapp-self-service.v1'&&v.business_id===businessId&&version(v.connection_version)&&
      typeof v.onboarding_available==='boolean'&&['not_connected','paused','setup_required','needs_reconnect','local_access_verified'].includes(v.local_status)&&
      Array.isArray(v.blockers)&&v.blockers.length<=20&&v.blockers.every(x=>typeof x==='string')&&v.provider_approval==='not_evaluated'&&
      (v.current_generation_test===null||validTest(v.current_generation_test));
  }
  function recovery() {
    const active=journalInvalid||signupJournal&&signupJournal.stage!=='attached'||testJournal&&(['start_unknown','send_unknown'].includes(testJournal.stage)||testJournal.stage==='challenge'&&!$('private-command').value&&test?.status==='awaiting_recipient');
    $('recovery').hidden=!active;
    $('recovery-message').textContent=journalInvalid?'This browser has incomplete or different-sign-in recovery details. They are withheld. No new action can be prepared here. Open Channels or sign in again to review.':
      signupJournal?.stage==='selection_unknown'?'The registration or subscription request may have completed. Its PIN was erased. Check saved state; this page will not repeat provider setup.':
      signupJournal?.stage==='exchange_unknown'?'Authorization may have been consumed. Check saved state; this page will not repeat its code exchange.':
      testJournal?.stage==='send_unknown'?'The fixed reply may already be queued or accepted. Check the existing result or retry its exact saved local command.':
      testJournal?.stage==='start_unknown'?'The recipient challenge may have been created. Retry its exact saved local request to recover it.':
      signupJournal?.stage==='consent_open'?'Meta signup was opened. Check the current attempt before explicitly continuing; no popup is reopened automatically.':
      'An earlier local signup request is saved. Check its state or explicitly recover that same request.';
    $('retry-action').hidden=journalInvalid||!(signupJournal&&['start_unknown','prepared','consent_open'].includes(signupJournal.stage)||signup?.status==='awaiting_assets'&&signupJournal?.assets||testJournal&&(['start_unknown','send_unknown'].includes(testJournal.stage)||testJournal.stage==='challenge'&&!$('private-command').value&&test?.status==='awaiting_recipient'));
    $('cancel-action').hidden=journalInvalid||['exchange_unknown','selection_unknown'].includes(signupJournal?.stage)||!(testJournal?.test_id&&!test?.message_id||signupJournal?.attempt_id&&signup&&['pending','awaiting_assets','awaiting_selection','expired','cancelled'].includes(signup.status));
    $('cancel-action').disabled=busy||checking||ended;
    $('retry-action').textContent=signup?.status==='awaiting_assets'&&signupJournal?.assets?'Continue saved account review':testJournal?.stage==='challenge'?'Recover same recipient command':'Retry the same local request';
    $('check-action').disabled=busy||checking||ended;
    $('retry-action').disabled=busy||checking||ended;
  }
  function sync() {
    const locked=ended||busy||checking||!owner()||journalInvalid||!readiness;
    $('workspace').hidden=ended||checking||document.hidden||!readiness;
    $('owner-tools').hidden=!owner();$('view-only').hidden=owner();
    $('refresh').disabled=ended||busy||checking;
    $('consent-fields').disabled=locked||!readiness?.onboarding_available||Boolean(signupJournal);
    $('selection-fields').disabled=locked||signup?.status!=='awaiting_selection'||signupJournal?.stage==='selection_unknown';
    $('challenge-fields').disabled=locked||Boolean(signupJournal)||Boolean(testJournal)||!['paused','local_access_verified'].includes(readiness?.local_status)||readiness?.blockers.includes('test_disabled');
    $('send-fields').disabled=locked||!recipient?.reply_allowed||Boolean(testJournal?.send_body);
    $('open-meta').disabled=locked||!sdkLoaded||consentOpen||!startResult||signup?.status!=='pending';
    $('review-recipient').disabled=locked||!testJournal?.test_id;
    $('copy-command').disabled=locked||!$('private-command').value;
    $('check-test').disabled=locked||!testJournal?.test_id;
    $('prepare-new-test').disabled=locked||!test?.can_prepare_new_test;
    if(['exchange_unknown','selection_unknown'].includes(signupJournal?.stage))$('connection-status').textContent='Current connection needs a fresh check';
    $('loading').textContent=ended?'':checking?'Checking current sign-in and connection…':busy?'Waiting for the reviewed action…':'';
    recovery();
  }
  function renderReadiness() {
    const labels={not_connected:'Not connected',paused:'Saved with automation paused',setup_required:'Current authorization needs review',needs_reconnect:'Reconnect required',local_access_verified:'Local account access verified'};
    $('connection-status').textContent=labels[readiness.local_status];
    $('configuration-note').textContent='Provider approval: not evaluated. Account access is separate from a real delivery test.';
    $('operator-gate').hidden=readiness.onboarding_available;
    $('test-gate').hidden=!readiness.blockers.includes('test_disabled')&&['paused','local_access_verified'].includes(readiness.local_status);
    if(readiness.current_generation_test&&!test)test=readiness.current_generation_test;
    renderTest();sync();
  }
  function renderTest() {
    if(!test)return;
    const labels={awaiting_recipient:'Waiting for the intended recipient’s signed inbound.',recipient_verified:'Recipient received. Review the exact number before one reply.',
      queued:'One fixed reply is queued.',sending:'The reply is claimed for delivery; do not resend.',accepted:'The provider accepted the reply. Delivery is not confirmed.',
      sent:'The provider reports sent. Delivery is not confirmed.',delivered:'The provider reports delivered.',read:'The provider reports read.',
      failed:'The reply failed. It will not be resent automatically.',unknown:'The send result is uncertain. Review before any other action.',expired:'The recipient challenge expired or was cancelled.',stale_connection:'This evidence belongs to an earlier connection generation.'};
    $('test-status').textContent=labels[test.status]+(test.proof_source==='synthetic_fixture'?' This is synthetic test evidence; it cannot confirm live delivery.':'')+
      (test.status==='stale_connection'&&test.recorded_effect_status==='unknown'?' The earlier reply outcome is uncertain. Review it before another test.':
        test.status==='stale_connection'&&['queued','sending'].includes(test.recorded_effect_status)?' The earlier reply is still queued or sending. Review its recorded result before another test.':'')+
      (test.delivery_confirmed?' Bound signed delivery is confirmed for this generation.':'');
    $('check-test').hidden=!testJournal?.test_id;
    $('prepare-new-test').hidden=!testJournal?.test_id||!test.can_prepare_new_test;
    if(testJournal?.test_id&&!test.message_id&&test.is_current_generation)$('challenge-area').hidden=false;
    $('private-command').hidden=!$('private-command').value;
    $('copy-command').hidden=!$('private-command').value;
  }
  function fail(error) {
    if(ended)return;
    if(error?.status===401||error?.status===403){end('Your sign-in or owner access changed. Open setup again from your business.');return;}
    $('page-error').textContent=error?.userMessage||(Number.isInteger(error?.status)?error.message:null)||'The result could not be confirmed. Check saved state before another action.';
  }
  async function refresh() {
    if(ended||checking||busy)return;checking=true;const requestEpoch=++epoch;eraseSecrets();sync();
    try {
      await guard();
      const result=await api(base+'/self-service');
      await guard();
      if(ended||requestEpoch!==epoch)return;
      if(!validReadiness(result))throw localError('The current connection response could not be verified. Fresh actions are withheld.');
      readiness=result;renderReadiness();$('page-error').textContent='';
    }catch(error){readiness=null;erasePrivate();fail(error);}
    finally {checking=false;if(!ended)sync();}
  }
  async function privateRead(path) {
    await guard(true);const requestEpoch=epoch;
    if(ended)throw localError('Your access ended.');
    const value=await api(path);
    await guard(true);
    if(ended||requestEpoch!==epoch)throw localError('This response no longer belongs to the current page.');
    return value;
  }
  async function prepareSignup(replay=false) {
    if(busy||checking||ended)return;busy=true;sync();
    try {
      await guard(true);
      if(!replay) {
        if(signupJournal||journalInvalid||!readiness?.onboarding_available||!$('consent-reviewed').checked)throw localError('Review the current signup and authorization first.');
        signupJournal={body:{idempotency_key:crypto.randomUUID(),expected_connection_version:readiness.connection_version,notice_reviewed:true},attempt_id:null,stage:'start_unknown',assets:null,selection_key:null};
      }
      if(!signupJournal||!safeStart(signupJournal.body))throw localError('The original signup request is unavailable.');
      store();
      if(ended||!cookieMatches())throw localError('Your sign-in changed before dispatch.');
      const result=await api(base+'/signup',{method:'POST',body:signupJournal.body});
      await guard(true);
      if(!exact(result,['contract_version','attempt','receipt','signed_state','sdk'])||result.contract_version!=='whatsapp-signup-start.v1'||!validSignup(result.attempt)||typeof result.signed_state!=='string'||result.signed_state.length<32||result.signed_state.length>4096||
        !exact(result.sdk,['app_id','config_id','graph_version','sdk_url','allowed_message_origin','auto_log_app_events','xfbml'])||!providerId(result.sdk.app_id)||!providerId(result.sdk.config_id)||result.sdk.graph_version!=='v26.0'||
        result.sdk.sdk_url!=='https://connect.facebook.net/en_US/sdk.js'||result.sdk.allowed_message_origin!=='https://www.facebook.com'||result.sdk.auto_log_app_events!==false||result.sdk.xfbml!==false||!validReceipt(result.receipt,signupJournal.body,'signup_start',result.attempt.attempt_id)||signupJournal.attempt_id!==null&&signupJournal.attempt_id!==result.attempt.attempt_id)throw localError('Signup could not be verified. Its exact local request remains saved.');
      signup=result.attempt;startResult=result;signupJournal.attempt_id=signup.attempt_id;signupJournal.stage='prepared';store();
      $('signup-status').textContent='Signup is prepared. Opening Meta requires your next explicit action.';
      if(signup.status==='pending'){await loadSDK(result.sdk);await guard(true);$('sdk-ready').hidden=false;}
      else await checkSavedSignup();
    }catch(error){fail(error);}
    finally {busy=false;if(!ended)sync();}
  }
  function loadSDK(config) {
    if(sdkLoaded)return Promise.resolve();
    if(sdkLoading)return sdkLoading;
    sdkLoading=new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src=config.sdk_url;script.async=true;script.referrerPolicy='no-referrer';
      const timer=setTimeout(()=>reject(localError('Meta signup did not load. No provider setup was repeated.')),15000);
      script.onerror=()=>{clearTimeout(timer);reject(localError('Meta signup could not load. Check saved state before trying again.'));};
      script.onload=()=>{
        clearTimeout(timer);
        if(ended||!cookieMatches()||!window.FB||typeof window.FB.init!=='function'||typeof window.FB.login!=='function')return reject(localError('The Meta signup interface is unavailable.'));
        try {window.FB.init({appId:config.app_id,version:config.graph_version,autoLogAppEvents:false,xfbml:false});sdkLoaded=true;resolve();}
        catch(_){reject(localError('The Meta signup interface could not be prepared. No provider setup was sent.'));}
      };document.head.append(script);
    });
    return sdkLoading;
  }
  function openMeta() {
    if(!ended&&!cookieMatches()){end('Your sign-in changed. Open setup again from your business.');return;}
    if(ended||busy||checking||!owner()||!sdkLoaded||!startResult||signup?.status!=='pending'||consentOpen)return;
    consentOpen=true;exchangeStarted=false;assetsHint=null;const thisLogin=++loginEpoch;
    signupJournal.stage='consent_open';
    try {store();}catch(error){consentOpen=false;fail(error);sync();return;}
    sync();
    // This is the explicit click boundary; do not await a network guard before
    // FB.login, which would lose the browser gesture. Server exchange still
    // reauthorizes exact sid+CSRF+state+HttpOnly nonce before consuming the code.
    try {window.FB.login(response=>{
      if(ended||!consentOpen||thisLogin!==loginEpoch||!cookieMatches())return;
      const code=response?.authResponse?.code;
      if(typeof code!=='string'||!code||code.length>8192){consentOpen=false;$('signup-status').textContent='Meta did not return an authorization code. Check the current attempt before explicitly continuing.';sync();return;}
      exchangeCode(code,thisLogin).catch(fail);
    },{config_id:startResult.sdk.config_id,response_type:'code',override_default_response_type:true,extras:{setup:{}}});}
    catch(_){consentOpen=false;$('signup-status').textContent='Meta signup did not open. Check the current attempt before continuing.';sync();}
  }
  async function exchangeCode(code,thisLogin) {
    if(exchangeStarted||ended||thisLogin!==loginEpoch)return;
    exchangeStarted=true;busy=true;signupJournal.stage='exchange_unknown';store();sync();
    try {
      await guard(true);
      if(ended||thisLogin!==loginEpoch)return;
      const body={idempotency_key:signupJournal.body.idempotency_key,signed_state:startResult.signed_state,code};
      code=null;
      let result;
      try {const response=await api(base+'/signup/'+signupJournal.attempt_id+'/exchange',{method:'POST',body});result=signupResult(response,signupJournal.body,'signup_exchange',signupJournal.attempt_id);}
      finally {body.code='';body.signed_state='';}
      await guard(true);
      if(!validSignup(result)||result.attempt_id!==signupJournal.attempt_id)throw localError('Authorization result is uncertain. Its code will not be repeated.');
      signup=result;startResult=null;$('sdk-ready').hidden=true;
      $('signup-status').textContent=SIGNUP_LABELS[result.status]+'.';
      if(signup.status==='awaiting_assets'&&assetsHint)await saveAssets();
    }catch(error){startResult=null;fail(error);}
    finally {busy=false;consentOpen=Boolean(!ended&&signup?.status==='awaiting_assets'&&!signupJournal?.assets);if(!ended)sync();}
  }
  window.addEventListener('message',event=>{
    if(ended||!consentOpen||!signupJournal?.attempt_id||event.origin!=='https://www.facebook.com'||typeof event.data!=='string'||event.data.length>4096)return;
    let packet;try {packet=JSON.parse(event.data);}catch(_){return;}
    if(!object(packet)||packet.type!=='WA_EMBEDDED_SIGNUP')return;
    if(packet.event!=='FINISH') {
      consentOpen=false;loginEpoch++;startResult=null;$('sdk-ready').hidden=true;
      $('signup-status').textContent='This signup did not finish the supported Cloud API flow. No account was selected.';sync();return;
    }
    const value=packet.data;
    const hint={idempotency_key:signupJournal.body.idempotency_key,event:'FINISH',waba_id:value?.waba_id,phone_number_id:value?.phone_number_id,provider_business_id:value?.business_id};
    if(!safeAssets(hint))return;
    if(signupJournal.assets&&JSON.stringify(signupJournal.assets)!==JSON.stringify(hint))return;
    assetsHint=hint;signupJournal.assets=hint;
    try {store();}catch(error){fail(error);return;}
    if(signup?.status==='awaiting_assets'&&!busy)saveAssets().catch(fail);
  });
  async function saveAssets() {
    if(assetsSaving)return;
    assetsSaving=true;
    try {
    if(ended||!signupJournal?.attempt_id||!safeAssets(signupJournal.assets))throw localError('The original account review is unavailable.');
    await guard(true);
    const response=await api(base+'/signup/'+signupJournal.attempt_id+'/assets',{method:'POST',body:signupJournal.assets});
    const result=signupResult(response,signupJournal.body,'signup_assets',signupJournal.attempt_id);
    await guard(true);
    if(!validSignup(result)||result.attempt_id!==signupJournal.attempt_id)throw localError('Account discovery could not be confirmed.');
    signup=result;signupJournal.stage='assets';store();consentOpen=false;await loadChoices();
    } finally {assetsSaving=false;if(!ended)sync();}
  }
  async function loadChoices() {
    const result=await privateRead(base+'/signup/'+signupJournal.attempt_id+'/choices');
    if(!object(result)||result.contract_version!=='whatsapp-signup-choices.v1'||result.business_id!==businessId||result.attempt_id!==signupJournal.attempt_id||
      !Array.isArray(result.choices)||!result.choices.length||result.choices.length>100||result.choices.some(v=>!object(v)||!uuid(v.choice_id)||
      !providerId(v.waba_id)||!providerId(v.phone_number_id)||typeof v.display_name!=='string'||v.display_name.length>160||
      typeof v.display_phone_number!=='string'||v.display_phone_number.length>50||!fingerprint(v.fingerprint)))throw localError('Verified account choices could not be checked.');
    choices=result.choices;$('account-choice').replaceChildren(new Option('Choose an account',''));
    for(const choice of choices)$('account-choice').append(new Option(choice.display_name+' · '+choice.display_phone_number,choice.choice_id));
    $('selection-section').hidden=false;$('signup-status').textContent='Choose an account from the server-verified membership list. Nothing is selected automatically.';sync();
  }
  async function chooseAccount() {
    if(busy||checking||ended)return;busy=true;sync();let body=null;
    try {
      await guard(true);
      const choice=choices.find(v=>v.choice_id===$('account-choice').value),pin=$('registration-pin').value;
      if(!choice||!$('account-confirmed').checked||!/^[0-9]{6}$/.test(pin)||signupJournal?.stage==='selection_unknown')throw localError('Review the exact account, registration PIN and authorization.');
      body={idempotency_key:crypto.randomUUID(),expected_connection_version:signup.connection_version,choice_id:choice.choice_id,
        waba_id:choice.waba_id,phone_number_id:choice.phone_number_id,expected_choice_fingerprint:choice.fingerprint,
        owner_confirmed:true,subscription_confirmed:true,request_registration:true,registration_pin:pin};
      signupJournal.selection_key=body.idempotency_key;signupJournal.stage='selection_unknown';store();
      if(ended||!cookieMatches())throw localError('Your sign-in changed before dispatch.');
      const response=await api(base+'/signup/'+signupJournal.attempt_id+'/select',{method:'POST',body});
      const result=signupResult(response,body,'signup_select',signupJournal.attempt_id,choice.choice_id);
      await guard(true);
      if(!validSignup(result)||result.attempt_id!==signupJournal.attempt_id)throw localError('The setup result is uncertain. Its provider steps will not be repeated.');
      signup=result;
      if(result.status==='attached') {
        signupJournal=null;store();choices=[];$('selection-section').hidden=true;
        $('signup-status').textContent='Account saved with automation paused. Billing and a real delivery test remain separate.';
      } else $('signup-status').textContent=SIGNUP_LABELS[result.status]+'. Check it before any further action.';
    }catch(error){fail(error);}
    finally {if(body)body.registration_pin='';$('registration-pin').value='';busy=false;if(!ended){sync();if(signup?.status==='attached')await refresh();}}
  }
  async function checkSavedSignup() {
    if(!signupJournal?.attempt_id)return;
    const value=await privateRead(base+'/signup/'+signupJournal.attempt_id);
    if(!validSignup(value)||value.attempt_id!==signupJournal.attempt_id)throw localError('Saved signup state could not be verified.');
    signup=value;$('signup-status').textContent=SIGNUP_LABELS[value.status]+'. Checking does not repeat registration or send a reply.';
    if(['attached','cancelled','expired','failed','stale'].includes(value.status)){signupJournal=null;store();$('selection-section').hidden=true;}
    else if(value.status==='awaiting_selection')await loadChoices();
    else if(value.status==='awaiting_assets'&&signupJournal.assets)$('signup-status').textContent+=' The original verified-account discovery request is available for explicit recovery.';
  }
  async function createChallenge(replay=false) {
    if(busy||checking||ended)return;busy=true;const responseSequence=++testSequence;sync();
    try {
      await guard(true);
      if(!replay) {
        if(testJournal||!$('recipient-authorized').checked)throw localError('Review the recipient authorization first.');
        testJournal={body:{idempotency_key:crypto.randomUUID(),expected_connection_version:readiness.connection_version,recipient_authorized:true},test_id:null,stage:'start_unknown',send_body:null};
      }
      if(!testJournal||!safeTestStart(testJournal.body))throw localError('The original test request is unavailable.');
      store();
      if(ended||!cookieMatches())throw localError('Your sign-in changed before dispatch.');
      const value=await api(base+'/tests',{method:'POST',body:testJournal.body});
      await guard(true);
      if(!exact(value,['contract_version','test','receipt','command'])||value.contract_version!=='whatsapp-test-challenge.v1'||!validTest(value.test)||typeof value.command!=='string'||!/^MUNIMJEE-WA-TEST:[A-Za-z0-9_-]{22}$/.test(value.command)||!validReceipt(value.receipt,testJournal.body,'test_start',value.test.test_id)||testJournal.test_id!==null&&testJournal.test_id!==value.test.test_id)throw localError('The challenge result could not be verified. Retry only its original local request.');
      if(responseSequence!==testSequence)return;
      $('page-error').textContent='';
      test=value.test;testJournal.test_id=test.test_id;testJournal.stage='challenge';store();
      $('private-command').value=value.command;value.command='';$('challenge-area').hidden=false;renderTest();
    }catch(error){fail(error);}
    finally {busy=false;if(!ended)sync();}
  }
  async function reviewRecipient() {
    if(busy||checking||ended||!testJournal?.test_id)return;busy=true;eraseSecrets();sync();
    try {
      const value=await privateRead(base+'/tests/'+testJournal.test_id+'/recipient');
      if(!exact(value,['contract_version','business_id','test_id','connection_version','recipient_contact_id','inbound_message_id','phone','inbound_observed_at','reply_window_expires_at','reply_allowed'])||value.contract_version!=='whatsapp-test-recipient.v1'||value.business_id!==businessId||value.test_id!==testJournal.test_id||
        !version(value.connection_version)||!uuid(value.recipient_contact_id)||!uuid(value.inbound_message_id)||typeof value.phone!=='string'||
        !/^[1-9][0-9]{7,14}$/.test(value.phone)||!date(value.inbound_observed_at)||!date(value.reply_window_expires_at)||typeof value.reply_allowed!=='boolean')throw localError('The intended recipient could not be verified.');
      recipient=value;$('recipient-phone').textContent='+'+value.phone;
      $('recipient-window').textContent=value.reply_allowed?'A current reply window is available. Confirm this is the person you asked.':'This test cannot queue another reply. Check its saved result.';
      $('recipient-review').hidden=false;
    }catch(error){eraseSecrets();fail(error);}
    finally {busy=false;if(!ended)sync();}
  }
  async function queueReply(replay=false) {
    if(busy||checking||ended)return;busy=true;const responseSequence=++testSequence;sync();
    try {
      await guard(true);
      if(!replay) {
        if(!recipient?.reply_allowed||!$('recipient-confirmed').checked||testJournal?.send_body)throw localError('Confirm the exact intended recipient and fixed reply first.');
        testJournal.send_body={idempotency_key:crypto.randomUUID(),expected_connection_version:recipient.connection_version,recipient_authorized:true,
          recipient_contact_id:recipient.recipient_contact_id,inbound_message_id:recipient.inbound_message_id,fixed_text_version:'wa-connection-test.v1'};
      }
      if(!testJournal?.test_id||!safeSend(testJournal.send_body))throw localError('The original fixed reply command is unavailable.');
      testJournal.stage='send_unknown';store();eraseSecrets();
      if(ended||!cookieMatches())throw localError('Your sign-in changed before dispatch.');
      const response=await api(base+'/tests/'+testJournal.test_id+'/send',{method:'POST',body:testJournal.send_body});
      const value=testResult(response,testJournal.send_body,'test_send',testJournal.test_id);
      await guard(true);
      if(!validTest(value)||value.test_id!==testJournal.test_id||!value.message_id)throw localError('The fixed reply may already be queued. Its exact command remains saved.');
      if(responseSequence!==testSequence)return;
      $('page-error').textContent='';
      test=value;testJournal.stage='queued';store();renderTest();$('challenge-area').hidden=true;
    }catch(error){fail(error);}
    finally {busy=false;if(!ended)sync();}
  }
  async function checkTest() {
    if(!testJournal?.test_id)return;
    const responseSequence=++testSequence;
    const value=await privateRead(base+'/tests/'+testJournal.test_id);
    if(!validTest(value)||value.test_id!==testJournal.test_id)throw localError('The existing test result could not be checked.');
    if(responseSequence!==testSequence)return;
    test=value;
    if(value.message_id&&testJournal.send_body){testJournal.stage='queued';store();}
    renderTest();sync();
  }
  async function prepareNewTest() {
    if(busy||checking||ended||!testJournal?.test_id)return;
    busy=true;const responseSequence=++testSequence,oldId=testJournal.test_id;sync();
    try {
      const previous=await privateRead(base+'/tests/'+oldId);
      const current=await privateRead(base+'/self-service');
      await guard(true);
      if(responseSequence!==testSequence||!testJournal||testJournal.test_id!==oldId||!validTest(previous)||previous.test_id!==oldId||
        !previous.can_prepare_new_test||!validReadiness(current))throw localError('The earlier test still needs review. No new recipient command was prepared.');
      // This button performs GETs only. The recorded test/outbox is untouched;
      // a new command requires a newly checked recipient authorization below.
      testJournal=null;store();eraseSecrets();$('recipient-authorized').checked=false;
      $('page-error').textContent='';
      test=null;readiness=current;renderReadiness();$('challenge-area').hidden=true;
      $('check-test').hidden=true;$('prepare-new-test').hidden=true;
      $('test-status').textContent='The earlier test remains recorded. Review recipient permission again before creating a new command. No reply was repeated.';
    }catch(error){fail(error);}
    finally {busy=false;if(!ended)sync();}
  }
  async function checkAction() {
    if(busy||checking||ended||journalInvalid)return;busy=true;eraseSecrets();sync();
    try {await guard(true);await checkSavedSignup();await checkTest();}
    catch(error){fail(error);}
    finally {busy=false;if(!ended)sync();}
  }
  async function retryAction() {
    if(journalInvalid)return;
    if(testJournal?.stage==='send_unknown')return queueReply(true);
    if(testJournal&&['start_unknown','challenge'].includes(testJournal.stage))return createChallenge(true);
    if(signup?.status==='awaiting_assets'&&signupJournal?.assets){try {await saveAssets();}catch(error){fail(error);}return;}
    if(signupJournal&&['start_unknown','prepared','consent_open'].includes(signupJournal.stage))return prepareSignup(true);
  }
  async function cancelAction() {
    if(busy||checking||ended||journalInvalid)return;busy=true;eraseSecrets();sync();
    try {
      await guard(true);
      if(testJournal?.test_id&&!test?.message_id) {
        testSequence++;
        const response=await api(base+'/tests/'+testJournal.test_id+'/cancel',{method:'POST',body:{idempotency_key:testJournal.body.idempotency_key}});
        const value=testResult(response,testJournal.body,'test_cancel',testJournal.test_id);
        await guard(true);
        if(!validTest(value)||value.test_id!==testJournal.test_id||value.status!=='expired'||value.message_id)throw localError('Cancellation could not be confirmed. Keep checking the original action.');
        test=value;testJournal=null;store();$('challenge-area').hidden=true;renderTest();
      } else if(signupJournal?.attempt_id) {
        const response=await api(base+'/signup/'+signupJournal.attempt_id+'/cancel',{method:'POST',body:{idempotency_key:signupJournal.body.idempotency_key}});
        const value=signupResult(response,signupJournal.body,'signup_cancel',signupJournal.attempt_id);
        await guard(true);
        if(!validSignup(value)||value.attempt_id!==signupJournal.attempt_id||!['cancelled','expired'].includes(value.status))throw localError('The unclaimed signup cancellation could not be confirmed.');
        signup=value;signupJournal=null;startResult=null;consentOpen=false;loginEpoch++;store();$('sdk-ready').hidden=true;$('selection-section').hidden=true;
      }
      $('notice').textContent='The unclaimed action was cancelled. Any provider-claimed or uncertain effect remains protected and is not repeated.';
    }catch(error){fail(error);}
    finally {busy=false;if(!ended)sync();}
  }
  $('cancel-action').addEventListener('click',cancelAction);
  $('consent-form').addEventListener('submit',event=>{event.preventDefault();prepareSignup();});
  $('selection-form').addEventListener('submit',event=>{event.preventDefault();chooseAccount();});
  $('challenge-form').addEventListener('submit',event=>{event.preventDefault();createChallenge();});
  $('send-form').addEventListener('submit',event=>{event.preventDefault();queueReply();});
  $('open-meta').addEventListener('click',openMeta);
  $('refresh').addEventListener('click',refresh);
  $('check-action').addEventListener('click',checkAction);
  $('retry-action').addEventListener('click',retryAction);
  $('review-recipient').addEventListener('click',reviewRecipient);
  $('check-test').addEventListener('click',()=>{if(!busy&&!checking){checkTest().catch(fail);}});
  $('prepare-new-test').addEventListener('click',prepareNewTest);
  $('account-choice').addEventListener('change',()=>{const choice=choices.find(v=>v.choice_id===$('account-choice').value);$('choice-description').textContent=choice?'Selected business number: '+choice.display_phone_number:'';});
  $('copy-command').addEventListener('click',async()=>{
    if(!owner()||!cookieMatches()||!$('private-command').value)return;
    try {await navigator.clipboard.writeText($('private-command').value);if(!ended)$('notice').textContent='Private command copied. Share only with the intended recipient.';}
    catch(_){if(!ended)$('page-error').textContent='Copy is unavailable in this browser. No message was sent.';}
  });
  $('logout').addEventListener('click',async()=>{
    try {await guard();await api('/api/v1/auth/logout',{method:'POST'});end('Signed out. Private connection details were cleared.');}
    catch(error){fail(error);}
  });
  async function focusGuard() {
    if(ended)return;epoch++;eraseSecrets();$('workspace').hidden=true;
    try {await guard();if(ended)return;if(!busy&&!checking)await refresh();else sync();}
    catch(error){fail(error);}
  }
  window.addEventListener('focus',()=>{if(!ended)focusGuard().catch(fail);});
  document.addEventListener('visibilitychange',()=>{
    epoch++;
    if(document.hidden){eraseSecrets();$('workspace').hidden=true;}
    else if(!ended)focusGuard().catch(fail);
  });
  (async()=>{
    try {if(!uuid(businessId))throw localError('Open setup from your business.');await identity();readStorage();await refresh();}
    catch(error){fail(error);}
  })();
})();
