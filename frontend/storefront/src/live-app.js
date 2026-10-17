import {el,button,money,art,productCard,productPriceText,dialogShell} from './components.js';
import {addItem,setQuantity,findSku,limitFor,previewSubtotal} from './commerce.js';
import {themes} from './theme-config.js';
import {CheckoutAttempt} from './checkout-attempt.js';
import {createPaymentHandoff} from './payment-handoff.js';

// Internal SSR page projection only: no catalogue.v1 fixture or query enables this.
export function viewProduct(dto,categories,base=''){
  return {id:dto.product_id,page_url:base?`${base}/products/${dto.product_id}`:null,name:dto.name,description:dto.description,category:categories.find(c=>c.category_id===dto.category_id)?.name||'Collection',category_id:dto.category_id,image_url:dto.photo_urls?.[0]||null,readiness:'reviewed',tag:'The collection',skus:dto.skus.map(sku=>({id:sku.sku_id,label:Object.values(sku.options).join(' / ')||'Default',price_minor:sku.price_minor,currency:sku.currency,active:sku.active,available_units:sku.stock_available,availability:sku.stock_available===0?'SOLD_OUT':'AVAILABLE'}))};
}
export function mountLiveStorefront({root,data,api,storage}){
  if(data.contract_version!=='storefront.page.v1'||data.capabilities?.public_catalogue!==true||!Object.hasOwn(themes,data.store.theme))throw new Error('Unsupported public storefront.');
  const store=data.store,theme=themes[store.theme],base=`/stores/${encodeURIComponent(store.slug)}`;
  let products=data.products.map(dto=>viewProduct(dto,data.categories,base)),cart=[],selectedCategory=data.selected_category_id,search='',customerDraft=null;
  const attempt=new CheckoutAttempt({slug:store.slug,storage});
  const payment=createPaymentHandoff({slug:store.slug,storage});
  let paymentActive=false,paymentNotice='',confirmationEpoch=0;
  if(attempt.current?.payload?.items&&!['confirmed','rejected'].includes(attempt.current.state))cart=attempt.current.payload.items.map(item=>({sku_id:item.sku_id,quantity:item.quantity}));
  const detail=dialogShell('A closer look','live-product-dialog'),bag=dialogShell('Your bag','live-bag-dialog'),checkout=dialogShell('Checkout','live-checkout-dialog');
  const live=el('p',{className:'sr-only','aria-live':'polite'});let bagButton;
  const alert=el('p',{className:'live-error',role:'alert'});
  const checkoutReady=Boolean(api&&data.capabilities.sku_checkout===true&&store.payment_methods?.length);
  function subtotal(){try{return money(previewSubtotal(cart,products));}catch{return 'Needs review';}}
  function syncBag(){bagButton.textContent=`Bag (${cart.reduce((n,line)=>n+line.quantity,0)})`;}
  function openProduct(product){
    let selected=null;const status=el('p',{'aria-live':'polite',className:'stock-status'},'Choose an option.');
    const qty=el('input',{type:'number',id:'live-quantity',min:1,max:1,value:1,disabled:true});
    const add=button('Choose an option',()=>{if(attempt.locked){status.textContent='Your previous checkout attempt needs checking before the bag can change.';return;}const result=addItem(cart,products,selected?.id,Number(qty.value));if(!result.ok){status.textContent=result.error.replaceAll('sample stock','available stock');return;}cart=result.cart;syncBag();detail.dialog.close();openBag();},{className:'primary-button',disabled:true});
    const choices=product.skus.map(sku=>el('label',{className:'sku-option'},el('input',{type:'radio',name:'live-sku',value:sku.id,onChange:()=>{selected=sku;status.textContent=!sku.active?'Unavailable':sku.available_units===0?'Sold out':sku.available_units===null?'Availability checked when the order is placed.':`${sku.available_units} available`;qty.max=limitFor(sku);qty.disabled=!limitFor(sku)||attempt.locked;add.disabled=qty.disabled;add.textContent=limitFor(sku)?`Add to bag · ${money(sku.price_minor)}`:'Unavailable';}}),el('span',{},sku.label),el('small',{},!sku.active?'Unavailable':sku.available_units===0?'Sold out':'Select')));
    detail.body.replaceChildren(el('div',{className:'product-detail'},art(product),el('div',{className:'product-info'},el('span',{className:'eyebrow'},product.category),el('h3',{},product.name),el('p',{className:'detail-price'},productPriceText(product)),el('p',{},product.description),el('fieldset',{},el('legend',{},'Size / colour'),choices),status,el('label',{for:'live-quantity',className:'quantity-label'},'Quantity',qty),add,el('a',{href:`${base}/products/${product.id}`,className:'product-page-link'},'Open product page'))));detail.dialog.showModal();
  }
  function updateLine(id,qty){if(attempt.locked){alert.textContent='Your checkout attempt must be checked before changing the bag.';return;}const result=setQuantity(cart,products,id,qty);if(!result.ok){alert.textContent=result.error;return;}cart=result.cart;syncBag();renderBag();}
  function renderBag(){
    const oldFocus=document.activeElement?.dataset?.focusKey;
    const lines=cart.map(line=>{const match=findSku(products,line.sku_id);if(!match)return el('article',{className:'cart-line'},el('p',{},'An item is no longer available.'),button('Remove unavailable item',()=>updateLine(line.sku_id,0),{disabled:attempt.locked,className:'text-button'}));const {sku,product}=match;return el('article',{className:'cart-line'},art(product),el('div',{},el('h3',{},product.name),el('p',{},sku.label),el('div',{className:'quantity-controls'},button('−',()=>updateLine(sku.id,line.quantity-1),{disabled:attempt.locked,'aria-label':`Decrease ${product.name}`,'data-focus-key':`minus-${sku.id}`}),el('span',{},line.quantity),button('+',()=>updateLine(sku.id,line.quantity+1),{disabled:attempt.locked||line.quantity>=limitFor(sku),'aria-label':`Increase ${product.name}`,'data-focus-key':`plus-${sku.id}`})),button('Remove',()=>updateLine(sku.id,0),{className:'text-button',disabled:attempt.locked,'aria-label':`Remove ${product.name}`})),el('strong',{},money(sku.price_minor*line.quantity)));});
    bag.body.replaceChildren(alert,...lines,el('div',{className:'subtotal'},el('span',{},'Items subtotal'),el('strong',{},subtotal())),el('p',{className:'quiet'},'Final prices, delivery and availability are confirmed by the server.'),...(cart.length?[button(attempt.locked?'Check previous checkout':'Continue to checkout',openCheckout,{className:'primary-button',disabled:!checkoutReady&&!attempt.current})]:[el('p',{},'Your bag is empty.'),...(attempt.current?.state==='confirmed'?[button('View your order',openCheckout,{className:'secondary-button'})]:[])]),...(!checkoutReady?[el('p',{className:'quiet'},'Checkout is not enabled for this store. Your bag does not place an order.')]:[]));
    if(oldFocus)[...bag.body.querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===oldFocus&&!node.disabled)?.focus();
  }
  function openBag(){renderBag();bag.dialog.showModal();}
  bag.dialog.addEventListener('close',()=>{if(!document.querySelector('dialog[open]'))bagButton?.focus();});
  function savePaymentState(order,state){
    confirmationEpoch++;
    const updated={...order,paymentStatus:state.payment_status,fulfillmentStatus:state.fulfillment_status};
    if(attempt.current?.state==='confirmed'&&attempt.current.confirmation.orderId===order.orderId){attempt.current.confirmation=updated;try{attempt.persist();}catch{}}
    showConfirmation(updated);
  }
  async function openPayment(order){
    if(paymentActive)return;
    confirmationEpoch++;paymentActive=true;paymentNotice='Checking payment for this order…';showConfirmation(order);
    try{await payment.open(order,state=>savePaymentState(order,state));paymentNotice='Payment status checked with the server.';}
    catch(error){paymentNotice=error.message;}
    finally{paymentActive=false;showConfirmation(attempt.current?.confirmation||order);}
  }
  function showConfirmation(order){
    const statusMessage=el('p',{className:'payment-status-message',role:'status'},paymentNotice);
    const statusButton=api?.readOrder&&order.accessToken?button('Check order status',async()=>{const epoch=++confirmationEpoch;statusButton.disabled=true;statusMessage.textContent='Checking the saved order…';try{const updated=await api.readOrder(order);if(epoch!==confirmationEpoch)return;attempt.current.confirmation=updated;try{attempt.persist();}catch{}showConfirmation(updated);}catch(error){if(epoch===confirmationEpoch){statusMessage.textContent=error.message;statusButton.disabled=false;}}},{className:'secondary-button',disabled:paymentActive}):null;
    checkout.body.replaceChildren(el('div',{className:'preview-notice'},el('span',{className:'eyebrow'},'ORDER RECEIVED'),el('h3',{},'Your order is received.'),el('p',{},`Reference: ${order.orderId}`),el('p',{},`Payment: ${order.paymentStatus==='paid'?'Paid':order.paymentStatus==='collected'?'Collected':order.paymentStatus==='review_required'?'Needs review':order.paymentStatus==='cancelled'?'Cancelled':order.paymentStatus==='expired'?'Expired':'Pending'}`)),el('div',{className:'subtotal'},el('span',{},'Server-confirmed total'),el('strong',{},money(order.totalMinor))),el('p',{className:'quiet'},order.paymentStatus==='pending'?'Your order has been received. This does not mean payment is complete.':'Payment status is provided by the server.'),...(order.paymentMethod==='razorpay'&&order.accessToken&&order.paymentStatus==='pending'&&order.fulfillmentStatus==='pending'?[button(paymentActive?'Checking payment…':'Continue payment',()=>openPayment(order),{className:'primary-button',disabled:paymentActive})]:[]),...(order.paymentUrl?[el('a',{href:order.paymentUrl,className:'primary-button',rel:'noreferrer'},'Continue to payment')]:[]),...(statusButton?[statusButton,el('a',{href:`${base}/orders/${order.orderId}`,className:'product-page-link'},'Open order status page')]:[]),statusMessage,button('Close',()=>checkout.dialog.close(),{className:'secondary-button'}));
    cart=[];customerDraft=null;syncBag();
  }
  function openCheckout(){
    if(!api||(!checkoutReady&&!attempt.current))return;
    bag.dialog.close();
    if(attempt.current?.state==='confirmed'){showConfirmation(attempt.current.confirmation);checkout.dialog.showModal();return;}
    const saved=attempt.current?.payload?.customer?attempt.current.payload:customerDraft;
    const fields={};
    const field=(name,label,attributes={})=>{const input=el('input',{name,required:true,...attributes});fields[name]=input;return el('label',{className:'live-field'},label,input);};
    const message=el('p',{className:'live-error',role:'alert'});
    const form=el('form',{className:'checkout-form'},el('h3',{},'Almost yours.'),field('name','Full name',{autocomplete:'name',maxlength:100,minlength:2,value:saved?.customer?.name||''}),field('phone','Indian mobile number',{autocomplete:'tel',type:'tel',inputmode:'tel',maxlength:20,value:saved?.customer?.phone||''}),field('line1','Address',{autocomplete:'address-line1',maxlength:200,minlength:3,value:saved?.address?.line1||''}),el('div',{className:'live-field-row'},field('city','City',{autocomplete:'address-level2',maxlength:100,value:saved?.address?.city||''}),field('state','State',{autocomplete:'address-level1',maxlength:100,value:saved?.address?.state||''})),field('postal_code','PIN code',{autocomplete:'postal-code',inputmode:'numeric',pattern:'[1-9][0-9]{5}',maxlength:6,value:saved?.address?.postal_code||''}));
    const method=el('select',{name:'payment_method'},(store.payment_methods||[]).map(value=>el('option',{value,selected:value===saved?.payment_method},value==='cod'?'Pay on delivery':'Online payment')));
    form.append(el('label',{className:'live-field'},'Payment method',method),el('p',{className:'quiet'},store.payment_methods.includes('razorpay')?'Online payment opens after the server confirms this order and total. An order or payment window does not mean payment is complete.':'Online payment is not available here. The server checks totals, availability and delivery support before accepting a pay-on-delivery order.'),message);
    const submit=el('button',{type:'submit',className:'primary-button'},attempt.locked?'Check this attempt again':'Place order');form.append(submit);submit.disabled=attempt.storageUnavailable||attempt.current?.state==='expired';
    if(attempt.current?.state==='rejected')form.append(button('Review your bag',()=>{attempt.clearRejected();checkout.dialog.close();openBag();},{className:'secondary-button'}));
    if(attempt.locked){message.textContent=attempt.current?.state==='expired'?'The saved attempt has expired. Contact the boutique to check its result; a new attempt is blocked.':attempt.storageUnavailable?'Session storage is unavailable. Checkout is blocked to avoid duplicate orders.':'The previous result is unconfirmed. Retry the same attempt; details and bag stay unchanged.';Object.values(fields).forEach(input=>input.readOnly=true);method.disabled=true;}
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(!form.reportValidity())return;
      const payload=(attempt.current?.state==='uncertain'?attempt.current.payload:null)||{customer:{name:fields.name.value,phone:fields.phone.value,email:null},address:{line1:fields.line1.value,line2:'',city:fields.city.value,state:fields.state.value,postal_code:fields.postal_code.value,country:'IN'},items:cart.map(line=>({...line})),note:'',payment_method:method.value,whatsapp_updates_opt_in:false};
      customerDraft=structuredClone(payload);
      submit.disabled=true;submit.textContent='Checking your order…';message.textContent='';Object.values(fields).forEach(input=>input.readOnly=true);method.disabled=true;
      try{if(payload.payment_method==='razorpay'&&attempt.current?.state!=='uncertain')await payment.prepare();const order=await attempt.submit(api,payload);paymentNotice='';showConfirmation(order);live.textContent='Your order was received by the server.';if(order.paymentMethod==='razorpay')await openPayment(order);}
      catch(error){message.textContent=error.message;submit.disabled=attempt.storageUnavailable||attempt.current?.state==='expired';submit.textContent=!attempt.current?'Place order':attempt.current?.state==='rejected'?'Review details and retry':'Check this attempt again';if(!attempt.current||attempt.current?.state==='rejected'){Object.values(fields).forEach(input=>input.readOnly=false);method.disabled=false;if(attempt.current?.state==='rejected')form.append(button('Review your bag',()=>{attempt.clearRejected();checkout.dialog.close();openBag();},{className:'secondary-button'}));}}
    });
    checkout.body.replaceChildren(form);checkout.dialog.showModal();
  }
  function renderProducts(){const filtered=products.filter(p=>(!selectedCategory||p.category_id===selectedCategory)&&p.name.toLowerCase().includes(search.toLowerCase()));document.getElementById('live-grid').replaceChildren(...filtered.map(product=>productCard(product,openProduct)));document.getElementById('live-count').textContent=`${filtered.length} pieces`;}
  bagButton=button(`Bag (${cart.reduce((sum,line)=>sum+line.quantity,0)})`,openBag,{className:'bag-button'});
  const heroProduct=products[Math.min(theme.feature,products.length-1)];
  const hero=el('section',{className:'hero'},el('div',{className:'hero-copy'},el('span',{className:'eyebrow'},theme.eyebrow),el('h1',{},theme.headline),el('p',{},store.description),el('a',{href:'#collection',className:'primary-button'},theme.cta+' ↗')),heroProduct?el('div',{className:'hero-art'},art(heroProduct,'hero-image')):el('div',{className:'empty-state'},'New pieces are on their way.'));
  const selected=data.selected_product_id?products.find(product=>product.id===data.selected_product_id):null;
  const detailSection=selected?el('section',{className:'brand-story'},el('h1',{},selected.name),el('p',{},selected.description),button('Choose your size',()=>openProduct(selected),{className:'primary-button'})):hero;
  const categories=el('nav',{className:'categories','aria-label':'Categories'},el('a',{href:base},'All pieces'),data.categories.map(category=>el('a',{href:`${base}/categories/${category.category_id}`},category.name)));
  const refresh=api?.readProducts?button('Refresh availability',async()=>{refresh.disabled=true;try{const dto=await api.readProducts();products=dto.products.map(item=>viewProduct(item,data.categories,base));renderProducts();live.textContent='Availability updated.';}catch(error){live.textContent=error.message;}finally{refresh.disabled=false;}},{className:'text-button'}):null;
  root.replaceChildren(el('header',{className:'shop-header'},el('a',{className:'wordmark',href:base},store.name.toUpperCase()+theme.suffix),el('nav',{'aria-label':'Main'},el('a',{href:'#collection'},'The collection'),bagButton)),...(!checkoutReady?[el('aside',{className:'live-capability-notice'},'Browse this collection. Checkout is unavailable here. The store must enable an available payment method.')]:[]),detailSection,el('section',{id:'collection',className:'collection'},el('div',{className:'section-heading'},el('h2',{},theme.collection),refresh),el('div',{className:'collection-controls'},categories,el('label',{className:'search-label'},el('span',{className:'sr-only'},'Search products'),el('input',{type:'search',placeholder:'Search the collection',onInput:event=>{search=event.target.value;renderProducts();}}))),el('p',{id:'live-count',className:'result-count','aria-live':'polite'}),el('div',{id:'live-grid',className:'product-grid'})),el('footer',{},el('div',{className:'policies'},el('details',{},el('summary',{},'Delivery policy'),el('p',{},store.shipping_policy)),el('details',{},el('summary',{},'Returns policy'),el('p',{},store.return_policy)))),live);
  renderProducts();
  if(attempt.locked&&attempt.current){openCheckout();}
  return {attempt};
}
