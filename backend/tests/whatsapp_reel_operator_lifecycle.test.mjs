/* Five frozen lifecycle cases execute actual production UI in node:vm.
 * Controlled DOM + transport/session substitutes: no browser, HTTP, SQL or sender proof. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
const root=new URL('../static/',import.meta.url);
const helpers=await import('data:text/javascript;base64,'+Buffer.from(await readFile(new URL('comment_operator_contract.js',root),'utf8')).toString('base64'));
const source=(await readFile(new URL('comment_operator.js',root),'utf8')).replace(/^import[^\n]+\n/,'');
const html=await readFile(new URL('comment_operator.html',root),'utf8');
const business='10000000-0000-4000-8000-000000000101',inbound='20000000-0000-4000-8000-000000000101',product='30000000-0000-4000-8000-000000000101',key='40000000-0000-4000-8000-000000000101',user='70000000-0000-4000-8000-000000000101';
const owner={user_id:user,csrf_token:'synthetic-csrf',businesses:[{id:business,capabilities:['inbox.read','automation.manage']}]};
const saved={operation:'reel_link',business,resource:inbound,path:`/api/v1/businesses/${business}/whatsapp/reel-enquiries/${inbound}/link`,method:'POST',
 body:{idempotency_key:key,action:'link_and_resume',product_id:product,shortcode:'Case_Ab-1',expected_fingerprint:'a'.repeat(64),expected_connection_version:3,confirmed:true},
 summary:'Synthetic reviewed product: one selected enquiry',request_hash:'f405d03c364dedbabcac1f1fd9d4598ced7f513f0205edd99aed98d72d50190a'};
function harness(){
 const elements=new Map(),storage=new Map(),raw=[];
 class Element{
  constructor(tag='div'){Object.assign(this,{tag,value:'',textContent:'',hidden:false,disabled:false,open:false,dataset:{},children:[],checked:false});}
  addEventListener(){}setAttribute(){}removeAttribute(){}scrollIntoView(){}
  append(...rows){this.children.push(...rows);}replaceChildren(...rows){this.textContent='';this.children=[...rows];}
  get firstElementChild(){return this.children[0]||null;}
  reset(){for(const row of elements.values())if(['input','textarea','select'].includes(row.tag)){row.value='';row.checked=false;}}
  close(){this.open=false;}showModal(){this.open=true;}
 }
 for(const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g))elements.set(match[2],new Element(match[1]));
 function query(selector){if(selector==='[data-tab]'||selector==='.record-actions button')return [];
  if(selector==='form'||selector==='dialog')return [...elements.values()].filter(row=>row.tag===selector);
  if(selector==='input,textarea')return [...elements.values()].filter(row=>['input','textarea'].includes(row.tag));
  return [...elements.values()].filter(row=>['button','input','textarea','select'].includes(row.tag));}
 const document={cookie:'v1_csrf=synthetic-csrf',hidden:false,getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),querySelectorAll:query,addEventListener(){}};
 const context=vm.createContext({...helpers,console,crypto:webcrypto,TextEncoder,URLSearchParams,document,
  location:{pathname:`/v1/businesses/${business}/comment-automation`},
  sessionStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  window:{addEventListener(){},V1:{session:()=>new Promise(()=>{}),api:async(...args)=>{raw.push(args);return {};}}}});
 vm.runInContext(source+`\n globalThis.probe={
  setup(value){identity='${user}:synthetic-csrf';storageKey='owned-comment';reelStorageKey='owned-reel';sessionScope='synthetic-scope';canManage=true;viewReady=true;tab='reels';reelIntent=value;selected={kind:'reels',can_manage:true,eligibility:{can_link:true,can_resume:true}};},
  state(){return {ended,viewReady,reelIntent,selected,canManage,busy};},
  setAPI(fn){api=fn;},setSession(fn){window.V1.session=fn;},setRaw(fn){window.V1.api=fn;},
  sendReel,session,api,fence,recoverReel,prepareReel
 };`,context);
 return {probe:context.probe,storage,elements,raw,document};
}
function pending(h){h.probe.setup(saved);h.storage.set('owned-reel',JSON.stringify(saved));return JSON.stringify(saved);}

test('N04 unrelated well-shaped200 retains exact uncertain journal and blocks fresh action',async()=>{
 const h=harness(),original=pending(h);let calls=0;
 h.probe.setAPI(async(path,options)=>{calls++;assert.equal(path,saved.path);assert.equal(options.body,saved.body);return {business_id:business,inbound_id:'ffffffff-ffff-4fff-8fff-ffffffffffff',command_id:key,idempotency_key:key,action:'link_and_resume',product_id:product,request_hash:saved.request_hash,result:{mapping:'saved',resume:'queued',reason:null,outbound_id:product,mapping_fingerprint:'c'.repeat(64)},replayed:false};});
 await h.probe.sendReel();assert.equal(calls,1);assert.equal(h.probe.state().reelIntent,saved);assert.equal(h.storage.get('owned-reel'),original);assert.equal(h.probe.state().viewReady,false);assert.equal(h.elements.get('reel-resume').disabled,true);assert.equal(h.elements.get('notice').textContent,'');
});

test('N05 unclassified409 and422 retry only same frozen key/body and preserve journal',async()=>{
 for(const status of [409,422]){const h=harness(),original=pending(h),requests=[];
  h.probe.setAPI(async(path,options)=>{requests.push({path,method:options.method,body:options.body});throw Object.assign(Error('Unclassified synthetic response'),{status});});
  await h.probe.sendReel();await h.probe.sendReel();
  assert.equal(requests.length,2);for(const request of requests){assert.equal(request.path,saved.path);assert.equal(request.method,'POST');assert.equal(request.body,saved.body);assert.equal(request.body.idempotency_key,key);}
  assert.equal(h.storage.get('owned-reel'),original);assert.equal(h.probe.state().reelIntent,saved);assert.equal(h.probe.state().viewReady,false);
 }
});

test('N06 only exact typed pre-effect409 releases journal and still requires fresh review',async()=>{
 const h=harness();pending(h);h.storage.set('replacement-session','keep');
 h.probe.setSession(async()=>owner);h.probe.setRaw(async(path,options)=>{assert.equal(path,saved.path);assert.equal(options.body,saved.body);throw Object.assign(Error('Review changed before effects'),{status:409,code:'reel_operator_pre_mutation_rejection'});});
 await h.probe.sendReel();assert.equal(h.probe.state().reelIntent,null);assert.equal(h.storage.has('owned-reel'),false);assert.equal(h.storage.get('replacement-session'),'keep');assert.equal(h.probe.state().viewReady,false);assert.equal(h.elements.get('reel-resume').disabled,true);assert.match(h.elements.get('notice').textContent,/not accepted.*Refresh/);
});

test('N07 actual api401 scrubs private reel DOM and only owned journals',async()=>{
 const h=harness();pending(h);h.storage.set('owned-comment','private');h.storage.set('another-business','keep');h.storage.set('replacement-session','keep');
 for(const id of ['reel-meta','reel-message','reel-source','reel-eligibility','reel-recovery-summary'])h.elements.get(id).textContent='Private synthetic content';h.elements.get('reel-dialog').open=true;
 h.probe.setSession(async()=>owner);h.probe.setRaw(async()=>{throw Object.assign(Error('Unauthorized'),{status:401});});
 await h.probe.sendReel();assert.equal(h.probe.state().ended,true);assert.equal(h.probe.state().reelIntent,null);assert.equal(h.probe.state().selected,null);
 for(const id of ['reel-meta','reel-message','reel-source','reel-eligibility','reel-recovery-summary'])assert.equal(h.elements.get(id).textContent,'');
 assert.equal(h.elements.get('reel-dialog').open,false);assert.equal(h.elements.get('workspace').hidden,true);assert.equal(h.storage.has('owned-reel'),false);assert.equal(h.storage.has('owned-comment'),false);assert.equal(h.storage.get('another-business'),'keep');assert.equal(h.storage.get('replacement-session'),'keep');
});

test('N08 replacement-session fence prevents late old guard dispatch or deletion of newer journal',async()=>{
 const h=harness();pending(h);let releaseOld,calls=0;
 h.storage.set('replacement-session','newer exact intent');h.storage.set('another-business','keep');
 h.probe.setSession(()=>++calls===1?new Promise(resolve=>{releaseOld=resolve;}):Promise.resolve({...owner,csrf_token:'replacement-csrf'}));
 const request=h.probe.api(saved.path,{method:'POST',body:saved.body});
 h.document.cookie='v1_csrf=replacement-csrf';await assert.rejects(h.probe.session(),/access changed/);releaseOld(owner);await assert.rejects(request,/access changed/);
 assert.equal(h.raw.length,0);assert.equal(h.probe.state().ended,true);assert.equal(h.storage.has('owned-reel'),false);assert.equal(h.storage.get('replacement-session'),'newer exact intent');assert.equal(h.storage.get('another-business'),'keep');
});
