// Synthetic public-only frozen catalogue.v1 fixtures. This module must never import seller records.
import {normalizeProduct} from './catalogue-adapter.js';
export const CONTRACT_VERSION = 'catalogue.v1';
export const business = Object.freeze({
  id: '11111111-1111-4111-8111-111111111111', // V1 alias for the legacy Seller.id UUID.
  name: 'Tara', currency: 'INR', preview: true,
  description: 'Thoughtful pieces, beautiful everyday rituals.',
  shipping_policy: 'Sample policy: delivery terms will be confirmed by the boutique before launch.',
  return_policy: 'Sample policy: returns and exchanges must be reviewed before publication.',
});
const sku = (id, size, color, price_minor, available_units, availability = available_units === 0 ? 'SOLD_OUT' : 'AVAILABLE') => ({id, size, color, price_minor, available_units, availability});
const presentationSamples = [
  {id:'22222222-2222-4222-8222-222222222201',slug:'gulab-occasion-set',name:'Gulab occasion set',category:'Occasionwear',description:'An illustrative celebration set in a deep rose palette. All descriptions, prices and inventory here are synthetic examples.',image:'rose.svg',tag:'The celebration edit',skus:[sku('33333333-3333-4333-8333-333333333301','S','Rose',689000,2),sku('33333333-3333-4333-8333-333333333302','M','Rose',689000,4),sku('33333333-3333-4333-8333-333333333303','L','Rose',689000,0)]},
  {id:'22222222-2222-4222-8222-222222222202',slug:'saanjh-drape-dress',name:'Saanjh drape dress',category:'Occasionwear',description:'A sculptural silhouette for slow evenings. Illustrative sample, with seller verification required for real garment details.',image:'saffron.svg',tag:'An evening favourite',skus:[sku('33333333-3333-4333-8333-333333333304','S','Saffron',549000,3),sku('33333333-3333-4333-8333-333333333305','M','Saffron',549000,1)]},
  {id:'22222222-2222-4222-8222-222222222203',slug:'everyday-cotton-kurta',name:'Everyday cotton kurta',category:'Kurtas',description:'A quiet staple in an earthy green palette. Sample product only; fabric and care details are illustrative.',image:'sage.svg',tag:'For your daily rotation',skus:[sku('33333333-3333-4333-8333-333333333306','S','Sage',189000,5),sku('33333333-3333-4333-8333-333333333307','M','Sage',189000,null)]},
  {id:'22222222-2222-4222-8222-222222222204',slug:'linen-weekend-co-ord',name:'Linen weekend co-ord',category:'Co-ords',description:'Easy proportions in a warm ivory palette. Synthetic catalogue sample; no real garment or fabric claim.',image:'ivory.svg',tag:'Easy, considered layers',skus:[sku('33333333-3333-4333-8333-333333333308','S','Ivory',325000,6),sku('33333333-3333-4333-8333-333333333309','M','Ivory',325000,3)]},
  {id:'22222222-2222-4222-8222-222222222205',slug:'indigo-day-dress',name:'Indigo day dress',category:'Dresses',description:'An illustrative relaxed silhouette, drawn in deep indigo. A synthetic example for browsing and size selection.',image:'indigo.svg',tag:'From morning to evening',skus:[sku('33333333-3333-4333-8333-333333333310','S','Indigo',279000,0),sku('33333333-3333-4333-8333-333333333311','M','Indigo',279000,0)]},
  {id:'22222222-2222-4222-8222-222222222206',slug:'heritage-layer',name:'Heritage layer',category:'Co-ords',description:'An example of a legacy product with unresolved variant inventory. It stays unavailable until each variant is reviewed.',image:'terracotta.svg',tag:'Awaiting catalogue review',skus:[sku('33333333-3333-4333-8333-333333333312','S','Clay',410000,null,'REVIEW_REQUIRED'),sku('33333333-3333-4333-8333-333333333313','M','Clay',410000,null,'REVIEW_REQUIRED')]},
];
// The envelope and string readiness match frozen catalogue.v1.
// Never connect this fixture to an API implicitly.
export const catalogueFixtures = presentationSamples.map((sample,index) => ({
  contract_version: CONTRACT_VERSION,
  mode: 'preview_foundation',
  business_id: business.id,
  product_id: sample.id,
  name: sample.name,
  description: sample.description,
  category_id: `44444444-4444-4444-8444-${String(index+1).padStart(12,'0')}`,
  photo_urls: [`./assets/${sample.image}`],
  readiness: sample.skus.some(sku=>sku.availability==='REVIEW_REQUIRED') ? 'needs_review' : 'reviewed',
  checkout_enabled: false,
  skus: sample.skus.map(sku=>({
    sku_id: sku.id, product_id: sample.id,
    options: {Size:sku.size, Colour:sku.color},
    price_minor:sku.price_minor, currency:business.currency,
    stock_available:sku.available_units,
    active:sku.availability!=='REVIEW_REQUIRED',
  })),
}));
export const products = catalogueFixtures.map((dto,index)=>normalizeProduct(dto, presentationSamples[index]));
export const themes = {
  editorial:{name:'Editorial occasionwear',suffix:'',eyebrow:'THE CELEBRATION EDIT',headline:'For moments\nthat stay.',intro:'Occasionwear, considered. A softer kind of statement.',cta:'Explore the edit',feature:0,caption:'A study in rose · Gulab occasion set',collection:'Pieces to make memories in.',label:'THE ART OF OCCASION'},
  catalogue:{name:'Everyday fashion',suffix:' / DAILY',eyebrow:'EVERYDAY, ELEVATED',headline:'Good pieces.\nGreat repeats.',intro:'Considered staples, easy layers, and a daily rotation that feels like you.',cta:'Find your everyday',feature:3,caption:'Easy layers · Linen weekend co-ord',collection:'Your next everyday favourite.',label:'A LITTLE LESS ORDINARY'},
  video:{name:'Video-led boutique',suffix:' / STUDIO',eyebrow:'A CLOSER LOOK',headline:'Made to move\nwith you.',intro:'Discover the pieces behind the story. Explore our illustrated studio study.',cta:'Explore the pieces',feature:1,caption:'Illustrated story study · no seller footage',collection:'From the story to your wardrobe.',label:'IN THE STUDIO'},
};
