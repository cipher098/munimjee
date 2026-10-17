const patterns={dhl:/^\d{10}$/, ups:/^1Z[A-Z0-9]{16}$/,fedex:/^\d{12}$|^\d{15}$|^\d{20}$|^\d{22}$/,skyking:/^\d{9,12}$/,tirupati:/^\d{12,14}$/,shree_maruti:/^\d{11,14}$/,aakash_ganga:/^\d{9,14}$/};
export function detectCourier(text,candidates=[]){
 const raw=String(text||''),lower=raw.toLowerCase();
 const numbers=candidates.map(x=>String(x).replace(/\s/g,'').toUpperCase());
 const clues=[['dhl',/\bdhl\b|mydhl|dhl\.com/],['skyking',/sky\s*king|skyking\.co/],['shree_maruti',/shree\s*maruti|shreemaruti|smcspl|innofulfill/],['tirupati',/tirupati|shreetirupaticourier/],['aakash_ganga',/a[ak]*ash\s*ganga|akashganga|agcgroup|a\.?g\.?c\.?\s*(?:courier|express)/],['fedex',/fed\s*[e£3]\s*x|fedex\.com/],['ups',/\bups\b|ups\.com/]];
 const brands=clues.filter(([,re])=>re.test(lower)).map(([id])=>id);
 if(brands.length===1)return brands[0];
 // UPS's 1Z prefix is distinctive; numeric AWBs from the other carriers overlap.
 if(!brands.length&&/WAYBILL/i.test(raw)&&/EXPRESS WORLDWIDE|DHL Billing/i.test(raw))return 'dhl';
 if(numbers.some(n=>patterns.ups.test(n))||/\b1Z(?:[\sA-Z0-9]){16,24}\b/i.test(raw))return 'ups';
 // FedEx's tracking marker plus a compatible AWB is stronger than length alone.
 if(!brands.length&&/\bTRK\s*#\s*/i.test(raw)&&numbers.some(n=>patterns.fedex.test(n)))return 'fedex';
 return '';
}
export function chooseAwb(courier,candidates=[]){
 const values=[...new Set(candidates.map(x=>String(x).replace(/\s/g,'').toUpperCase()))];
 if(!courier)return values.find(x=>/^1Z[A-Z0-9]{16}$|^\d{8,22}$/.test(x))||'';
 return values.find(x=>patterns[courier]?.test(x))||'';
}
export function extractTracking(text,barcodes=[]){
 const raw=String(text||'');const candidates=barcodes.map(x=>String(x).replace(/\s/g,''));
 const ups=raw.match(/1[Zz][\sA-Za-z0-9]{16,28}/)?.[0]?.replace(/\s/g,'').slice(0,18);if(ups)candidates.push(ups);
 for(const line of raw.split('\n')){if(/^\s*(?:TO|SHIP\s*TO|RECIPIENT)\b/i.test(line)||/\b(?:PH(?:ONE)?|MOB(?:ILE)?|TEL|FRT\s*A\/C|ACCOUNT|REF(?:ERENCE)?|CAD)\b/i.test(line)||/^\s*\+?\s*91[ -]/.test(line))continue;const marked=line.match(/(?:TRK\s*#|TRACKING\s*#|WAYBILL|C\.?N\.?\s*No\.?|AWB\s*(?:NO|#|:)?)[\s:]*([\d ][\d ]{7,24})/i);if(marked)candidates.push(marked[1].replace(/\s/g,''));else candidates.push(...line.match(/\b\d{9,22}\b/g)||[]);}
 let courier=detectCourier(raw,candidates);if(!courier){const codes=barcodes.map(x=>String(x).replace(/\s/g,''));if(codes.some(x=>/^391\d{9}$/.test(x)))courier='tirupati';else if(codes.some(x=>/^2603\d{10}$/.test(x)))courier='shree_maruti';else if(codes.some(x=>/^446\d{6}$/.test(x)))courier='skyking';else if(codes.some(x=>/^4100\d{6}$/.test(x)))courier='aakash_ganga';else if(codes.some(x=>/^87\d{10}$/.test(x)))courier='fedex';}const matches=[...new Set(candidates.map(x=>x.toUpperCase()).filter(x=>patterns[courier]?.test(x)))];
 const barcode=chooseAwb(courier,barcodes);return {courier,awb:courier?(barcode|| (matches.length===1?matches[0]:'')):''};
}
