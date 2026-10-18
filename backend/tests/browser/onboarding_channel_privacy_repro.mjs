/* Read-only VM behavioral reproduction against the actual private-page script.
 * Minimal DOM/API doubles; not rendered browser, live auth, or provider evidence. */
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import vm from 'node:vm';
import {createHash,randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const sourcePath=new URL('../../static/channel_operator.js',import.meta.url);
const source=await readFile(sourcePath,'utf8');
class Element {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.hidden=false;this.value='';this._text='';}
 set textContent(value){this._text=String(value);this.children=[];}get textContent(){return this._text+this.children.map(x=>typeof x==='string'?x:x.textContent).join('');}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this._text='';this.children=[...nodes];}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}setAttribute(){}removeAttribute(){}
 showModal(){this.open=true;}close(){this.open=false;}
 async fire(name,event={}){for(const fn of this.listeners[name]||[])await fn(event);}
}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
const tabs=['review','connections'].map(name=>{const x=new Element('button');x.dataset.tab=name;return x;});
get('status-filter').value='error';
let ended=false;
const item={id:randomUUID(),customer_ref:'987654',message_preview:'SYNTHETIC_PRIVATE_CUSTOMER_TEXT',kinds:['text'],reason:'Synthetic private review reason',created_at:'2026-10-18T00:00:00Z',status:'error'};
const sandbox={document:{getElementById:get,createElement:tag=>new Element(tag),querySelectorAll:()=>tabs},
 location:{pathname:'/v1/businesses/11111111-1111-4111-8111-111111111111/channels',search:'',assign(){}},history:{replaceState(){}},
 sessionStorage:{getItem(){return null;},setItem(){},removeItem(){}},crypto:{randomUUID},URL,URLSearchParams,Date,Set,FormData,
 fetch:async path=>({ok:!ended,status:ended?401:200,json:async()=>ended?{detail:'Session expired or revoked'}:
 path==='/api/v1/auth/session'?{user_id:'synthetic-owner',csrf_token:'synthetic-csrf'}:
 path.includes('/instagram/receipts')?{items:[item],next_cursor:null}:
 {business_name:'SYNTHETIC_PRIVATE_BUSINESS',capabilities:['channels.connect','channels.disconnect'],channels:[{channel:'whatsapp',status:'paused',configured:true,account_hint:'••654321',checked_at:null,webhook_configured:false,automation_enabled:false}]}})};
vm.runInNewContext(source,sandbox,{filename:fileURLToPath(sourcePath)});
for(let i=0;i<20&&!get('receipt-rows').children.length;i++)await new Promise(setImmediate);
assert.equal(get('receipt-rows').children.length,1,'Fixture must reach the actual loaded-page code path');
get('wa-dialog').showModal();const secretInput=new Element('input');secretInput.value='SYNTHETIC_NEVER_REAL_SECRET';get('wa-form').append(secretInput);
ended=true;await get('refresh').fire('click');
const result={source_sha256:createHash('sha256').update(source).digest('hex'),evidence_kind:'VM actual script with minimal DOM/API doubles; no rendered or database claim',observed_401_error:get('global-error').textContent.includes('session ended'),business_retained:get('business-name').textContent.includes('SYNTHETIC_PRIVATE_BUSINESS'),customer_text_retained:get('receipt-rows').textContent.includes('SYNTHETIC_PRIVATE_CUSTOMER_TEXT'),connections_retained:get('connections-list').children.length>0,secret_input_retained:secretInput.value.length>0,secret_dialog_open:get('wa-dialog').open===true};
assert.equal(result.observed_401_error,true);
assert.equal(result.business_retained&&result.customer_text_retained&&result.connections_retained&&result.secret_input_retained&&result.secret_dialog_open,true,'Current issue must reproduce before being reported');
const out=new URL('../../../artifacts/v1/onboarding-acceptance/',import.meta.url);await mkdir(out,{recursive:true});await writeFile(new URL('channel-401-retention-repro.json',out),JSON.stringify(result,null,2)+'\n');console.log('CONFIRMED: actual channel script retains private business/message/connection/secret-input DOM after401. VM evidence only; no DB/browser/provider calls.');
