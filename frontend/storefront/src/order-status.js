import {CheckoutAttempt} from './checkout-attempt.js';
import {createStorefrontApi} from './live-api.js';
import {canonicalContract} from './canonical-contract.js';
import {createPaymentHandoff} from './payment-handoff.js';
import {el,button,money} from './components.js';
const root=document.getElementById('order-status');
try{
 const {slug,orderId}=JSON.parse(document.getElementById('order-context').textContent);
 const attempt=new CheckoutAttempt({slug,storage:sessionStorage});
 let confirmation=attempt.current?.state==='confirmed'?attempt.current.confirmation:null;
 if(!confirmation||confirmation.orderId!==orderId||!confirmation.accessToken)throw new Error('Order access is unavailable in this browser session. Return to the original browser or contact the boutique with your order reference.');
 const api=createStorefrontApi({slug,contract:canonicalContract});
 const payment=createPaymentHandoff({slug,storage:sessionStorage});
 let busy=false,notice='';
 function save(order){confirmation=order;attempt.current.confirmation=order;try{attempt.persist();}catch{}}
 async function refresh(){
  if(busy)return;busy=true;notice='Checking your saved order…';render();
  try{save(await api.readOrder(confirmation));notice='Order status checked.';}catch(error){notice=error.message;}
  finally{busy=false;render();}
 }
 async function resume(){
  if(busy)return;busy=true;notice='Checking payment for this order…';render();
  try{
   await payment.open(confirmation,state=>{save({...confirmation,paymentStatus:state.payment_status,fulfillmentStatus:state.fulfillment_status});render();});
   notice='Payment status checked with the server.';
  }catch(error){notice=error.message;}
  finally{busy=false;render();}
 }
 function render(){
  const order=confirmation;
  root.replaceChildren(el('h1',{},'Your order'),el('p',{},`Reference: ${order.orderId}`),
   el('p',{},`Payment: ${order.paymentStatus.replaceAll('_',' ')}`),el('p',{},`Order: ${order.fulfillmentStatus}`),
   el('p',{},`Server-confirmed total: ${money(order.totalMinor)}`),
   el('p',{},order.paymentStatus==='pending'?'Payment is pending. Receiving an order does not confirm payment.':'This status was returned by the order service.'),
   ...(order.paymentMethod==='razorpay'&&order.paymentStatus==='pending'&&order.fulfillmentStatus==='pending'?
    [button(busy?'Checking payment…':'Continue payment',resume,{className:'primary-button',disabled:busy})]:[]),
   button('Check order status',refresh,{className:'secondary-button',disabled:busy}),el('p',{role:'status'},notice));
 }
 render();refresh();
}catch(error){root.replaceChildren(el('h1',{},'Order status unavailable'),el('p',{role:'alert'},error.message));}
