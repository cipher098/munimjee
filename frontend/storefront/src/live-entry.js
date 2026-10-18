import {mountLiveStorefront} from './live-app.js';
import {createStorefrontApi} from './live-api.js';
import {canonicalContract} from './canonical-contract.js';
import {createActivityClient} from './activity-client.js';
const dataNode=document.getElementById('storefront-data');
if(dataNode){
  try{
    const data=JSON.parse(dataNode.textContent);
    const activity=createActivityClient({slug:data.store.slug,storage:sessionStorage});
    const api=createStorefrontApi({slug:data.store.slug,contract:canonicalContract,activityProof:id=>activity.proofFor(id)});
    mountLiveStorefront({root:document.getElementById('live-app'),data,api,storage:sessionStorage,activity});
  }catch{
    const message=document.createElement('p');message.setAttribute('role','alert');message.textContent='The shopping controls are unavailable. You can still browse this collection.';document.getElementById('live-app')?.prepend(message);
  }
}
