// Frozen catalogue.v1 preview adapter. No API call or server checkout authority.
export function normalizeProduct(dto,presentation={}) {
  if(dto.contract_version!=='catalogue.v1' || dto.mode!=='preview_foundation' || dto.checkout_enabled!==false) throw new Error('Unsupported preview catalogue contract.');
  const requiresReview=dto.readiness==='needs_review';
  // Only seller-reviewed snapshots are selectable in this local preview.
  // Backfilled/stale/unknown snapshots remain disabled until review.
  const reviewed=dto.readiness==='reviewed';
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
      label:Object.values(sku.options).join(' / ') || 'Default',
      price_minor:sku.price_minor,
      currency:sku.currency,
      active:sku.active && reviewed,
      available_units:sku.stock_available,
      availability:requiresReview || !reviewed ? 'REVIEW_REQUIRED' : sku.stock_available===0 ? 'SOLD_OUT' : 'AVAILABLE',
    })),
  };
}
