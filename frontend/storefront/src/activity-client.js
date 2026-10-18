// Optional observed activity only. Shopping must never depend on this module.
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTEXT_MS=30*60*1000;
const exact=(x,keys)=>x&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).length===keys.length&&keys.every(k=>Object.hasOwn(x,k));

export function createActivityClient({slug,storage,fetchImpl=globalThis.fetch,
  document=globalThis.document,navigator=globalThis.navigator,now=()=>Date.now(),
  keyFactory=()=>crypto.randomUUID(),origin=globalThis.location?.origin}={}){
  let current=null,capability=null,pending=null,disabled=false,disposed=false;
  const key=`munimjee.activity.v1:${origin}:${slug}`;
  if(typeof slug!=='string'||! /^[a-z0-9][a-z0-9-]{0,62}$/.test(slug))disabled=true;
  const allowed=()=>!disabled&&!disposed&&document?.visibilityState==='visible'&&
    navigator?.globalPrivacyControl!==true&&!['1','yes'].includes(String(navigator?.doNotTrack||'').toLowerCase());
  function read(){
    try{
      const raw=storage.getItem(key);
      if(raw===null)return;
      if(raw.length>1024)throw Error();
      const row=JSON.parse(raw);
      if(!exact(row,['version','slug','origin','key','context_id','expires_at'])||row.version!==1||row.slug!==slug||row.origin!==origin||!UUID.test(row.key)||
        !(row.context_id===null||UUID.test(row.context_id))||!(row.expires_at===null||Number.isSafeInteger(row.expires_at)&&row.expires_at>0&&row.expires_at<=now()+CONTEXT_MS+60000)||
        (row.context_id===null)!==(row.expires_at===null))throw Error();
      current=row;
    }catch{disabled=true;current=null;}
  }
  function persist(row){
    try{const raw=JSON.stringify(row);storage.setItem(key,raw);if(storage.getItem(key)!==raw)throw Error();current=row;return true;}
    catch{disabled=true;capability=null;return false;}
  }
  read();
  async function post(path,body,token=null){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
    try{
      const response=await fetchImpl(`/api/v1/storefronts/${encodeURIComponent(slug)}/activity/${path}`,{
        method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',
        headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})},
        body:JSON.stringify(body),signal:controller.signal});
      if(!response.ok)throw Error();
      const raw=await response.text();if(raw.length>8192)throw Error();return JSON.parse(raw);
    }finally{clearTimeout(timer);}
  }
  async function start(){
    if(!allowed())return null;
    if(capability&&current?.expires_at>now())return current.context_id;
    if(pending)return pending;
    pending=(async()=>{
      try{
        if(!current||current.expires_at!==null&&current.expires_at<=now()){
          const command=keyFactory();if(!UUID.test(command))return null;
          if(!persist({version:1,slug,origin,key:command,context_id:null,expires_at:null}))return null;
        }
        const sent=current.key,result=await post('contexts',{idempotency_key:current.key});
        if(!allowed()||current.key!==sent)return null;
        if(!exact(result,['contract_version','state','context_id','expires_at','capability'])||result.contract_version!=='activity-context.v1'||
          !['ready','disabled','excluded','expired','capped'].includes(result.state))return null;
        if(result.state!=='ready'){
          if(result.context_id!==null||result.expires_at!==null||result.capability!==null)return null;
          capability=null;
          // A refused/expired context is never silently retried with a new key
          // inside the same operation; later visible browsing may start anew.
          if(result.state==='expired'){
            try{storage.removeItem(key);current=null;}
            catch{disabled=true;}
          }
          return null;
        }
        const expires=Date.parse(result.expires_at);
        if(!UUID.test(result.context_id)||typeof result.capability!=='string'||result.capability.length<10||result.capability.length>4096||
          !Number.isSafeInteger(expires)||expires<=now()||expires>now()+CONTEXT_MS+60000||
          current.context_id!==null&&current.context_id!==result.context_id)return null;
        if(!persist({...current,context_id:result.context_id,expires_at:expires}))return null;
        capability=result.capability;return current.context_id;
      }catch{return null;}finally{pending=null;}
    })();
    return pending;
  }
  async function event(event_kind,product_id=null){
    if(!allowed()||event_kind==='product_view'&&!UUID.test(product_id))return false;
    const id=await start();if(!id||!allowed())return false;
    try{
      const result=await post('events',{event_kind,product_id},capability);
      return exact(result,['contract_version','state','replayed'])&&result.contract_version==='activity-event.v1'&&
        result.state==='accepted'&&typeof result.replayed==='boolean';
    }catch{return false;}
  }
  return {
    start,
    productView:product_id=>event('product_view',product_id),
    checkoutOpened:()=>event('checkout_opened'),
    // Freeze this nullable ID into the existing financial intent BEFORE POST.
    // Do not replace an old CheckoutAttempt payload with a renewed context.
    contextForCheckout:()=>allowed()&&capability&&current?.expires_at>now()?current.context_id:null,
    // Ephemeral proof may be absent/expired on replay; checkout remains usable.
    proofFor:context_id=>allowed()&&capability&&current?.context_id===context_id&&current.expires_at>now()?capability:null,
    dispose(){disposed=true;capability=null;current=null;},
  };
}
