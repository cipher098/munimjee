// Pure client-side preview rules. Server prices, locks and checkout remain authoritative.
export const MAX_UNTRACKED_PREVIEW_QUANTITY = 10;
export function validateSku(sku) {
  if (!sku || !Number.isSafeInteger(sku.price_minor) || sku.price_minor < 0 || sku.currency !== 'INR' || typeof sku.active !== 'boolean') return false;
  if (!['AVAILABLE','SOLD_OUT','REVIEW_REQUIRED'].includes(sku.availability)) return false;
  if (sku.available_units !== null && (!Number.isSafeInteger(sku.available_units) || sku.available_units < 0)) return false;
  if (sku.availability === 'AVAILABLE' && sku.available_units === 0) return false;
  if (sku.availability === 'SOLD_OUT' && sku.available_units !== 0) return false;
  return true;
}
export function limitFor(sku) {
  if (!validateSku(sku) || sku.availability !== 'AVAILABLE' || !sku.active) return 0;
  return sku.available_units ?? MAX_UNTRACKED_PREVIEW_QUANTITY;
}
export function stockText(sku) {
  if (!validateSku(sku)) return 'Stock unavailable';
  if (sku.availability === 'REVIEW_REQUIRED') return 'Variant stock needs review';
  if (!sku.active) return 'Currently unavailable';
  if (sku.availability === 'SOLD_OUT') return 'Sold out';
  return sku.available_units === null ? 'Stock untracked · confirmed at real checkout' : `${sku.available_units} available in this sample`;
}
export function findSku(catalogue, skuId) {
  for (const product of catalogue) {
    const sku = product.skus.find(item => item.id === skuId);
    if (sku) return {product, sku};
  }
  return null;
}
export function addItem(cart, catalogue, skuId, quantity=1) {
  const match = findSku(catalogue, skuId);
  if (!match || !Number.isSafeInteger(quantity) || quantity < 1) return {ok:false,error:'Choose a valid quantity.'};
  const current = cart.find(item=>item.sku_id===skuId)?.quantity || 0;
  if (current + quantity > limitFor(match.sku)) return {ok:false,error:limitFor(match.sku) === 0 ? stockText(match.sku) : 'The sample stock limit has been reached.'};
  const next = cart.filter(item=>item.sku_id!==skuId);
  next.push({sku_id:skuId,quantity:current+quantity});
  return {ok:true,cart:next};
}
export function setQuantity(cart,catalogue,skuId,quantity) {
  if (!Number.isSafeInteger(quantity) || quantity < 0) return {ok:false,error:'Choose a valid quantity.'};
  if (!cart.some(line=>line.sku_id===skuId)) return {ok:false,error:'Item is not in the bag.'};
  if (quantity === 0) return {ok:true,cart:cart.filter(line=>line.sku_id!==skuId)};
  const match = findSku(catalogue,skuId);
  if (!match || quantity > limitFor(match.sku)) return {ok:false,error:'The sample stock limit has been reached.'};
  return {ok:true,cart:cart.map(line=>line.sku_id===skuId?{...line,quantity}:line)};
}
export function previewSubtotal(cart,catalogue) {
  return cart.reduce((sum,line)=>{
    const match=findSku(catalogue,line.sku_id);
    if(!match || !validateSku(match.sku) || !Number.isSafeInteger(line.quantity) || line.quantity<1 || line.quantity>limitFor(match.sku)) throw new Error('The bag needs review.');
    const total=sum+match.sku.price_minor*line.quantity;
    if(!Number.isSafeInteger(total)) throw new Error('Sample subtotal exceeds the supported range.');
    return total;
  },0);
}
export function checkoutProposal(cart,catalogue,idempotencyKey) {
  if (!cart.length || cart.some(line=>!findSku(catalogue,line.sku_id) || !Number.isSafeInteger(line.quantity) || line.quantity < 1 || line.quantity > limitFor(findSku(catalogue,line.sku_id).sku))) throw new Error('The bag needs review.');
  if (new Set(cart.map(line=>line.sku_id)).size !== cart.length) throw new Error('Duplicate SKU lines are invalid.');
  return {idempotency_key:idempotencyKey,items:cart.map(({sku_id,quantity})=>({sku_id,quantity}))};
}
