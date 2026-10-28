import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
import {verifiedAccount} from './helpers.js';

test('monthly subscription starts without checkout, retries safely and persists across profile and settings',async({page,request,browser})=>{
  await page.goto('/#/profile/subscription');
  await expect(page.getByRole('heading',{name:'Free simulation access',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Student access',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Standard access',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Start Student subscription',exact:true})).toHaveCount(0);
  await verifiedAccount(page,request,`student-plan-${randomUUID()}@example.com`);
  await page.goto('/#/profile/subscription');
  await expect(page.getByRole('region',{name:'Student access',exact:true})).toContainText('₹99');
  await expect(page.getByRole('region',{name:'Standard access',exact:true})).toContainText('₹199');
  let interrupted=false;
  await page.route('**/api/v1/me/subscription',async route=>{
    if(interrupted)return route.continue();
    interrupted=true;const result=await route.fetch();expect(result.ok()).toBeTruthy();
    return route.fulfill({status:503,json:{error:{message:'Activation response interrupted. Please retry.'}}});
  });
  await page.getByRole('button',{name:'Start Student subscription',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Activation response interrupted');
  await page.getByRole('button',{name:'Start Student subscription',exact:true}).click();
  const active=page.getByRole('region',{name:'Your subscription',exact:true});
  await expect(active).toContainText('Student access');
  await expect(active).toContainText('No payment collected');
  const first=await page.evaluate(async()=>(await (await fetch('/api/v1/me')).json()).subscription);
  await page.reload();
  await expect(active).toContainText('Student access');
  await expect(page.getByRole('button',{name:'Student subscription active',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Start Standard subscription',exact:true})).toBeDisabled();
  expect(await page.evaluate(async()=>(await (await fetch('/api/v1/me')).json()).subscription)).toEqual(first);
  for(const width of [1440,390,360]){
    await page.setViewportSize({width,height:900});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`/tmp/investiq-subscriptions-${width}.png`,fullPage:true});
  }
  await page.goto('/#/settings');
  await expect(page.locator('.settingsrow').filter({hasText:'Monthly preview'})).toContainText('Student access');
  await page.goto('/#/profile');
  await expect(page.getByRole('link',{name:/Subscription Student access/})).toBeVisible();
  const context=await browser.newContext(),other=await context.newPage();
  await verifiedAccount(other,request,`standard-plan-${randomUUID()}@example.com`);
  await other.goto('/#/profile/subscription');
  await expect(other.getByRole('region',{name:'Your subscription',exact:true})).toHaveCount(0);
  await other.getByRole('button',{name:'Start Standard subscription',exact:true}).click();
  await expect(other.getByRole('region',{name:'Your subscription',exact:true})).toContainText('Standard access');
  await other.reload();
  await expect(other.getByRole('button',{name:'Standard subscription active',exact:true})).toBeDisabled();
  await context.close();
});
