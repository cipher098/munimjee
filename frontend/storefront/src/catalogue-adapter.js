// Deliberately fixture-only. No API call and no claim that readiness is frozen.
export function normalizeProduct(dto,presentation={}) {
  if(dto.contract_version!=='catalogue.v1' || dto.mode!=='preview_foundation' || dto.checkout_enabled!==false) throw new Error('Unsupported preview catalogue contract.');
  const requiresReview=dto.readiness?.state==='variant_stock_review';
  // Unknown readiness fails closed rather than treating null stock as review.
  const reviewed=dto.readiness?.state==='reviewed_sample';
  return {
    id:dto.product_id,
    slug:presentation.slug || dto.product_id,
    name:dto.name,
    description:dto.description,
    category:presentation.category || 'Collection',
    image:presentation.image || 'ivory.svg',
    tag:presentation.tag || 'Sample collection',
    skus:dto.skus.map(sku=>({
      id:sku.sku_id,
      size:sku.options.Size,
      color:sku.options.Colour,
      price_minor:sku.price_minor,
      currency:sku.currency,
      active:sku.active && reviewed,
      available_units:sku.stock_available,
      availability:requiresReview || !reviewed ? 'REVIEW_REQUIRED' : sku.stock_available===0 ? 'SOLD_OUT' : 'AVAILABLE',
    })),
  };
}
