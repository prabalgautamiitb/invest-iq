import { randomUUID } from 'node:crypto';
import { test, expect } from '@playwright/test';
import { verifiedAccount } from './helpers.js';

test('wallet-funded entry, insufficient funds and cancellation work across desktop and mobile',async({page,request},testInfo)=>{
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await verifiedAccount(page,request,`wallet-${randomUUID()}@example.com`);
  await page.goto('/#/wallet');
  await expect(page.locator('.wallet-total strong')).toHaveText('₹10,00,000.00');
  await expect(page.locator('[data-wallet-shortcut]')).toHaveAccessibleName('₹10,00,000.00 available virtual funds');
  await expect(page.locator('[data-wallet-shortcut]')).toHaveAttribute('href','#/wallet');
  await page.goto('/#/dashboard');
  await expect(page.getByRole('region',{name:'Overall portfolio value',exact:true})).toContainText('₹10,00,000');
  await expect(page.getByRole('region',{name:'Virtual wallet',exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Waiting for your first valuation',exact:true})).toBeVisible();
  await expect(page.locator('.capital-curve')).toHaveCount(0);
  for(const width of [390,1440]){
    await page.setViewportSize({width,height:1000});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.locator('.capital-overview').screenshot({path:testInfo.outputPath('portfolio-start-'+width+'.png')});
  }
  await expect(page.locator('[data-wallet-shortcut]')).toHaveAccessibleName('₹10,00,000.00 available virtual funds');
  await page.goto('/#/profile/details');
  await page.getByLabel('Display name',{exact:true}).fill('Unsaved wallet refresh check');
  const balanceRefresh=page.waitForResponse(r=>r.url().endsWith('/api/v1/me/wallet')&&r.request().method()==='GET');
  await page.evaluate(()=>document.dispatchEvent(new CustomEvent('investiq:wallet-changed')));
  await balanceRefresh;
  await expect(page.locator('[data-wallet-shortcut]')).toHaveAccessibleName('₹10,00,000.00 available virtual funds');
  await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Unsaved wallet refresh check');
  await page.locator('[data-wallet-shortcut]').click();
  await expect(page).toHaveURL(/#\/wallet$/);
  const ids=await page.evaluate(async()=>{
    const token=(await (await fetch('/api/v1/auth/csrf')).json()).csrf_token;
    const template=await (await fetch('/api/v1/contest-template')).json();
    const ids=[];
    for(const capital of ['600000','700000']){
      const headers={'Content-Type':'application/json','X-CSRF-Token':token,'Idempotency-Key':crypto.randomUUID()};
      const response=await fetch('/api/v1/contests',{method:'POST',headers,body:JSON.stringify({...template,name:'Wallet test '+capital,visibility:'public',rules:{...template.rules,capital}})});
      if(!response.ok)throw new Error(await response.text());
      const c=await response.json();
      const published=await fetch(`/api/v1/contests/${c.id}/transitions`,{method:'POST',headers,body:JSON.stringify({action:'publish'})});
      if(!published.ok)throw new Error(await published.text());
      ids.push(c.id);
    }
    return ids;
  });
  await page.goto('/#/contests/'+ids[0]);
  await expect(page.getByLabel('Contest funding')).toContainText('Available ₹10,00,000');
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:/Reserve .* join/}).click();
  await expect(page).toHaveURL(/#\/my-contests$/);
  await page.goto('/#/wallet');
  await expect(page.locator('.wallet-balance-grid>div').nth(1).locator('strong')).toHaveText('₹4,00,000.00');
  await expect(page.locator('[data-wallet-shortcut]')).toHaveAccessibleName('₹4,00,000.00 available virtual funds');
  await expect(page.locator('.wallet-total strong')).toHaveText('₹10,00,000.00');
  await expect(page.locator('.wallet-position')).toContainText('Wallet test 600000');
  await expect(page.locator('.wallet-transactions')).toContainText('Contest capital reserved');
  await page.reload();
  await expect(page.locator('.wallet-balance-grid>div').nth(1).locator('strong')).toHaveText('₹4,00,000.00');
  for(const width of [320,390,1280]){
    await page.setViewportSize({width,height:900});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    const headerFits=await page.locator('.appbar').evaluate(el=>{
      const brand=el.querySelector('.mobilebrand').getBoundingClientRect();
      const wallet=el.querySelector('[data-wallet-shortcut]').getBoundingClientRect();
      const profile=el.querySelector('[aria-label="Your profile"]').getBoundingClientRect();
      return wallet.right<=profile.x&&wallet.x>=brand.right&&profile.right<=innerWidth;
    });
    expect(headerFits).toBe(true);
    if(width===390||width===1280)await page.screenshot({path:testInfo.outputPath('wallet-'+width+'.png'),fullPage:true});
  }
  await page.goto('/#/contests/'+ids[1]);
  await expect(page.getByRole('button',{name:'Insufficient wallet balance',exact:true})).toBeDisabled();
  await expect(page.getByLabel('Contest funding')).toContainText('Shortfall ₹3,00,000');
  await page.goto('/#/contests/'+ids[0]);
  await expect(page.getByText('This entry is funded by your virtual wallet.',{exact:false})).toBeVisible();
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Cancel contest',exact:true}).click();
  await expect(page.locator('.main')).toContainText('Cancelled');
  await page.goto('/#/wallet');
  await expect(page.locator('.wallet-balance-grid>div').nth(1).locator('strong')).toHaveText('₹10,00,000.00');
  await expect(page.locator('[data-wallet-shortcut]')).toHaveAccessibleName('₹10,00,000.00 available virtual funds');
  await expect(page.locator('.wallet-position')).toHaveCount(0);
  await expect(page.locator('.wallet-transactions')).toContainText('Cancelled contest refund');
  expect(errors).toEqual([]);
});
