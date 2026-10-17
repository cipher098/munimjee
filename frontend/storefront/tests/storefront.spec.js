import {test,expect} from '@playwright/test';
for(const theme of ['editorial','catalogue','video']){
 for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
  test(`${theme} ${viewport.width}: browse, variants, capped cart, honest checkout and keyboard close`,async({page},testInfo)=>{
   const errors=[];const writes=[];const external=[];
   page.on('pageerror',error=>errors.push(error.message));
   page.on('request',request=>{if(request.method()!=='GET') writes.push(request.url());if(new URL(request.url()).hostname!=='127.0.0.1') external.push(request.url());});
   await page.setViewportSize(viewport);await page.goto(`/?theme=${theme}`);
   await expect(page.getByText('Synthetic catalogue · no orders or payments')).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   await page.getByRole('button',{name:'View Gulab occasion set',exact:true}).click();
   const product=page.getByRole('dialog',{name:'A closer look'});
   await expect(product.getByRole('button',{name:'Choose a size',exact:true})).toBeDisabled();
   await product.getByRole('radio',{name:/L \/ Rose/}).check();
   await expect(product.getByRole('button',{name:'Sold out',exact:true})).toBeDisabled();
   await product.getByRole('radio',{name:/S \/ Rose/}).focus();await page.keyboard.press('Space');
   await product.getByLabel('Quantity',{exact:true}).fill('2');
   await product.getByRole('button',{name:/Add to bag/}).click();
   const cart=page.getByRole('dialog',{name:'Your bag'});
   await expect(cart.getByRole('button',{name:'Increase Gulab occasion set'})).toBeDisabled();
   await expect(cart.getByText('₹13,780',{exact:true})).toHaveCount(2);
   await cart.getByRole('button',{name:'Review checkout preview →'}).click();
   const checkout=page.getByRole('dialog',{name:'Checkout preview'});
   await expect(checkout.getByText(/No order has been placed/)).toBeVisible();
   await expect(checkout.getByRole('button',{name:'Order placement unavailable'})).toBeDisabled();
   await checkout.getByRole('button',{name:'Return to your bag'}).click();
   await cart.getByRole('button',{name:'Decrease Gulab occasion set'}).click();
   await expect(cart.getByRole('button',{name:'Decrease Gulab occasion set'})).toBeFocused();
   await cart.getByRole('button',{name:'Remove Gulab occasion set'}).click();
   await expect(cart.getByText('A good place to begin.')).toBeVisible();
   await page.keyboard.press('Escape');await expect(cart).not.toBeVisible();
   await expect(page.getByRole('button',{name:'Bag (0)',exact:true})).toBeFocused();
   await page.getByLabel('Search products').fill('linen');await expect(page.locator('.product-card')).toHaveCount(1);
   await page.getByLabel('Search products').fill('zzzz');await expect(page.getByText('A little too specific?')).toBeVisible();
   await page.getByRole('button',{name:'Clear filters'}).click();await expect(page.locator('.product-card')).toHaveCount(6);
   await page.screenshot({path:testInfo.outputPath(`${theme}-${viewport.width===1440?'desktop':'mobile'}.png`),fullPage:true});
   expect(errors).toEqual([]);expect(writes).toEqual([]);expect(external).toEqual([]);
  });
 }
}
test('review, untracked and illustrated video states are explicit; themes share the bag',async({page})=>{
 await page.goto('/?theme=video');
 await page.getByRole('button',{name:'▷ View styling story'}).click();
 const story=page.getByRole('dialog',{name:'In the studio'});
 await expect(story.getByText(/No seller footage is connected/)).toBeVisible();
 await expect(story.locator('video')).toHaveCount(0);
 await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'View Heritage layer',exact:true}).click();
 const product=page.getByRole('dialog',{name:'A closer look'});
 await product.getByRole('radio',{name:/S \/ Clay/}).check();
 await expect(product.getByRole('button',{name:'Stock needs review'})).toBeDisabled();
 await page.keyboard.press('Escape');
 await expect(page.getByRole('button',{name:'View Heritage layer',exact:true})).toBeFocused();
 await page.getByRole('button',{name:'View Everyday cotton kurta',exact:true}).click();
 await product.getByRole('radio',{name:/M \/ Sage/}).check();
 await expect(product.getByText('Stock untracked · confirmed at real checkout')).toBeVisible();
 await product.getByRole('button',{name:/Add to bag/}).click();await page.keyboard.press('Escape');
 await page.getByLabel('Theme',{exact:true}).selectOption('catalogue');
 await expect(page.getByRole('button',{name:'Bag (1)',exact:true})).toBeVisible();
 await page.getByText('Preview settings',{exact:true}).click();
 await page.getByLabel('Boutique name').fill('<img src=x onerror=alert(1)>');
 await expect(page.locator('.shop-header .wordmark')).toHaveText('<IMG SRC=X ONERROR=ALERT(1)> / DAILY');
 await expect(page.locator('.shop-header img')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Publishing unavailable'})).toBeDisabled();
});
test('all themes fit narrow phones and tablets, including open preview settings',async({page})=>{
 for(const theme of ['editorial','catalogue','video'])for(const width of [320,768]){
  await page.setViewportSize({width,height:900});await page.goto(`/?theme=${theme}`);
  await page.getByText('Preview settings',{exact:true}).click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${theme} overflow at ${width}`).toBe(true);
 }
});
