import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';

if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
const source=await readFile(new URL('../static/comment_operator_contract.js',import.meta.url),'utf8');
const contracts=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const id='12345678-1234-4234-8234-123456789abc',other='12345678-1234-4234-8234-123456789def',business='12345678-1234-4234-8234-123456789aaa';
const body={idempotency_key:id,expected_fingerprint:'a'.repeat(64),confirmed:true,reason:'Checked the original conversation'};
const intent={operation:'comment_close',resource:id,path:`/api/v1/businesses/${business}/comment-automation/events/${id}/reviews`,method:'POST',body,summary:'Close review without send',request_hash:'b'.repeat(64)};
const receipt={command_id:other,idempotency_key:id,operation:'comment_close',request_hash:'b'.repeat(64),result:{resource_id:id,fingerprint:'c'.repeat(64)},replayed:false};

test('canonical command fingerprint matches Python with mixed language, emoji and case-sensitive frozen text',async()=>{
  const value={operation:'rule_update',resource_id:id,body:{name:'साड़ी 👗',enabled:false,keywords:['PRICE','Straße'],public_reply:null}};
  assert.equal(await contracts.digest(value),'e26597803ee90e6fc3fef8060083c69a14221f521227fb0202456b72086a7831');
  assert.notEqual(await contracts.digest(value),await contracts.digest({...value,body:{...value.body,keywords:['price','strasse']}}));
});

test('well-shaped old acknowledgement cannot confirm a different exact command or target',()=>{
  assert.ok(contracts.validReceipt(receipt,intent));
  for(const patch of [{idempotency_key:other},{request_hash:'d'.repeat(64)},{operation:'enquiry_close'},
    {result:{resource_id:other,fingerprint:'c'.repeat(64)}},{result:{resource_id:id,fingerprint:'c'.repeat(64),delivered:true}},
    {command_id:'invalid'},{replayed:'true'}])assert.equal(contracts.validReceipt({...receipt,...patch},intent),false);
});

test('exact receipt replay is a separate acknowledgement and never delivery evidence',()=>{
  assert.ok(contracts.validReceipt({...receipt,replayed:true},intent));
  assert.equal(Object.hasOwn(receipt.result,'delivered'),false);
});

test('recovery cannot change method, route, business, target or review confirmation',()=>{
  assert.ok(contracts.validIntent(intent,business));
  for(const patch of [{method:'DELETE'},{resource:other},{path:intent.path.replace(business,other)},
    {body:{...body,confirmed:1}},{body:{...body,delivered:true}},{summary:'\ud800'}])assert.equal(contracts.validIntent({...intent,...patch},business),false);
});

test('recovery rule scopes remain explicit and cannot be reconstructed from arbitrary URL/body',()=>{
  const facts={name:'Saved dress reply',enabled:false,media_id:'123456',keywords:['price','कीमत'],product_id:id,private_reply:'The team can help 👗',public_reply:null};
  const create={operation:'rule_create',resource:null,path:`/api/v1/businesses/${business}/comment-automation/rules`,method:'POST',
    body:{idempotency_key:id,expected_fingerprint:null,facts},summary:'Create saved dress reply',request_hash:'b'.repeat(64)};
  assert.ok(contracts.validIntent(create,business));
  for(const patch of [{media_id:null},{product_id:other.slice(1)},{enabled:1},{private_reply:'\ud800'},{keywords:['\x00']}])assert.equal(contracts.validIntent({...create,body:{...create.body,facts:{...facts,...patch}}},business),false);
});

test('legacy wildcard rule is inspectable/disableable but is never admitted as a new native rule scope',()=>{
  const facts={name:'Legacy rule',enabled:true,media_id:null,keywords:['price'],product_id:id,private_reply:'Saved copy',public_reply:null};
  assert.ok(contracts.validRule({...facts,id,fingerprint:'a'.repeat(64)}));
  assert.equal(contracts.validFacts(facts),false);
});
