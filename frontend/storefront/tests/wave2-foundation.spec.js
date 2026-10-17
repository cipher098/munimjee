import {test,expect} from '@playwright/test';

test('preview URL flags cannot authorize checkout, payment or publication',async({page})=>{
 const writes=[];const external=[];
 page.on('request',request=>{if(request.method()!=='GET')writes.push(request.url());if(new URL(request.url()).hostname!=='127.0.0.1')external.push(request.url());});
 await page.goto('/?theme=catalogue&checkout_enabled=true&contract_version=catalogue.v2&payment_status=paid&published=true');
 await expect(page.getByText('Synthetic catalogue · no orders or payments')).toBeVisible();
 await page.getByText('Preview settings',{exact:true}).click();
 await expect(page.getByRole('button',{name:'Publishing unavailable'})).toBeDisabled();
 await page.getByRole('button',{name:'View Gulab occasion set',exact:true}).click();
 const detail=page.getByRole('dialog',{name:'A closer look'});
 await detail.getByRole('radio',{name:/S \/ Rose/}).check();
 await detail.getByRole('button',{name:/Add to bag/}).click();
 await page.getByRole('dialog',{name:'Your bag'}).getByRole('button',{name:'Review checkout preview →'}).click();
 const checkout=page.getByRole('dialog',{name:'Checkout preview'});
 await expect(checkout.getByRole('button',{name:'Order placement unavailable'})).toBeDisabled();
 await expect(checkout.getByText(/No order has been placed/)).toBeVisible();
 expect(writes).toEqual([]);expect(external).toEqual([]);
});

test('browser contract rejects unknown stale inactive and malformed SKU proposals',async({page})=>{
 await page.goto('/');
 const result=await page.evaluate(async()=>{
  const rules=await import('/src/commerce.js');
  const {normalizeProduct}=await import('/src/catalogue-adapter.js');
  const dto={contract_version:'catalogue.v1',mode:'preview_foundation',checkout_enabled:false,product_id:'product',name:'Product',description:'Synthetic',readiness:'reviewed',skus:[{sku_id:'sku',options:{Size:'S'},price_minor:129900,currency:'INR',stock_available:2,active:true}]};
  const outcomes={};
  for(const [name,edit] of Object.entries({unknown:()=>{},stale:p=>{p.readiness='stale';},inactive:p=>{p.skus[0].active=false;},badPrice:p=>{p.skus[0].price_minor='129900';},badStock:p=>{p.skus[0].stock_available=-1;}})){
   const changed=structuredClone(dto);edit(changed);const catalogue=[normalizeProduct(changed)];
   try{rules.checkoutProposal([{sku_id:name==='unknown'?'absent':'sku',quantity:1}],catalogue,'synthetic-key');outcomes[name]='accepted';}catch{outcomes[name]='rejected';}
  }
  const catalogue=[normalizeProduct(dto)];
  try{rules.checkoutProposal([{sku_id:'sku',quantity:1},{sku_id:'sku',quantity:1}],catalogue,'synthetic-key');outcomes.duplicates='accepted';}catch{outcomes.duplicates='rejected';}
  const payload=rules.checkoutProposal([{sku_id:'sku',quantity:1,price_minor:1,business_id:'foreign',payment_status:'paid'}],catalogue,'synthetic-key');
  return {outcomes,payload};
 });
 expect(result.outcomes).toEqual({unknown:'rejected',stale:'rejected',inactive:'rejected',badPrice:'rejected',badStock:'rejected',duplicates:'rejected'});
 expect(result.payload).toEqual({idempotency_key:'synthetic-key',items:[{sku_id:'sku',quantity:1}]});
});

test('malicious branding remains literal after theme change and modal roundtrip',async({page})=>{
 const dialogs=[];page.on('dialog',dialog=>{dialogs.push(dialog.message());dialog.dismiss();});
 await page.goto('/?theme=editorial');
 await page.getByText('Preview settings',{exact:true}).click();
 const payload='<svg onload=alert(1)>';
 await page.getByLabel('Boutique name').fill(payload);
 await page.getByLabel('Theme',{exact:true}).selectOption('video');
 await expect(page.locator('.shop-header .wordmark')).toContainText(payload.toUpperCase());
 await expect(page.locator('.shop-header svg,.shop-header script')).toHaveCount(0);
 await page.getByRole('button',{name:'Bag (0)',exact:true}).click();
 await page.keyboard.press('Escape');
 await expect(page.getByRole('button',{name:'Bag (0)',exact:true})).toBeFocused();
 expect(dialogs).toEqual([]);
});
