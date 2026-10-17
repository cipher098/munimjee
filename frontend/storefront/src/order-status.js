import {CheckoutAttempt} from './checkout-attempt.js';
import {createStorefrontApi} from './live-api.js';
import {canonicalContract} from './canonical-contract.js';
import {el,button,money} from './components.js';
const root=document.getElementById('order-status');
try{
 const {slug,orderId}=JSON.parse(document.getElementById('order-context').textContent);
 const attempt=new CheckoutAttempt({slug,storage:sessionStorage});
 const confirmation=attempt.current?.state==='confirmed'?attempt.current.confirmation:null;
 if(!confirmation||confirmation.orderId!==orderId||!confirmation.accessToken)throw new Error('Order access is unavailable in this browser session. Return to the original browser or contact the boutique with your order reference.');
 const api=createStorefrontApi({slug,contract:canonicalContract});
 const message=el('p',{role:'status'});
 const refresh=button('Check order status',async()=>{refresh.disabled=true;message.textContent='Checking your saved order…';try{const order=await api.readOrder(confirmation);root.replaceChildren(el('h1',{},'Your order'),el('p',{},`Reference: ${order.orderId}`),el('p',{},`Payment: ${order.paymentStatus.replaceAll('_',' ')}`),el('p',{},`Order: ${order.fulfillmentStatus}`),el('p',{},`Server-confirmed total: ${money(order.totalMinor)}`),el('p',{},order.paymentStatus==='pending'?'Payment is pending. Receiving an order does not confirm payment.':'This status was returned by the order service.'),refresh,message);message.textContent='Order status checked.';}catch(error){message.textContent=error.message;}finally{refresh.disabled=false;}},{className:'primary-button'});
 root.replaceChildren(el('h1',{},'Your order'),refresh,message);refresh.click();
}catch(error){root.replaceChildren(el('h1',{},'Order status unavailable'),el('p',{role:'alert'},error.message));}
