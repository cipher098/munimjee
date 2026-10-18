/* Actual operating script with minimal DOM/API doubles. No rendered/DB claim. */
import {test} from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';
import {readFile} from 'node:fs/promises';import {randomUUID,webcrypto,createHash} from 'node:crypto';
const source=await readFile(new URL('../../static/channel_operator.js',import.meta.url),'utf8');
const bid='11111111-1111-4111-8111-111111111111',uid='22222222-2222-4222-8222-222222222222';
const owner=['inbox.read','automation.manage','channels.connect','channels.disconnect'];
class Element {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.hidden=false;this.value='';this.checked=false;this._text='';this.elements={};}
 set textContent(x){this._text=String(x);this.children=[];}get textContent(){return this._text+this.children.map(x=>typeof x==='string'?x:x.textContent).join('');}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this._text='';this.children=[...nodes];}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}setAttribute(){}removeAttribute(){}
 showModal(){this.open=true;}close(){this.open=false;}
 reset(){for(const n of Object.values(this.elements)){n.value='';n.checked=false;}}
 querySelectorAll(){return this.children.flatMap(x=>typeof x==='object'?[...(x.tagName==='button'?[x]:[]),...x.querySelectorAll()]:[]);}
 async fire(name,event={}){for(const fn of this.listeners[name]||[])await fn(event);}
}
const wait=async predicate=>{for(let n=0;n<80;n++){if(predicate())return;await new Promise(setImmediate);}throw Error('VM fixture did not settle');};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
async function fixture({storageFailure=false,initialEntries=[]}={}){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
 get('channel-workspace').hidden=true;get('status-filter').value='error';
 for(const [form,names] of [['wa-form',['waba_id','phone_number_id','access_token']],['review-form',['review-note','review-confirm']]])for(const name of names)get(form).elements[name]=get(name);
 const tabs=['review','connections'].map(name=>{const x=new Element('button');x.dataset.tab=name;return x;});
 const entries=new Map(initialEntries),listeners={},documentListeners={},calls=[],navigations=[];
 const session={auth_method:'v1_user',user_id:uid,csrf_token:'synthetic-bound-csrf-never-real',businesses:[{id:bid,name:'Synthetic private boutique',role:'owner',capabilities:owner}]};
 let current=session,sessionHook=null,apiHook=null;
 const item={id:randomUUID(),customer_ref:'654321',message_preview:'SYNTHETIC_PRIVATE_MESSAGE',kinds:['text'],reason:'Synthetic review',created_at:'2026-10-18T00:00:00Z',status:'error'};
 const overview={business_id:bid,business_name:'Synthetic private boutique',capabilities:owner,channels:['instagram','whatsapp'].map(channel=>({channel,status:'paused',configured:true,account_hint:'••654321',checked_at:null,webhook_configured:false,automation_enabled:false,oauth_configured:true,connection_version:0}))};
 const api=async(path,options={})=>{calls.push({path,options});if(apiHook)return apiHook(path,options);return path.includes('/instagram/receipts')?{items:[item],next_cursor:null}:structuredClone(overview);};
 const storage={getItem:key=>entries.get(key)??null,setItem:(key,value)=>{if(storageFailure)throw Error('restricted');entries.set(key,value);},removeItem:key=>entries.delete(key)};
 const document={visibilityState:'visible',getElementById:get,createElement:tag=>new Element(tag),querySelectorAll:selector=>selector==='[data-tab]'?tabs:get('connections-list').querySelectorAll(),addEventListener:(name,fn)=>(documentListeners[name]??=[]).push(fn)};
 const window={V1:{session:async()=>{if(sessionHook)return sessionHook();if(current instanceof Error)throw current;return structuredClone(current);},api},addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)};
 const formData=class{constructor(form){this.form=form;}get(key){return this.form.elements[key].value;}};
 const sandbox={window,document,sessionStorage:storage,location:{pathname:`/v1/businesses/${bid}/channels`,search:'',assign(url){navigations.push(url);}},history:{replaceState(){}},crypto:{randomUUID,subtle:webcrypto.subtle},TextEncoder,URL,URLSearchParams,Date,Set,FormData:formData};
 vm.runInNewContext(source,sandbox);await wait(()=>get('receipt-rows').children.length===1);
 return{get,entries,calls,navigations,session,overview,item,storage,document,setSession:value=>{current=value;},sessionHook:value=>{sessionHook=value;},apiHook:value=>{apiHook=value;},focus:async()=>{for(const fn of listeners.focus||[])await fn();},changeVisibility:async value=>{document.visibilityState=value;for(const fn of documentListeners.visibilitychange||[])await fn();}};
}
test('confirmed401 physically clears facts, dialogs, token input and disables refresh',async()=>{
 const f=await fixture();f.get('access_token').value='synthetic-never-real-secret';f.get('wa-dialog').showModal();
 f.setSession(Object.assign(Error('revoked'),{status:401}));await f.get('refresh').fire('click');
 for(const id of ['receipt-rows','connections-list','review-components','review-history','command-message','command-current'])assert.equal(f.get(id).textContent,'',id);
 assert.equal(f.get('access_token').value,'');assert.equal(f.get('wa-dialog').open,false);assert.equal(f.get('refresh').disabled,true);assert.equal(f.get('logout').hidden,true);assert.equal(f.get('channel-workspace').hidden,true);
});
test('same-user replaced session on focus closes private access and old responses cannot revive it',async()=>{
 const f=await fixture(),held=deferred();let heldUsed=false;
 f.apiHook(async(path)=>{if(!heldUsed&&path.endsWith('/channels')){heldUsed=true;return held.promise;}return{items:[f.item],next_cursor:null};});
 const old=f.get('refresh').fire('click');await wait(()=>heldUsed);
 f.setSession({...f.session,csrf_token:'synthetic-replaced-bound-csrf'});await f.focus();held.resolve(structuredClone(f.overview));await old;
 assert.equal(f.get('connections-list').children.length,0);assert.equal(f.get('receipt-rows').children.length,0);assert.equal(f.get('channel-workspace').hidden,true);assert.equal(f.get('logout').hidden,true);
});
test('older session response cannot restore owner controls after newer viewer authority',async()=>{
 const f=await fixture(),held=deferred();let first=true;
 f.sessionHook(()=>{if(first){first=false;return held.promise;}return{...f.session,businesses:[{...f.session.businesses[0],role:'viewer',capabilities:['inbox.read']}]};});
 const old=f.get('refresh').fire('click');await wait(()=>!first);await f.focus();held.resolve(structuredClone(f.session));await old;
 assert.equal(f.get('connections-list').textContent.includes('Reconnect'),false);assert.equal(f.get('connections-list').textContent.includes('Disconnect'),false);assert.equal(f.get('logout').hidden,false);
});
test('visibility loss erases an entered token without a provider or mutation call',async()=>{
 const f=await fixture();f.get('access_token').value='synthetic-never-real-secret';await f.changeVisibility('hidden');assert.equal(f.get('access_token').value,'');assert.equal(f.calls.some(x=>x.options.method==='POST'),false);
});
test('unknown WA save persists only safe conditional marker and erases password; reload never autoPOSTs',async()=>{
 const f=await fixture();for(const [key,value] of Object.entries({waba_id:'1234567',phone_number_id:'7654321',access_token:'synthetic-never-real-secret'}))f.get(key).value=value;
 f.apiHook(async()=>{throw Error('synthetic dropped response');});await f.get('wa-form').fire('submit',{preventDefault(){},currentTarget:f.get('wa-form')});
 const raw=[...f.entries.values()].join('');assert(raw.includes('connect_whatsapp'));assert(raw.includes('"version":0'));assert(!raw.includes('synthetic-never-real-secret'));assert(!raw.includes('access_token'));assert.equal(f.get('access_token').value,'');assert.equal(f.get('command-retry').hidden,true);assert.equal(f.get('command-check').hidden,false);
 assert.equal(f.calls.filter(x=>x.options.method==='POST').length,1);
 const reloaded=await fixture({initialEntries:f.entries});assert.equal(reloaded.calls.some(x=>x.options.method==='POST'),false);assert.equal(reloaded.get('command-retry').hidden,true);assert.equal(reloaded.get('command-check').hidden,false);
});
test('restricted journal storage blocks mutation before POST and erases token',async()=>{
 const f=await fixture({storageFailure:true});for(const [key,value] of Object.entries({waba_id:'1234567',phone_number_id:'7654321',access_token:'synthetic-never-real-secret'}))f.get(key).value=value;
 await f.get('wa-form').fire('submit',{preventDefault(){},currentTarget:f.get('wa-form')});assert.equal(f.calls.some(x=>x.options.method==='POST'),false);assert.equal(f.get('access_token').value,'');assert(f.get('wa-error').textContent.includes('No action was sent'));
});
test('a delayed preparation guard reserves one command before concurrent submit awaits',async()=>{
 const f=await fixture(),held=deferred();let first=true;
 f.sessionHook(()=>{if(first){first=false;return held.promise;}return structuredClone(f.session);});
 f.apiHook(async(path,options)=>options.method==='POST'?{business_id:bid,idempotency_key:options.body.idempotency_key,action:'connect_whatsapp',status:'paused',connection_version:1}:path.includes('/instagram/receipts')?{items:[f.item],next_cursor:null}:structuredClone(f.overview));
 const fill=token=>{for(const [key,value] of Object.entries({waba_id:'1234567',phone_number_id:'7654321',access_token:token}))f.get(key).value=value;};
 fill('synthetic-first-never-real-secret');
 const one=f.get('wa-form').fire('submit',{preventDefault(){},currentTarget:f.get('wa-form')});await wait(()=>!first);
 fill('synthetic-second-never-real-secret');await f.get('wa-form').fire('submit',{preventDefault(){},currentTarget:f.get('wa-form')});
 assert.equal(f.calls.some(x=>x.options.method==='POST'),false);
 held.resolve(structuredClone(f.session));await one;
 const posts=f.calls.filter(x=>x.options.method==='POST');assert.equal(posts.length,1);assert.equal(posts[0].options.body.access_token,'synthetic-first-never-real-secret');assert.equal(f.entries.size,0);assert.equal(f.get('access_token').value,'');
});
test('a held command guard cannot launch a mutation after a newer401 ends access',async()=>{
 const f=await fixture(),held=deferred();let first=true;
 f.sessionHook(()=>{if(first){first=false;return held.promise;}throw Object.assign(Error('revoked'),{status:401});});
 for(const [key,value] of Object.entries({waba_id:'1234567',phone_number_id:'7654321',access_token:'synthetic-never-real-secret'}))f.get(key).value=value;
 const old=f.get('wa-form').fire('submit',{preventDefault(){},currentTarget:f.get('wa-form')});await wait(()=>!first);await f.focus();held.resolve(structuredClone(f.session));await old;
 assert.equal(f.calls.some(x=>x.options.method==='POST'),false);assert.equal(f.entries.size,0);assert.equal(f.get('access_token').value,'');assert.equal(f.get('logout').hidden,true);
});

