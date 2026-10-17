import {business,products,themes} from './fixtures.js';
import {addItem,setQuantity,findSku,stockText,limitFor,previewSubtotal,checkoutProposal} from './commerce.js';
import {el,button,money,art,productPriceText,productCard,dialogShell} from './components.js';
const state={theme:Object.hasOwn(themes,new URL(location.href).searchParams.get('theme'))?new URL(location.href).searchParams.get('theme'):'editorial',cart:[],category:'All pieces',search:'',brand:business.name};
const root=document.querySelector('#app');
const productModal=dialogShell('A closer look','product-dialog');
const cartModal=dialogShell('Your bag','cart-dialog');
const checkoutModal=dialogShell('Checkout preview','checkout-dialog');
const storyModal=dialogShell('In the studio','story-dialog');
const announcement=el('div',{className:'sr-only','aria-live':'polite','aria-atomic':'true'});
const announce=message=>{announcement.textContent='';requestAnimationFrame(()=>{announcement.textContent=message;});};
let bagButton;
cartModal.dialog.addEventListener('close',()=>{if(!document.querySelector('dialog[open]')) bagButton?.focus();});
function render(){
  const theme=themes[state.theme];
  document.documentElement.dataset.theme=state.theme;
  const select=el('select',{id:'theme-picker',onChange:event=>{state.theme=event.target.value;const url=new URL(location.href);url.searchParams.set('theme',state.theme);history.replaceState(null,'',url);render();document.querySelector('#theme-picker').focus();announce(`${themeName()} theme preview selected.`);}},Object.entries(themes).map(([value,item])=>el('option',{value,selected:value===state.theme},item.name)));
  const settings=el('details',{className:'preview-settings'},el('summary',{},'Preview settings'),el('div',{className:'settings-panel'},el('label',{},'Boutique name',el('input',{value:state.brand,maxlength:50,onInput:event=>{state.brand=event.target.value;document.querySelector('.wordmark').textContent=`${state.brand.toUpperCase()}${themes[state.theme].suffix}`;}})),el('p',{},'Changes the header wordmark only. Sample collection copy remains Tara.'),button('Publishing unavailable',()=>{},{disabled:true}),el('p',{},'Publication needs a reviewed catalogue, connected checkout and release checks.')));
  const toolbar=el('aside',{className:'preview-toolbar','aria-label':'Theme preview controls'},el('div',{className:'preview-state'},el('span',{className:'preview-dot','aria-hidden':true}),el('strong',{},'Storefront preview'),el('span',{},'Synthetic catalogue · no orders or payments')),el('div',{className:'preview-tools'},el('label',{for:'theme-picker'},'Theme'),select,settings));
  bagButton=button(`Bag (${state.cart.reduce((sum,line)=>sum+line.quantity,0)})`,openCart,{className:'bag-button'});
  const header=el('header',{className:'shop-header'},el('a',{href:'#',className:'wordmark','aria-label':'Boutique home'},`${state.brand.toUpperCase()}${theme.suffix}`),el('nav',{'aria-label':'Main'},el('a',{href:'#collection'},'The collection'),el('a',{href:'#our-story'},'Our story'),bagButton));
  const featured=products[theme.feature];
  const heroArt=el('div',{className:'hero-art'},art(featured,'hero-image'),el('div',{className:'art-caption'},el('span',{},state.theme==='video'?'ILLUSTRATED STUDIO STUDY':'ILLUSTRATIVE SAMPLE'),el('span',{},state.theme==='video'?'No seller video connected':'Tara / Sample collection')));
  if(state.theme==='video') heroArt.append(button('▷  View styling story',openStory,{className:'story-play'}));
  const hero=el('section',{className:'hero','aria-labelledby':'hero-heading'},el('div',{className:'hero-copy'},el('span',{className:'eyebrow'},theme.eyebrow),el('h1',{id:'hero-heading'},theme.headline),el('p',{},theme.intro),el('a',{href:'#collection',className:'primary-button'},`${theme.cta} ↗`),el('span',{className:'hero-note'},theme.label)),heroArt,el('div',{className:'hero-side-note'},theme.caption));
  const collection=el('section',{id:'collection',className:'collection','aria-labelledby':'collection-heading'},el('div',{className:'section-heading'},el('div',{},el('span',{className:'eyebrow'},'THE TARA COLLECTION'),el('h2',{id:'collection-heading'},theme.collection)),el('p',{},'Made-up pieces. Real preview interactions.')));
  const search=el('input',{id:'product-search',type:'search',placeholder:'Search the collection',value:state.search,onInput:event=>{state.search=event.target.value;renderProducts();}});
  const categories=el('div',{className:'categories','aria-label':'Filter by category'},['All pieces','Occasionwear','Kurtas','Co-ords','Dresses'].map(category=>button(category,event=>{state.category=category;document.querySelectorAll('.categories button').forEach(node=>node.setAttribute('aria-pressed',node.textContent===category));renderProducts();},{'aria-pressed':state.category===category})));
  collection.append(el('div',{className:'collection-controls'},categories,el('label',{className:'search-label',for:'product-search'},el('span',{className:'sr-only'},'Search products'),search)),el('p',{id:'result-count',className:'result-count','aria-live':'polite'}),el('div',{id:'product-grid',className:'product-grid'}));
  const story=el('section',{id:'our-story',className:'brand-story'},el('span',{className:'eyebrow'},'A MORE CONSIDERED WARDROBE'),el('h2',{},'Less noise.\nMore you.'),el('div',{},el('p',{},business.description),el('p',{},'Tara is a fictional boutique for exploring Munimjee’s storefront themes. Every product image is an illustration, and every price and stock count is a sample.')));
  const footer=el('footer',{},el('div',{className:'footer-top'},el('span',{className:'wordmark'},'TARA'),el('span',{},'Thoughtfully composed.')),el('div',{className:'policies'},el('details',{},el('summary',{},'Delivery policy · sample'),el('p',{},business.shipping_policy)),el('details',{},el('summary',{},'Returns policy · sample'),el('p',{},business.return_policy))),el('p',{className:'footer-note'},'Local preview · Nothing is published. Checkout, payment, delivery and messaging services are not connected.'));
  root.replaceChildren(toolbar,header,hero,collection,story,footer,announcement);
  renderProducts();
}
function themeName(){return themes[state.theme].name;}
function renderProducts(){
  const matching=products.filter(product=>(state.category==='All pieces'||product.category===state.category)&&`${product.name} ${product.category}`.toLowerCase().includes(state.search.trim().toLowerCase()));
  document.querySelector('#result-count').textContent=`${matching.length} ${matching.length===1?'piece':'pieces'} · sample catalogue`;
  document.querySelector('#product-grid').replaceChildren(...(matching.length?matching.map(product=>productCard(product,openProduct)):[el('div',{className:'empty-state'},el('h3',{},'A little too specific?'),el('p',{},'Try another name or category.'),button('Clear filters',()=>{state.search='';state.category='All pieces';render();document.querySelector('#product-search').focus();},{className:'secondary-button'}))]));
}
function openProduct(product){
  let selected=null;
  const status=el('p',{className:'stock-status','aria-live':'polite'},'Choose a size to see sample availability.');
  const quantity=el('input',{type:'number',id:'product-quantity',value:1,min:1,max:1,step:1,inputmode:'numeric',disabled:true});
  const add=button('Choose a size',()=>{
    const result=addItem(state.cart,products,selected?.id,Number(quantity.value));
    if(!result.ok){status.textContent=result.error;return;}
    state.cart=result.cart;updateBag();productModal.dialog.close();openCart();announce(`${product.name} added to bag.`);
  },{className:'primary-button',disabled:true});
  const choices=product.skus.map(sku=>{
    const input=el('input',{type:'radio',name:'sku',value:sku.id,onChange:()=>{selected=sku;status.textContent=stockText(sku);quantity.disabled=limitFor(sku)===0;quantity.max=limitFor(sku);quantity.value=1;add.disabled=limitFor(sku)===0;add.textContent=limitFor(sku)?`Add to bag · ${money(sku.price_minor)}`:sku.availability==='REVIEW_REQUIRED'?'Stock needs review':stockText(sku);}});
    return el('label',{className:'sku-option'},input,el('span',{},`${sku.label}`),el('small',{},sku.availability==='REVIEW_REQUIRED'?'Review needed':sku.availability==='SOLD_OUT'?'Sold out':!sku.active?'Unavailable':sku.available_units===null?'Untracked':'Available'));
  });
  productModal.body.replaceChildren(el('div',{className:'product-detail'},art(product),el('div',{className:'product-info'},el('span',{className:'eyebrow'},product.category),el('h3',{},product.name),el('p',{className:'detail-price'},productPriceText(product)),el('p',{},product.description),el('fieldset',{},el('legend',{},'Size / colour'),choices),status,el('label',{className:'quantity-label',for:'product-quantity'},'Quantity',quantity),add,el('p',{className:'quiet'},'Sample products only. This preview does not reserve inventory.'))));
  productModal.dialog.showModal();
}
function updateBag(){bagButton.textContent=`Bag (${state.cart.reduce((sum,line)=>sum+line.quantity,0)})`;}
function changeQuantity(id,quantity){const result=setQuantity(state.cart,products,id,quantity);if(!result.ok){announce(result.error);return;}state.cart=result.cart;updateBag();renderCart();}
function renderCart(){
  const focusKey=document.activeElement?.dataset?.focusKey;
  const lines=state.cart.map(line=>{const {product,sku}=findSku(products,line.sku_id);return el('article',{className:'cart-line'},art(product),el('div',{},el('h3',{},product.name),el('p',{},`${sku.label}`),el('p',{},money(sku.price_minor)),el('div',{className:'quantity-controls'},button('−',()=>changeQuantity(sku.id,line.quantity-1),{'aria-label':`Decrease ${product.name}`, 'data-focus-key':`decrease-${sku.id}`}),el('span',{'aria-label':`Quantity ${line.quantity}`},line.quantity),button('+',()=>changeQuantity(sku.id,line.quantity+1),{'aria-label':`Increase ${product.name}`,disabled:line.quantity>=limitFor(sku),'data-focus-key':`increase-${sku.id}`})),button('Remove',()=>changeQuantity(sku.id,0),{className:'text-button','aria-label':`Remove ${product.name}`})),el('strong',{},money(sku.price_minor*line.quantity)));});
  cartModal.body.replaceChildren(...(lines.length?[...lines,el('div',{className:'subtotal'},el('span',{},'Sample subtotal'),el('strong',{},money(previewSubtotal(state.cart,products)))),el('p',{className:'quiet'},'Shipping and taxes are not calculated. These sample totals are not a quotation.'),button('Review checkout preview →',openCheckout,{className:'primary-button'}),el('p',{className:'quiet'},'No payment or order will be created.')]:[el('div',{className:'empty-state'},el('h3',{},'A good place to begin.'),el('p',{},'Find a piece you love and choose your size.'),button('Explore the collection',()=>{cartModal.dialog.close();document.querySelector('#collection').scrollIntoView();},{className:'primary-button'}))]));
  if(focusKey){const target=[...cartModal.body.querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===focusKey&&!node.disabled);(target||cartModal.body.querySelector('button'))?.focus();}
}
function openCart(){renderCart();cartModal.dialog.showModal();}
function openCheckout(){
  // Build a local proposal only. It is never submitted or persisted, and contains no prices.
  checkoutProposal(state.cart,products,crypto.randomUUID());
  cartModal.dialog.close();
  checkoutModal.body.replaceChildren(el('div',{className:'preview-notice'},el('span',{className:'eyebrow'},'PREVIEW ONLY'),el('h3',{},'A considered final step.'),el('p',{},'This is where the boutique’s real checkout will appear. No order has been placed and no payment will be taken.')),el('div',{className:'checkout-lines'},state.cart.map(line=>{const {product,sku}=findSku(products,line.sku_id);return el('div',{},el('span',{},`${product.name} · ${sku.size} × ${line.quantity}`),el('strong',{},money(sku.price_minor*line.quantity)));})),el('div',{className:'subtotal'},el('span',{},'Sample subtotal'),el('strong',{},money(previewSubtotal(state.cart,products)))),el('p',{className:'quiet'},'Delivery, taxes, supported destinations and payment options need confirmation before real checkout is enabled.'),el('div',{className:'checkout-unavailable'},button('Order placement unavailable',()=>{},{className:'primary-button',disabled:true})),button('Return to your bag',()=>{checkoutModal.dialog.close();openCart();},{className:'secondary-button'}));
  checkoutModal.dialog.showModal();
}
function openStory(){
  storyModal.body.replaceChildren(el('div',{className:'story-layout'},art(products[1]),el('div',{},el('span',{className:'eyebrow'},'ILLUSTRATED SAMPLE'),el('h3',{},'The Saanjh study'),el('p',{},'A vertical storytelling layout for a boutique’s own product videos. No seller footage is connected in this preview.'),el('p',{},'The garment shown is a synthetic illustration. Video playback will be added with reviewed, seller-authorized media.'),button('Explore this piece',()=>{storyModal.dialog.close();openProduct(products[1]);},{className:'primary-button'}))));
  storyModal.dialog.showModal();
}
render();
