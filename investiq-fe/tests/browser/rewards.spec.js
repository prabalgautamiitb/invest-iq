import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

const balance=page=>page.locator('[data-wallet-balance]');
async function avatar(page){return page.evaluate(async()=> (await (await fetch('/api/v1/rewards')).json()).items.find(i=>i.cost===50));}
async function firstLesson(page){
  const lesson=await page.evaluate(async()=> (await (await fetch('/api/v1/courses')).json()).items.find(c=>c.slug==='simulation-foundations').lessons[0]);
  await page.goto('/#/academy/'+lesson.id);
  await page.getByRole('button',{name:'Enroll to take this quiz',exact:true}).click();
  for(let i=0;i<2;i++)await page.locator('fieldset').nth(i).getByRole('radio').nth(0).check();
  await page.getByRole('button',{name:'Submit quiz',exact:true}).click();
  await expect(page.getByText('Quiz passed · 2/2 correct · 25 XP awarded',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Submit quiz',exact:true}).click();
  await expect(page.getByText('Quiz passed · 2/2 correct · 0 XP awarded',{exact:true})).toBeVisible();
}

test('learning coins, sandbox confirmation retries, ledger and private history persist',async({page,request,browser})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('investiq-demo-v1',JSON.stringify({coins:999999,redemptions:[{name:'Demo fake reward'}]})));
  await verifiedAccount(page,request,`rewards-${randomUUID()}@example.com`);
  await page.goto('/#/marketplace');
  await expect(balance(page)).toHaveText('0');
  await expect(page.locator('.main')).not.toContainText('999999');
  await firstLesson(page);
  await page.goto('/#/marketplace');
  await expect(balance(page)).toHaveText('50');
  const item=await avatar(page);
  await page.goto('/#/marketplace/'+item.id);
  await page.getByRole('button',{name:'Review sandbox redemption',exact:true}).click();
  await expect(page.getByRole('region',{name:'Confirm sandbox redemption'})).toContainText('No gift card, shipment, booking or paid feature will be delivered.');
  const keys=[];let interrupted=false;
  await page.route('**/api/v1/me/redemptions',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    keys.push(route.request().headers()['idempotency-key']);
    if(!interrupted){
      interrupted=true;
      const accepted=await route.fetch();expect(accepted.status()).toBe(201);
      return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Redemption response interrupted'}})});
    }
    return route.continue();
  });
  await page.getByRole('button',{name:'Confirm sandbox redemption',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Redemption response interrupted');
  let refreshInterrupted=false;
  await page.route('**/api/v1/me/coins',route=>{
    if(refreshInterrupted)return route.continue();
    refreshInterrupted=true;
    return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Wallet refresh interrupted'}})});
  });
  await page.getByRole('button',{name:'Confirm sandbox redemption',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Sandbox redemption recorded',exact:true})).toBeVisible();
  await expect(page.locator('.main')).toContainText('Current coin balance is unavailable.');
  await page.getByRole('button',{name:'Refresh rewards',exact:true}).click();
  expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1]);
  await expect(balance(page)).toHaveText('0');
  await page.getByRole('link',{name:'Redemption history',exact:true}).click();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody')).toContainText('Sandbox confirmed · no fulfillment');
  await page.reload();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody')).not.toContainText('Demo fake reward');
  await page.getByRole('link',{name:'Coin ledger',exact:true}).click();
  await expect(page.locator('tbody tr')).toHaveCount(2);
  await expect(page.locator('tbody')).toContainText('First lesson completion');
  await expect(page.locator('tbody')).toContainText('-50');
  const context=await browser.newContext();const other=await context.newPage();
  await verifiedAccount(other,request,`other-rewards-${randomUUID()}@example.com`);
  await other.goto('/#/marketplace/history');
  await expect(balance(other)).toHaveText('0');
  await expect(other.locator('tbody')).toContainText('No sandbox redemptions yet.');
  await context.close();
  expect(errors).toEqual([]);
});

test('reward errors show retry states and guests browse without spending',async({page})=>{
  await page.route('**/api/v1/rewards?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Reward catalogue unavailable'}})}));
  await page.goto('/#/marketplace');
  await expect(page.getByRole('alert')).toContainText('Reward catalogue unavailable');
  await expect(page.getByText('Amazon ₹500',{exact:true})).toHaveCount(0);
  await page.unroute('**/api/v1/rewards?*');
  await page.getByRole('button',{name:'Retry rewards',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Practice avatar voucher',exact:true})).toBeVisible();
  const item=await avatar(page);
  await page.goto('/#/marketplace/'+item.id);
  await expect(page.getByRole('link',{name:'Sign in to redeem',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Confirm sandbox redemption',exact:true})).toHaveCount(0);
  await page.goto('/#/marketplace/history');
  await expect(page.getByRole('link',{name:'Sign in to view your history',exact:true})).toBeVisible();
});
