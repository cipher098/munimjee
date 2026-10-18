/* Three of the frozen eight Node cases; exact production contract helpers.
 * No browser, DB, transport or runtime authority is established by these DTOs. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';

if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
const source=await readFile(new URL('../static/comment_operator_contract.js',import.meta.url),'utf8');
const contract=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const business='10000000-0000-4000-8000-000000000101',inbound='20000000-0000-4000-8000-000000000101',product='30000000-0000-4000-8000-000000000101';
const key='40000000-0000-4000-8000-000000000101',command='50000000-0000-4000-8000-000000000101',outbound='60000000-0000-4000-8000-000000000101';
const other='ffffffff-ffff-4fff-8fff-ffffffffffff';
const body={idempotency_key:key,action:'link_and_resume',product_id:product,shortcode:'Case_Ab-1',expected_fingerprint:'a'.repeat(64),expected_connection_version:3,confirmed:true};
const intent={operation:'reel_link',business,resource:inbound,path:`/api/v1/businesses/${business}/whatsapp/reel-enquiries/${inbound}/link`,method:'POST',body,summary:'Review this one enquiry',request_hash:'b'.repeat(64)};
const receipt={business_id:business,inbound_id:inbound,command_id:command,idempotency_key:key,action:body.action,product_id:product,request_hash:intent.request_hash,
  result:{mapping:'saved',resume:'queued',reason:null,outbound_id:outbound,mapping_fingerprint:'c'.repeat(64)},replayed:false};

test('N01 canonical business/inbound/body digest matches independent Python literal',async()=>{
  const input={business_id:business,inbound_id:inbound,body};
  assert.equal(await contract.digest(input),'f405d03c364dedbabcac1f1fd9d4598ced7f513f0205edd99aed98d72d50190a');
  for(const changed of [{...input,business_id:other},{...input,inbound_id:other},
    {...input,body:{...body,shortcode:'case_ab-1'}},{...input,body:{...body,action:'link_only'}},
    {...input,body:{...body,expected_connection_version:4}}])assert.notEqual(await contract.digest(input),await contract.digest(changed));
});

test('N02 exact detail and frozen intent reject caller scope or source promotion',()=>{
  const detail={business_id:business,inbound_id:inbound,message:'Synthetic original question',received_at:'2026-10-18T12:00:00+00:00',customer_name:'Synthetic buyer',customer_ref:'0000',account_hint:'…12345',
    source:{classification:'message_link',shortcode:'Case_Ab-1',url:'https://www.instagram.com/reel/Case_Ab-1/'},connection_version:3,fingerprint:'a'.repeat(64),matches:[],products:[{id:product,name:'Synthetic reviewed kurta'}],eligibility:{can_link:true,can_resume:true,reason:null},can_manage:true};
  assert.equal(contract.validReelDetail(detail,business),true);
  assert.equal(contract.validReelDetail({...detail,business_id:other},business),false);
  assert.equal(contract.validReelDetail({...detail,source:{...detail.source,classification:'recent_message'}},business),false);
  assert.equal(contract.validReelDetail({...detail,source:{...detail.source,classification:'recent_message'},eligibility:{can_link:true,can_resume:false,reason:'inferred_context'}},business),true);
  assert.equal(contract.validReelIntent(intent,business),true);
  for(const changed of [{...intent,business:other},{...intent,resource:other},{...intent,path:intent.path.replace(business,other)},
    {...intent,method:'DELETE'},{...intent,body:{...body,confirmed:1}},{...intent,body:{...body,source:'message_link'}},
    {...intent,body:{...body,expected_connection_version:true}},{...intent,body:{...body,recipient:'synthetic-other'}}])assert.equal(contract.validReelIntent(changed,business),false);
});

test('N03 receipt and typed rejection bind the exact command without delivery or source assertions',()=>{
  assert.equal(contract.validReelReceipt(receipt,intent),true);
  assert.equal(contract.validReelReceipt({...receipt,replayed:true},intent),true);
  for(const changed of [{...receipt,business_id:other},{...receipt,inbound_id:other},{...receipt,idempotency_key:other},
    {...receipt,action:'link_only'},{...receipt,product_id:other},{...receipt,request_hash:'d'.repeat(64)},
    {...receipt,result:{...receipt.result,delivered:true}},{...receipt,result:{...receipt.result,outbound_id:null}},
    {...receipt,result:{...receipt.result,reason:'accepted_by_provider'}},{...receipt,source:'message_link'}])assert.equal(contract.validReelReceipt(changed,intent),false);
  const rejection={status:409,code:'reel_operator_pre_mutation_rejection',reel_request_path:intent.path,reel_request_body:contract.stable(body)};
  assert.equal(contract.validReelRejection(rejection,intent),true);
  for(const changed of [{...rejection,status:422},{...rejection,code:'unclassified'},
    {...rejection,reel_request_path:intent.path.replace(inbound,other)},
    {...rejection,reel_request_body:contract.stable({...body,idempotency_key:other})},
    {status:409,code:rejection.code,detail:{accepted:false}}])assert.equal(contract.validReelRejection(changed,intent),false);
});