test('valid-shaped old WA acknowledgement cannot clear a secret-bearing conditional intent',async()=>{
 const f=await fixture();for(const [key,value] of Object.entries({waba_id:'1234567',phone_number_id:'7654321',access_token:'synthetic-never-real-secret'}))f.get(key).value=value;
 f.apiHook(async(path,options)=>({business_id:bid,idempotency_key:options.body.idempotency_key,action:'connect_whatsapp',status:'paused',connection_version:0,message:'Old-shaped acknowledgement'}));
 await f.get('wa-form').fire('submit',{preventDefault(){},currentTarget:f.get('wa-form')});assert.equal(f.entries.size,1);assert.equal(f.get('command-check').hidden,false);assert.equal(f.get('access_token').value,'');
});
test('unclassified409 remains uncertain while exact typed pre-mutation generation conflict permits fresh review',async()=>{
 for(const typed of [false,true]){const f=await fixture();for(const [key,value] of Object.entries({waba_id:'1234567',phone_number_id:'7654321',access_token:'synthetic-never-real-secret'}))f.get(key).value=value;
 f.apiHook(async()=>{throw Object.assign(Error('Synthetic conflict'),{status:409,code:typed?'channel_generation_stale':null});});await f.get('wa-form').fire('submit',{preventDefault(){},currentTarget:f.get('wa-form')});assert.equal(f.entries.size,typed?0:1);assert.equal(f.get('access_token').value,'');}
});
test('unknown nonsecret operation reload explicitly retries exact body/key and never mints a replacement',async()=>{
 const f=await fixture();const button=f.get('connections-list').querySelectorAll().find(n=>n.textContent==='Disconnect');await button.fire('click');
 f.apiHook(async()=>{throw Error('Synthetic unknown response');});await f.get('confirm-action').onclick();
 const first=f.calls.find(x=>x.options.method==='POST'),saved=structuredClone(first.options.body);assert.equal(f.entries.size,1);
 const reloaded=await fixture({initialEntries:f.entries});assert.equal(reloaded.calls.some(x=>x.options.method==='POST'),false);assert.equal(reloaded.get('command-retry').hidden,false);
 reloaded.apiHook(async(path,options)=>options.method==='POST'?{business_id:bid,idempotency_key:options.body.idempotency_key,action:'disconnect_instagram',status:'disconnected',message:'Acknowledged'}:path.includes('/instagram/receipts')?{items:[reloaded.item],next_cursor:null}:structuredClone(reloaded.overview));
 await reloaded.get('command-retry').fire('click');const retry=reloaded.calls.find(x=>x.options.method==='POST');assert.equal(JSON.stringify(retry.options.body),JSON.stringify(saved));assert.equal(reloaded.entries.size,0);
});

