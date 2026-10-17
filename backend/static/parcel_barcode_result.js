import {extractTracking} from './parcel_label_courier.js';
// Carrier formats overlap. Never guess a carrier from the digit count alone.
export function barcodeResult(values){
 const candidates=[...new Set(values.map(v=>String(v).replace(/\s/g,'').toUpperCase()).filter(v=>/^1Z[A-Z0-9]{16}$|^\d{8,22}$/.test(v)))];
 if(candidates.length!==1)return null;
 const found=extractTracking('',candidates);
 return {awb:candidates[0],courier:found.courier||''};
}
