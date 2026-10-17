import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {money,productPriceText} from '../src/components.js';
import assert from 'node:assert/strict';
import {products,catalogueFixtures,business} from '../src/fixtures.js';
import {normalizeProduct} from '../src/catalogue-adapter.js';
import {limitFor,stockText,addItem,setQuantity,previewSubtotal,checkoutProposal,validateSku} from '../src/commerce.js';
const tracked=products[0].skus[0];
const untracked=products[2].skus[1];
const sold=products[4].skus[0];
const review=products[5].skus[0];
test('public fixture DTO has the catalogue.v1 envelope and public SKU names',()=>{
 for(const dto of catalogueFixtures){
  assert.equal(dto.contract_version,'catalogue.v1');assert.equal(dto.mode,'preview_foundation');assert.equal(dto.business_id,business.id);assert.equal(dto.checkout_enabled,false);
  assert.ok(['needs_review','default_backfilled','reviewed','stale'].includes(dto.readiness));
  assert.deepEqual(Object.keys(dto).sort(),['contract_version','mode','business_id','product_id','name','description','category_id','photo_urls','readiness','checkout_enabled','skus'].sort());
  for(const sku of dto.skus){assert.deepEqual(Object.keys(sku).sort(),['sku_id','product_id','options','price_minor','currency','stock_available','active'].sort());assert.equal(sku.product_id,dto.product_id);}
 }
 assert.doesNotMatch(JSON.stringify(catalogueFixtures),/floor|credential|gateway|private|internal_price|seller_note/i);
});
test('tracked, untracked, sold out and unresolved stock remain distinct',()=>{
 assert.equal(limitFor(tracked),2);assert.equal(limitFor(untracked),10);assert.equal(limitFor(sold),0);assert.equal(limitFor(review),0);
 assert.match(stockText(untracked),/untracked/);assert.match(stockText(review),/review/);assert.match(stockText(sold),/Sold out/);
 assert.equal(review.available_units,null);assert.equal(untracked.available_units,null);
});
test('same SKU aggregates and cannot exceed available units',()=>{
 let result=addItem([],products,tracked.id);assert.equal(result.ok,true);
 result=addItem(result.cart,products,tracked.id);assert.equal(result.ok,true);assert.deepEqual(result.cart,[{sku_id:tracked.id,quantity:2}]);
 assert.equal(addItem(result.cart,products,tracked.id).ok,false);
 assert.equal(setQuantity(result.cart,products,tracked.id,3).ok,false);
 assert.equal(previewSubtotal(result.cart,products),tracked.price_minor*2);
 assert.deepEqual(setQuantity(result.cart,products,tracked.id,0).cart,[]);
});
test('invalid quantities and unknown SKU cannot enter a bag',()=>{
 for(const qty of [0,-1,1.5,NaN,Infinity,'1']) assert.equal(addItem([],products,tracked.id,qty).ok,false);
 assert.equal(addItem([],products,'unknown').ok,false);
 assert.equal(addItem([],products,sold.id).ok,false);assert.equal(addItem([],products,review.id).ok,false);
 assert.equal(addItem([],products,untracked.id,11).ok,false);
});
test('inactive and unsupported currency SKUs fail closed',()=>{
 for(const sku of [{...tracked,active:false},{...tracked,currency:'USD'},{...tracked,price_minor:-1},{...tracked,available_units:0},{...tracked,available_units:NaN}]) assert.equal(limitFor(sku),0);
 assert.equal(validateSku({...tracked,currency:'USD'}),false);
 const foreign=[{...products[0],skus:[{...tracked,currency:'USD'}]}];
 assert.equal(addItem([],foreign,tracked.id).ok,false);
 assert.throws(()=>previewSubtotal([{sku_id:tracked.id,quantity:1}],foreign));
 assert.throws(()=>checkoutProposal([{sku_id:tracked.id,quantity:1}],foreign,'key'));
});
test('unknown readiness and checkout-enabled API responses are never silently enabled',()=>{
 const dto={...catalogueFixtures[0],readiness:'new-server-value'};
 assert.ok(normalizeProduct(dto).skus.every(sku=>limitFor(sku)===0));
 assert.throws(()=>normalizeProduct({...dto,checkout_enabled:true}));
});
test('unsubmitted checkout proposal has SKU quantities and key only, no tenant or prices',()=>{
 const cart=[{sku_id:tracked.id,quantity:2}];
 assert.deepEqual(checkoutProposal(cart,products,'local-key'),{idempotency_key:'local-key',items:cart});
 assert.throws(()=>checkoutProposal([],products,'key'));
 assert.throws(()=>checkoutProposal([...cart,...cart],products,'key'));
 assert.throws(()=>checkoutProposal([{sku_id:sold.id,quantity:1}],products,'key'));
});

test('actual frozen B10 DTOs preserve review and available stock semantics',()=>{
 const root=new URL('../../../docs/contracts/catalogue/',import.meta.url);
 const reviewed=JSON.parse(readFileSync(new URL('variants-reviewed-read.json',root)));
 const pending=JSON.parse(readFileSync(new URL('variants-needs-review-read.json',root)));
 const nonvariant=JSON.parse(readFileSync(new URL('nonvariant-read.json',root)));
 assert.equal(normalizeProduct(nonvariant).skus[0].label,'Default');
 const product=normalizeProduct(reviewed);
 assert.equal(product.skus.length,reviewed.skus.length);
 assert.ok(product.skus.some(sku=>sku.active && limitFor(sku)>0));
 assert.ok(normalizeProduct(pending).skus.every(sku=>limitFor(sku)===0));
 for(const readiness of ['stale','default_backfilled',{state:'reviewed_sample'},null]){
  assert.ok(normalizeProduct({...reviewed,readiness}).skus.every(sku=>limitFor(sku)===0));
 }
});
test('INR display preserves paise from server minor units',()=>{
 assert.equal(money(129950),'₹1,299.50');
 assert.equal(money(100001),'₹1,000.01');
 assert.equal(money(689000),'₹6,890');
});

test('products awaiting SKU review do not show an infinite price or crash',()=>{
 const dto=JSON.parse(readFileSync(new URL('../../../docs/contracts/catalogue/variants-needs-review-read.json',import.meta.url)));
 assert.equal(productPriceText(normalizeProduct(dto)),'Price after review');
 assert.equal(normalizeProduct(dto).readiness,'needs_review');
});