test('an ended old page removes only its own session-scoped journal',async()=>{
 const f=await fixture(),newKey=`munimjee.v1.channel-command:${uid}:${bid}:new-session-hash`;
 f.entries.set(newKey,'new-session-command');f.setSession({...f.session,csrf_token:'new-valid-synthetic-session-csrf'});await f.focus();assert.equal(f.entries.get(newKey),'new-session-command');
});

test('a bound but invalid OAuth ACK retains original intent and cannot navigate',async()=>{
 const f=await fixture();f.apiHook(async(path,options)=>({business_id:bid,idempotency_key:options.body.idempotency_key,action:'start_instagram',status:'authorization_started',attempt_id:randomUUID(),authorization_url:'https://outside.invalid/oauth/authorize'}));
 const button=f.get('connections-list').querySelectorAll().find(n=>n.textContent==='Reconnect');await button.fire('click');assert.equal(f.entries.size,1);assert.deepEqual(f.navigations,[]);assert.equal(f.get('command-retry').hidden,false);
});
for(const kind of ['malformed','session','business','expired'])test(`recovered ${kind} journal is withheld without an implicit new action`,async()=>{
 const hash=value=>createHash('sha256').update(value).digest('hex'),sessionHash=hash('synthetic-bound-csrf-never-real');
 const command={action:'verify_instagram',path:'/instagram/verify',body:{idempotency_key:randomUUID()},version:null,secret:false};
 const core={user:uid,business:kind==='business'?randomUUID():bid,session:kind==='session'?'f'.repeat(64):sessionHash,created_at:Date.now()-(kind==='expired'?90000000:0),command};
 const raw=kind==='malformed'?'{':JSON.stringify({...core,checksum:hash(JSON.stringify(core))});
 const f=await fixture({initialEntries:[[`${'munimjee.v1.channel-command:'}${uid}:${bid}:${sessionHash}`,raw]]});
 assert(f.get('command-message').textContent.includes('cannot safely be recovered'));assert.equal(f.get('command-retry').hidden,true);assert.equal(f.calls.some(x=>x.options.method==='POST'),false);assert(f.get('connections-list').querySelectorAll().every(b=>b.disabled));
});
