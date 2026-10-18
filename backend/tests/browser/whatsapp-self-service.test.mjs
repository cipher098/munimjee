/* Actual owned script, controlled DOM/API/SDK doubles. No rendered/DB claim. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {randomUUID,webcrypto,createHash} from 'node:crypto';
const source=await readFile(new URL('../../static/whatsapp_self_service.js',import.meta.url),'utf8');
const html=await readFile(new URL('../../static/whatsapp_self_service.html',import.meta.url),'utf8');
const bid='11111111-1111-4111-8111-111111111111',uid='22222222-2222-4222-8222-222222222222';
const aid='33333333-3333-4333-8333-333333333333',cid='44444444-4444-4444-8444-444444444444';
const tid='55555555-5555-4555-8555-555555555555',contactId='66666666-6666-4666-8666-666666666666',inboundId='77777777-7777-4777-8777-777777777777';
const at=new Date().toISOString(),expiry=new Date(Date.now()+600000).toISOString();
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.listeners={};this.hidden=false;this.disabled=false;this.value='';this.checked=false;this._text='';this.elements=[];}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(v=>typeof v==='string'?v:v.textContent).join('');}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this._text='';this.children=[...nodes];}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  removeAttribute(name){delete this[name];}
  reset(){for(const node of this.elements){node.value='';node.checked=false;}}
  async fire(name,event={}){for(const fn of this.listeners[name]||[])await fn({preventDefault(){},...event});}
}
const wait=async predicate=>{for(let n=0;n<120;n++){if(predicate())return;await new Promise(setImmediate);}throw Error('Controlled operating script did not settle');};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const attempt=status=>({contract_version:'whatsapp-signup.v1',business_id:bid,attempt_id:aid,status,connection_version:1,expires_at:expiry,
  choices:status==='awaiting_selection'?[{choice_id:cid,display_name:'Synthetic account',phone_hint:'••12345'}]:[],
  setup:{subscription:'not_started',registration:'not_started',billing:'external_action_required'},provider_approval:'not_evaluated'});
const testView=status=>({contract_version:'whatsapp-test.v1',business_id:bid,test_id:tid,connection_version:1,status,recipient_hint:null,
  inbound_observed_at:null,message_id:null,provider_delivery_observed_at:null,delivery_confirmed:false,recorded_effect_status:null,can_prepare_new_test:false,is_current_generation:true,proof_source:'synthetic_fixture',message:'Synthetic test only'});
const ready={contract_version:'whatsapp-self-service.v1',business_id:bid,onboarding_available:true,connection_version:1,local_status:'paused',
  blockers:[],provider_approval:'not_evaluated',current_generation_test:null};
const receipt=(body,action,resourceId,choiceId=null)=>({business_id:bid,idempotency_key:body.idempotency_key,action,expected_connection_version:body.expected_connection_version??1,resource_id:resourceId,selected_choice_id:choiceId});
const signupAck=(status,body,action)=>({contract_version:'whatsapp-signup-command.v1',receipt:receipt(body,action,aid),result:attempt(status)});
const testAck=(value,body,action)=>({contract_version:'whatsapp-test-command.v1',receipt:receipt(body,action,tid),result:value});
const startResponse=body=>({contract_version:'whatsapp-signup-start.v1',attempt:attempt('pending'),signed_state:'x'.repeat(32),receipt:receipt(body,'signup_start',aid),
  sdk:{app_id:'123',config_id:'789',graph_version:'v26.0',sdk_url:'https://connect.facebook.net/en_US/sdk.js',allowed_message_origin:'https://www.facebook.com',auto_log_app_events:false,xfbml:false}});
const challengeResponse=body=>({contract_version:'whatsapp-test-challenge.v1',test:testView('awaiting_recipient'),command:'MUNIMJEE-WA-TEST:'+'A'.repeat(22),receipt:receipt(body,'test_start',tid)});
async function fixture({role='owner',entries=[],restricted=false,gated=false}={}) {
  const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  for(const match of html.matchAll(/<[^>]+id="([^"]+)"[^>]*>/g)){get(match[1]).hidden=/\bhidden(?:\s|>|=)/.test(match[0]);get(match[1]).disabled=/\bdisabled(?:\s|>|=)/.test(match[0]);}
  for(const [form,names] of [['consent-form',['consent-reviewed']],['selection-form',['account-choice','registration-pin','account-confirmed']],
    ['challenge-form',['recipient-authorized']],['send-form',['recipient-confirmed']]])get(form).elements=names.map(get);
  const stored=new Map(entries),listeners={},documentListeners={},calls=[],sdkCalls=[];
  const session={user_id:uid,csrf_token:'synthetic-native-csrf',businesses:[{id:bid,name:'Synthetic private business',role,capabilities:['inbox.read',...(role==='owner'?['channels.connect']:[])]}]};
  let current=session,sessionHook=null,apiHook=null,loginCallback=null;
  const document={hidden:false,cookie:'v1_csrf='+session.csrf_token,getElementById:get,createElement:tag=>new Element(tag),
    addEventListener:(name,fn)=>(documentListeners[name]??=[]).push(fn)};
  document.head={append:script=>{sdkCalls.push({src:script.src});setImmediate(()=>script.onload());}};
  const api=async(path,options={})=>{
    calls.push({path,options:structuredClone({...options,signal:undefined})});
    if(path==='/api/v1/auth/session') {if(sessionHook)return sessionHook();if(current instanceof Error)throw current;return structuredClone(current);}
    if(apiHook)return apiHook(path,options);
    if(path.endsWith('/self-service'))return structuredClone(gated?{...ready,onboarding_available:false,blockers:['signup_disabled','test_disabled']}:ready);
    if(path.endsWith('/signup')&&options.method==='POST')return startResponse(options.body);
    if(path.endsWith('/exchange'))return signupAck('awaiting_assets',options.body,'signup_exchange');
    if(path.endsWith('/assets'))return signupAck('awaiting_selection',options.body,'signup_assets');
    if(path.endsWith('/choices'))return{contract_version:'whatsapp-signup-choices.v1',business_id:bid,attempt_id:aid,choices:[{choice_id:cid,display_name:'Synthetic account',
      phone_hint:'••12345',waba_id:'456',phone_number_id:'12345',display_phone_number:'+910000000000',fingerprint:'a'.repeat(64),registration_status:'unknown'}]};
    if(path.endsWith('/signup/'+aid))return attempt('pending');
    if(path.endsWith('/tests')&&options.method==='POST')return challengeResponse(options.body);
    if(path.endsWith('/recipient'))return{contract_version:'whatsapp-test-recipient.v1',business_id:bid,test_id:tid,connection_version:1,recipient_contact_id:contactId,
      inbound_message_id:inboundId,phone:'910000000000',inbound_observed_at:at,reply_window_expires_at:new Date(Date.now()+86400000).toISOString(),reply_allowed:true};
    if(path.endsWith('/tests/'+tid))return testView('awaiting_recipient');
    throw Error('Unspecified controlled API route');
  };
  const window={V1:{api},FB:{init:options=>sdkCalls.push({init:options}),login:(callback,options)=>{loginCallback=callback;sdkCalls.push({login:options});}},
    addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)};
  const storage={getItem:key=>stored.get(key)??null,setItem:(key,value)=>{if(restricted)throw Error('restricted');stored.set(key,value);},removeItem:key=>stored.delete(key)};
  const sandbox={window,document,sessionStorage:storage,location:{pathname:'/v1/businesses/'+bid+'/channels/whatsapp/setup'},
    crypto:{randomUUID,subtle:webcrypto.subtle},TextEncoder,Date,Set,Option:class extends Element{constructor(text,value){super('option');this.textContent=text;this.value=value;}},
    AbortController,setTimeout,clearTimeout,navigator:{clipboard:{writeText:async()=>{}}}};
  vm.runInNewContext(source,sandbox);
  await wait(()=>get('connection-status').textContent||get('access-message').textContent);
  await wait(()=>get('loading').textContent==='');
  return{get,stored,calls,sdkCalls,document,session,setSession:value=>{current=value;},sessionHook:value=>{sessionHook=value;},apiHook:value=>{apiHook=value;},
    focus:async()=>{for(const fn of listeners.focus||[])await fn();},message:async packet=>{for(const fn of listeners.message||[])await fn(packet);},
    login:response=>loginCallback(response),visibility:async hidden=>{document.hidden=hidden;for(const fn of documentListeners.visibilitychange||[])await fn();}};
}
async function prepare(f) {
  f.get('consent-reviewed').checked=true;await f.get('consent-form').fire('submit');
  await wait(()=>f.get('sdk-ready').hidden===false);
  await wait(()=>f.get('loading').textContent==='');
}
test('default-off projection withholds controls and never loads the SDK',async()=>{
  const f=await fixture({gated:true});
  assert.equal(f.get('consent-fields').disabled,true);assert.equal(f.get('challenge-fields').disabled,true);
  assert.equal(f.sdkCalls.length,0);assert(!f.calls.some(v=>v.options.method==='POST'));
});
test('viewer only sees coarse status, without any owner controls',async()=>{
  const f=await fixture({role:'viewer'});assert.equal(f.get('owner-tools').hidden,true);assert.equal(f.get('view-only').hidden,false);
  assert(!f.calls.some(v=>v.options.method==='POST'));assert.equal(f.sdkCalls.length,0);
});
test('restricted recovery storage fails before the first POST',async()=>{
  const f=await fixture({restricted:true});f.get('consent-reviewed').checked=true;await f.get('consent-form').fire('submit');
  await wait(()=>f.get('page-error').textContent);assert(!f.calls.some(v=>v.options.method==='POST'));assert.equal(f.sdkCalls.length,0);
});
test('lost prepare response survives reload without an automatic POST or new key',async()=>{
  const f=await fixture();f.apiHook(async()=>{throw Error('Synthetic dropped response');});
  f.get('consent-reviewed').checked=true;await f.get('consent-form').fire('submit');await wait(()=>f.get('page-error').textContent);
  const original=f.calls.find(v=>v.options.method==='POST').options.body;
  const reloaded=await fixture({entries:f.stored});assert(!reloaded.calls.some(v=>v.options.method==='POST'));
  await reloaded.get('retry-action').fire('click');await wait(()=>reloaded.get('sdk-ready').hidden===false);
  const replay=reloaded.calls.find(v=>v.options.method==='POST').options.body;
  assert.deepEqual(replay,original);assert.equal(reloaded.sdkCalls.filter(v=>v.login).length,0);
});
test('a held preparation guard reserves one intent before simultaneous submits',async()=>{
  const f=await fixture(),held=deferred();let first=true;
  f.sessionHook(()=>{if(first){first=false;return held.promise;}return structuredClone(f.session);});
  f.get('consent-reviewed').checked=true;await f.get('consent-form').fire('submit');await wait(()=>!first);
  await f.get('consent-form').fire('submit');assert(!f.calls.some(v=>v.options.method==='POST'));
  held.resolve(structuredClone(f.session));await wait(()=>f.get('sdk-ready').hidden===false);
  assert.equal(f.calls.filter(v=>v.options.method==='POST').length,1);
});
test('same-user session replacement during a pending read physically clears private DOM',async()=>{
  const f=await fixture(),held=deferred();let used=false;
  f.get('registration-pin').value='123456';f.get('recipient-phone').textContent='SYNTHETIC_PRIVATE_RECIPIENT';
  f.apiHook(async path=>{if(path.endsWith('/self-service')&&!used){used=true;return held.promise;}return structuredClone(ready);});
  const pending=f.get('refresh').fire('click');await wait(()=>used);
  f.setSession({...f.session,csrf_token:'synthetic-replacement'});f.document.cookie='v1_csrf=synthetic-replacement';await f.focus();
  await wait(()=>f.get('logout').hidden===true);held.resolve(structuredClone(ready));await pending;await wait(()=>f.get('loading').textContent==='');
  for(const id of ['recipient-phone','connection-status','recovery-message'])assert.equal(f.get(id).textContent,'');
  assert.equal(f.get('registration-pin').value,'');assert.equal(f.get('workspace').hidden,true);
});
test('a delayed owner session cannot revive a page ended by a newer401',async()=>{
  const f=await fixture(),held=deferred();let first=true;
  f.sessionHook(()=>{if(first){first=false;return held.promise;}throw Object.assign(Error('Synthetic revoked'),{status:401});});
  f.get('consent-reviewed').checked=true;await f.get('consent-form').fire('submit');await wait(()=>!first);
  await f.focus();await wait(()=>f.get('logout').hidden===true);held.resolve(structuredClone(f.session));
  await wait(()=>f.get('loading').textContent==='');
  assert(!f.calls.some(v=>v.options.method==='POST'));assert.equal(f.get('owner-tools').hidden,true);
});
test('SDK code exchange occurs once and late FINISH data still reaches verified account review',async()=>{
  const f=await fixture();await prepare(f);await f.get('open-meta').fire('click');
  f.login({authResponse:{code:'synthetic-never-real-code'}});
  await wait(()=>f.get('signup-status').textContent.includes('Review the authorized account'));
  await f.message({origin:'https://attacker.facebook.com',data:JSON.stringify({type:'WA_EMBEDDED_SIGNUP',event:'FINISH',data:{waba_id:'456',phone_number_id:'12345',business_id:'789'}})});
  assert(!f.calls.some(v=>v.path.endsWith('/assets')));
  await f.message({origin:'https://www.facebook.com',data:JSON.stringify({type:'WA_EMBEDDED_SIGNUP',event:'FINISH',data:{waba_id:'456',phone_number_id:'12345',business_id:'789'}})});
  await wait(()=>f.get('selection-section').hidden===false);
  assert.equal(f.calls.filter(v=>v.path.endsWith('/exchange')).length,1);
  assert.equal(f.calls.filter(v=>v.path.endsWith('/assets')).length,1);
  assert(![...f.stored.values()].join('').includes('synthetic-never-real-code'));
  assert(![...f.stored.values()].join('').includes('signed_state'));
});
test('unknown account selection erases PIN and never persists or replays it on reload',async()=>{
  const f=await fixture();await prepare(f);await f.get('open-meta').fire('click');
  await f.message({origin:'https://www.facebook.com',data:JSON.stringify({type:'WA_EMBEDDED_SIGNUP',event:'FINISH',data:{waba_id:'456',phone_number_id:'12345',business_id:'789'}})});
  f.login({authResponse:{code:'synthetic-never-real-code'}});await wait(()=>f.get('selection-section').hidden===false);
  f.get('account-choice').value=cid;f.get('registration-pin').value='123456';f.get('account-confirmed').checked=true;
  f.apiHook(async()=>{throw Error('Synthetic dropped selection');});await f.get('selection-form').fire('submit');
  await wait(()=>f.get('page-error').textContent);await wait(()=>f.get('registration-pin').value==='');
  assert.equal(f.get('cancel-action').hidden,true);
  assert.equal(f.get('connection-status').textContent,'Current connection needs a fresh check');
  assert.equal(f.get('page-error').textContent,'The result could not be confirmed. Check saved state before another action.');
  const raw=[...f.stored.values()].join('');assert(!raw.includes('123456'));assert(!raw.includes('registration_pin'));
  const reloaded=await fixture({entries:f.stored});assert(!reloaded.calls.some(v=>v.options.method==='POST'));assert.equal(reloaded.get('retry-action').hidden,true);
  reloaded.apiHook(async path=>path.endsWith('/self-service')?{...ready,connection_version:2}:attempt('attached'));
  await reloaded.get('check-action').fire('click');await wait(()=>reloaded.get('recovery').hidden===true);
  assert.equal(reloaded.get('connection-status').textContent,'Saved with automation paused');
  assert(reloaded.get('signup-status').textContent.includes('Account saved with automation paused'));
  assert(!reloaded.get('signup-status').textContent.includes('attached'));
  assert(reloaded.calls.some(v=>v.path.endsWith('/self-service')));
});

test('current unknown receipt never claims provider acceptance or a fresh test',async()=>{
  const f=await fixture();f.get('recipient-authorized').checked=true;await f.get('challenge-form').fire('submit');await wait(()=>f.get('private-command').value);
  f.apiHook(async()=>({...testView('unknown'),message_id:randomUUID(),recorded_effect_status:'unknown',can_prepare_new_test:false}));
  await f.get('check-test').fire('click');await wait(()=>f.get('test-status').textContent.includes('send result is uncertain'));
  assert(!f.get('test-status').textContent.includes('provider accepted'));assert.equal(f.get('prepare-new-test').hidden,true);
});

test('confirmed signup without a fresh readiness read withholds old connection controls',async()=>{
  const fingerprint=createHash('sha256').update('synthetic-native-csrf').digest('hex');
  const value={version:1,user_id:uid,business_id:bid,session_fingerprint:fingerprint,created_at:new Date().toISOString(),
    signup:{body:{idempotency_key:randomUUID(),expected_connection_version:1,notice_reviewed:true},attempt_id:aid,
      stage:'selection_unknown',assets:null,selection_key:randomUUID()},test:null};
  const f=await fixture({entries:[['munimjee.v1.whatsapp-setup:'+uid+':'+bid+':'+fingerprint,JSON.stringify(value)]]});
  f.apiHook(async path=>{if(path.endsWith('/self-service'))throw Error('Synthetic readiness read failed');return attempt('attached');});
  await f.get('check-action').fire('click');
  assert.equal(f.get('workspace').hidden,true);assert.equal(f.get('challenge-fields').disabled,true);
  assert.equal(f.get('connection-status').textContent,'');assert(!f.calls.some(v=>v.options.method==='POST'));
});

test('explicit new-test review only reads the old receipt and resets recipient permission',async()=>{
  const f=await fixture();f.get('recipient-authorized').checked=true;await f.get('challenge-form').fire('submit');
  await wait(()=>f.get('private-command').value);
  const previous={...testView('stale_connection'),is_current_generation:false,message_id:randomUUID(),
    recorded_effect_status:'delivered',can_prepare_new_test:true};
  f.apiHook(async path=>path.endsWith('/self-service')?{...ready,connection_version:2}:structuredClone(previous));
  await f.get('check-test').fire('click');await wait(()=>f.get('prepare-new-test').hidden===false);
  const count=f.calls.filter(v=>v.options.method==='POST').length;
  await f.get('prepare-new-test').fire('click');await wait(()=>f.get('recipient-authorized').checked===false);
  assert.equal(f.calls.filter(v=>v.options.method==='POST').length,count);
  assert.equal(JSON.parse([...f.stored.values()][0]).test,null);
  assert.equal(f.get('private-command').value,'');assert.equal(f.get('challenge-fields').disabled,false);
});

for(const effect of ['queued','sending','unknown'])test('stale '+effect+' cannot retire its journal or prepare another test',async()=>{
  const f=await fixture();f.get('recipient-authorized').checked=true;await f.get('challenge-form').fire('submit');
  await wait(()=>f.get('private-command').value);
  const previous={...testView('stale_connection'),is_current_generation:false,message_id:randomUUID(),
    recorded_effect_status:effect,can_prepare_new_test:false};
  f.apiHook(async path=>path.endsWith('/self-service')?{...ready,connection_version:2}:structuredClone(previous));
  await f.get('check-test').fire('click');await wait(()=>f.get('test-status').textContent.includes('earlier connection generation'));
  assert.equal(f.get('prepare-new-test').hidden,true);
  if(effect==='unknown')assert(f.get('test-status').textContent.includes('outcome is uncertain'));
  const before=[...f.stored.values()][0],count=f.calls.filter(v=>v.options.method==='POST').length;
  await f.get('prepare-new-test').fire('click');
  assert.equal([...f.stored.values()][0],before);assert.equal(f.calls.filter(v=>v.options.method==='POST').length,count);
});
test('private challenge and exact recipient stay outside recovery, unknown send keeps the same local command',async()=>{
  const f=await fixture();f.get('recipient-authorized').checked=true;await f.get('challenge-form').fire('submit');
  await wait(()=>f.get('private-command').value);assert(![...f.stored.values()].join('').includes('MUNIMJEE-WA-TEST:'));
  await f.get('review-recipient').fire('click');await wait(()=>f.get('recipient-phone').textContent);
  assert(![...f.stored.values()].join('').includes('910000000000'));
  f.get('recipient-confirmed').checked=true;f.apiHook(async()=>{throw Error('Synthetic dropped queue response');});
  await f.get('send-form').fire('submit');await wait(()=>f.get('page-error').textContent);
  assert.equal(f.get('recipient-phone').textContent,'');assert.equal(f.get('private-command').value,'');
  const original=f.calls.find(v=>v.path.endsWith('/send')).options.body;
  const reloaded=await fixture({entries:f.stored});assert(!reloaded.calls.some(v=>v.options.method==='POST'));
  reloaded.apiHook(async(path,options)=>path.endsWith('/send')?testAck({...testView('queued'),message_id:randomUUID()},options.body,'test_send'):structuredClone(ready));
  await reloaded.get('retry-action').fire('click');await wait(()=>reloaded.calls.some(v=>v.path.endsWith('/send')));
  assert.deepEqual(reloaded.calls.find(v=>v.path.endsWith('/send')).options.body,original);
});
test('an old ended page cannot remove a replacement session journal',async()=>{
  const f=await fixture(),newKey='munimjee.v1.whatsapp-setup:'+uid+':'+bid+':new-session-fingerprint';
  f.stored.set(newKey,'new-session-safe-command');f.setSession({...f.session,csrf_token:'replacement'});f.document.cookie='v1_csrf=replacement';
  await f.focus();await wait(()=>f.get('logout').hidden===true);assert.equal(f.stored.get(newKey),'new-session-safe-command');
});
for(const kind of ['malformed','foreign_business','foreign_session','expired'])test('withholds '+kind+' recovery without a new action',async()=>{
  const csrf='synthetic-native-csrf',fingerprint=createHash('sha256').update(csrf).digest('hex');
  const raw=kind==='malformed'?'{':JSON.stringify({version:1,user_id:uid,business_id:kind==='foreign_business'?randomUUID():bid,
    session_fingerprint:kind==='foreign_session'?'f'.repeat(64):fingerprint,created_at:new Date(Date.now()-(kind==='expired'?90000000:0)).toISOString(),
    signup:{body:{idempotency_key:randomUUID(),expected_connection_version:1,notice_reviewed:true},attempt_id:null,stage:'start_unknown',assets:null,selection_key:null},test:null});
  const f=await fixture({entries:[['munimjee.v1.whatsapp-setup:'+uid+':'+bid+':'+fingerprint,raw]]});
  assert.equal(f.get('consent-fields').disabled,true);assert.equal(f.get('retry-action').hidden,true);assert(!f.calls.some(v=>v.options.method==='POST'));
});

for(const action of ['signup','test'])test('wrong-command valid200 '+action+' ACK preserves original intent across reload',async()=>{
  const f=await fixture();
  f.apiHook(async(path,options)=>{
    const value=action==='signup'?startResponse(options.body):challengeResponse(options.body);
    value.receipt.idempotency_key=randomUUID();return value;
  });
  if(action==='signup'){f.get('consent-reviewed').checked=true;await f.get('consent-form').fire('submit');}
  else{f.get('recipient-authorized').checked=true;await f.get('challenge-form').fire('submit');}
  await wait(()=>f.get('page-error').textContent);
  const original=f.calls.find(v=>v.options.method==='POST').options.body;
  const journal=JSON.parse([...f.stored.values()][0]);
  assert.equal(action==='signup'?journal.signup.attempt_id:journal.test.test_id,null);
  assert.equal(f.sdkCalls.length,0);assert.equal(f.get('private-command').value,'');
  const reloaded=await fixture({entries:f.stored});assert(!reloaded.calls.some(v=>v.options.method==='POST'));
  await reloaded.get('retry-action').fire('click');await wait(()=>reloaded.calls.some(v=>v.options.method==='POST'));
  assert.deepEqual(reloaded.calls.find(v=>v.options.method==='POST').options.body,original);
});
test('held older test status cannot replace newer queued acknowledgement',async()=>{
  const f=await fixture();f.get('recipient-authorized').checked=true;await f.get('challenge-form').fire('submit');await wait(()=>f.get('private-command').value);
  await f.get('review-recipient').fire('click');await wait(()=>f.get('recipient-phone').textContent);
  const held=deferred();let readEntered=false;
  f.apiHook(async(path,options)=>{
    if(path.endsWith('/tests/'+tid)){readEntered=true;return held.promise;}
    if(path.endsWith('/send'))return testAck({...testView('queued'),message_id:randomUUID()},options.body,'test_send');
    throw Error('Unspecified race API');
  });
  await f.get('check-test').fire('click');await wait(()=>readEntered);
  f.get('recipient-confirmed').checked=true;await f.get('send-form').fire('submit');await wait(()=>f.get('test-status').textContent.includes('queued'));
  held.resolve(testView('recipient_verified'));await new Promise(setImmediate);await new Promise(setImmediate);
  assert(f.get('test-status').textContent.includes('queued'));assert(!f.get('test-status').textContent.includes('Recipient received'));
  assert.equal(JSON.parse([...f.stored.values()][0]).test.stage,'queued');
});
