/* Exact production JS with a controlled DOM substitute; no browser/API/DB. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

const root=new URL('../static/',import.meta.url);
const helpers=await import('data:text/javascript;base64,'+Buffer.from(await readFile(new URL('comment_operator_contract.js',root),'utf8')).toString('base64'));
const source=(await readFile(new URL('comment_operator.js',root),'utf8')).replace(/^import[^\n]+\n/,'');
const html=await readFile(new URL('comment_operator.html',root),'utf8');
const business='12345678-1234-4234-8234-123456789aaa',user='12345678-1234-4234-8234-123456789bbb';
const owner={user_id:user,csrf_token:'synthetic-csrf',businesses:[{id:business,capabilities:['inbox.read','automation.manage']}]};
const saved={operation:'comment_close',resource:'12345678-1234-4234-8234-123456789abc',
  path:`/api/v1/businesses/${business}/comment-automation/events/12345678-1234-4234-8234-123456789abc/reviews`,method:'POST',
  body:{idempotency_key:'12345678-1234-4234-8234-123456789def',expected_fingerprint:'a'.repeat(64),confirmed:true,reason:'Reviewed original conversation'},
  summary:'Close original review without send',request_hash:'b'.repeat(64)};

function harness(){
  const elements=new Map(),tags=new Map(),storage=new Map(),raw=[];
  class Element{
    constructor(tag='div'){this.tag=tag;this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.open=false;this.dataset={};this.children=[];this.checked=false;}
    addEventListener(){}setAttribute(){}removeAttribute(){}scrollIntoView(){}
    append(...rows){this.children.push(...rows);}replaceChildren(...rows){this.textContent='';this.children=[...rows];}
    get firstElementChild(){return this.children[0]||null;}
    reset(){for(const row of elements.values())if(['input','textarea','select'].includes(row.tag)){row.value='';row.checked=false;}}
    close(){this.open=false;}showModal(){this.open=true;}
  }
  for(const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)){elements.set(match[2],new Element(match[1]));tags.set(match[2],match[1]);}
  function query(selector){if(selector==='[data-tab]'||selector==='.record-actions button')return [];
    if(selector==='form')return [...elements.values()].filter(row=>row.tag==='form');
    if(selector==='dialog')return [...elements.values()].filter(row=>row.tag==='dialog');
    if(selector==='input,textarea')return [...elements.values()].filter(row=>['input','textarea'].includes(row.tag));
    if(selector.includes('#rule-form'))return [...elements.values()].filter(row=>['input','textarea','select'].includes(row.tag));
    return [...elements.values()].filter(row=>['button','input','textarea','select'].includes(row.tag));}
  const document={cookie:'v1_csrf=synthetic-csrf',hidden:false,getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),querySelectorAll:query,addEventListener(){}};
  const context=vm.createContext({...helpers,console,crypto:webcrypto,TextEncoder,URLSearchParams,
    document,location:{pathname:`/v1/businesses/${business}/comment-automation`},
    sessionStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    window:{addEventListener(){},V1:{session:()=>new Promise(()=>{}),api:async(...args)=>{raw.push(args);return {};}}}});
  vm.runInContext(source+`\n globalThis.probe={
    setup(value){identity='${user}:synthetic-csrf';storageKey='owned-key';canManage=true;viewReady=true;intent=value;selected={can_close:true};editing={name:'Private rule'};},
    state(){return {ended,viewReady,intent,selected,editing,canManage};},
    setSession(fn){window.V1.session=fn;},setAPI(fn){api=fn;},fence,invalidateReads,load,send,session,api,
    command(){return command('comment_close','unused','unused','POST',{},'must not dispatch');}
  };`,context);
  return {probe:context.probe,storage,elements,raw};
}

test('old page fence deletes only its owned journal, not a replacement session or another business',()=>{
  const h=harness();h.probe.setup(saved);h.storage.set('owned-key','original');h.storage.set('newer-session-key','keep');h.storage.set('other-business-key','keep');
  h.elements.get('detail-content').textContent='Private customer message';h.elements.get('rule-private').value='Private draft reply';
  h.probe.fence('Session changed');
  assert.equal(h.storage.has('owned-key'),false);assert.equal(h.storage.get('newer-session-key'),'keep');assert.equal(h.storage.get('other-business-key'),'keep');
  assert.equal(h.elements.get('detail-content').textContent,'');assert.equal(h.elements.get('rule-private').value,'');assert.equal(h.probe.state().selected,null);
});

test('ordinary read failure scrubs stale rows/editor and blocks fresh writes, preserving exact pending intent',async()=>{
  const h=harness();h.probe.setup(saved);h.storage.set('owned-key',JSON.stringify(saved));h.elements.get('records').textContent='Old private comment';h.elements.get('rule-private').value='Old static copy';h.elements.get('detail-dialog').open=true;
  h.probe.invalidateReads();
  assert.equal(h.elements.get('records').textContent,'');assert.equal(h.elements.get('rule-private').value,'');assert.equal(h.elements.get('detail-dialog').open,false);assert.equal(h.probe.state().viewReady,false);
  assert.equal(h.probe.state().intent,saved);assert.equal(h.storage.get('owned-key'),JSON.stringify(saved));assert.equal(h.elements.get('new-rule').disabled,true);
  await h.probe.command();assert.equal(h.raw.length,0);
  h.probe.setAPI(async()=>({items:[],next_cursor:null,can_manage:true}));await h.probe.load();assert.equal(h.probe.state().viewReady,true);assert.equal(h.probe.state().intent,saved);
});

test('unclassified409 after POST keeps same key/body and disables new work',async()=>{
  const h=harness();h.probe.setup(saved);h.storage.set('owned-key',JSON.stringify(saved));
  h.probe.setAPI(async()=>{throw Object.assign(Error('Unclassified intermediary response'),{status:409,code:null});});
  await h.probe.send();assert.equal(h.probe.state().intent,saved);assert.equal(h.storage.get('owned-key'),JSON.stringify(saved));assert.equal(h.probe.state().viewReady,false);
});

test('only typed pre-mutation stale rejection releases a command and still requires fresh facts',async()=>{
  const h=harness();h.probe.setup(saved);h.storage.set('owned-key',JSON.stringify(saved));
  h.probe.setAPI(async()=>{throw Object.assign(Error('Changed before acceptance'),{status:409,code:'comment_operator_context_changed'});});
  await h.probe.send();assert.equal(h.probe.state().intent,null);assert.equal(h.storage.has('owned-key'),false);assert.equal(h.probe.state().viewReady,false);assert.equal(h.elements.get('new-rule').disabled,true);
});

test('older successful session guard cannot dispatch after a newer role downgrade',async()=>{
  const h=harness();h.probe.setup(null);let releaseOld,calls=0;
  h.probe.setSession(()=>++calls===1?new Promise(resolve=>{releaseOld=resolve;}):Promise.resolve({...owner,businesses:[{id:business,capabilities:['inbox.read']}]}));
  const request=h.probe.api('/api/v1/businesses/'+business+'/comment-automation/events',{});
  await h.probe.session();releaseOld(owner);await assert.rejects(request,/newer sign-in check/);assert.equal(h.raw.length,0);assert.equal(h.probe.state().canManage,false);
});

test('back link uses mounted native business picker route',()=>{
  assert.ok(source.includes('`/v1?business=${encodeURIComponent(business)}`'));
  assert.equal(source.includes('href=`/v1/businesses/${business}`'),false);
});
