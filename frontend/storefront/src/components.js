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
export const money = minor => new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(minor/100);
export const button = (label,onClick,attributes={})=>el('button',{type:'button',onClick,...attributes},label);
export const art = (product,className='')=>el('img',{src:`./assets/${product.image}`,alt:`Illustration of ${product.name}; synthetic sample`,className,loading:'lazy',width:600,height:760});
export function productCard(product,onOpen) {
  const unavailable = product.skus.every(s=>s.availability!=='AVAILABLE'||!s.active);
  const state = unavailable ? product.skus.some(s=>s.availability==='REVIEW_REQUIRED') ? 'Stock review' : product.skus.every(s=>s.availability==='SOLD_OUT') ? 'Sold out' : 'Unavailable' : product.tag;
  return el('article',{className:'product-card'},
    button([art(product),el('span',{className:'image-action'},'Choose your size ↗')],()=>onOpen(product),{className:'product-image', 'aria-label':`View ${product.name}`}),
    el('div',{className:'product-meta'},el('span',{className:'eyebrow'},state),el('div',{className:'product-title'},el('h3',{},button(product.name,()=>onOpen(product),{className:'text-button'})),el('span',{},money(Math.min(...product.skus.map(s=>s.price_minor)))))));
}
export function dialogShell(title,id) {
  const body=el('div',{className:'dialog-body'});
  const dialog=el('dialog',{'aria-labelledby':`${id}-title`,className:id},el('div',{className:'dialog-header'},el('h2',{id:`${id}-title`},title),button('Close ×',()=>dialog.close(),{className:'text-button'})),body);
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom) dialog.close();}});
  document.body.append(dialog);
  return {dialog,body};
}
