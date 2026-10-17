import {validateSku} from './commerce.js';
// Never interpolate catalogue, branding or policy strings into HTML.
export function el(tag, attributes={}, ...children) {
  const node = document.createElement(tag);
  for (const [key,value] of Object.entries(attributes)) {
    if (key === 'className') node.className = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(),value);
    else if (value !== undefined && value !== false) node.setAttribute(key,value === true ? '' : String(value));
  }
  children.flat().filter(child=>child !== null && child !== undefined).forEach(child=>node.append(child instanceof Node ? child : document.createTextNode(String(child))));
  return node;
}
export const money = minor => new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',minimumFractionDigits:minor % 100 === 0 ? 0 : 2,maximumFractionDigits:2}).format(minor/100);
export function productPriceText(product) {
  const prices=product.skus.filter(validateSku).map(sku=>sku.price_minor);
  return prices.length ? money(Math.min(...prices)) : 'Price after review';
}
export const button = (label,onClick,attributes={})=>el('button',{type:'button',onClick,...attributes},label);
export const art = (product,className='')=>product.image_url === null ? el('div',{className:`empty-state ${className}`},'Image unavailable') : el('img',{src:product.image_url || `./assets/${product.image}`,alt:product.image_url ? product.name : `Illustration of ${product.name}; synthetic sample`,className,loading:'lazy',width:600,height:760});
export function productCard(product,onOpen) {
  const unavailable = product.skus.every(s=>s.availability!=='AVAILABLE'||!s.active);
  const state = product.readiness!=='reviewed' ? 'Stock review' : unavailable ? product.skus.some(s=>s.availability==='REVIEW_REQUIRED') ? 'Stock review' : product.skus.every(s=>s.availability==='SOLD_OUT') ? 'Sold out' : 'Unavailable' : product.tag;
  const action=(content,attributes={})=>product.page_url
    ? el('a',{href:product.page_url,...attributes,onClick:event=>{if(!event.metaKey&&!event.ctrlKey&&!event.shiftKey&&!event.altKey){event.preventDefault();onOpen(product);}}},content)
    : button(content,()=>onOpen(product),attributes);
  return el('article',{className:'product-card'},
    action([art(product),el('span',{className:'image-action'},'Choose your size ↗')],{className:'product-image','aria-label':`View ${product.name}`}),
    el('div',{className:'product-meta'},el('span',{className:'eyebrow'},state),el('div',{className:'product-title'},el('h3',{},action(product.name,{className:'text-button'})),el('span',{},productPriceText(product)))));
}
export function dialogShell(title,id) {
  const body=el('div',{className:'dialog-body'});
  const dialog=el('dialog',{'aria-labelledby':`${id}-title`,className:id},el('div',{className:'dialog-header'},el('h2',{id:`${id}-title`},title),button('Close ×',()=>dialog.close(),{className:'text-button'})),body);
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom) dialog.close();}});
  document.body.append(dialog);
  return {dialog,body};
}
