import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

const harness={'X-Investiq-Browser-Test':'local-disposable-only'};
async function clock(request,at){const r=await request.post('http://127.0.0.1:8081/__browser__/clock',{headers:harness,data:{at}});expect(r.ok()).toBeTruthy();}

test('admin publishes an InvestIQ contest and another learner joins, submits and follows standings',async({page,request,browser})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await clock(request,'2026-10-14T13:00:00Z');
  let learnerContext;
  try {
    await verifiedAccount(page,request,`platform-admin-${randomUUID()}@example.com`);
    const user=await page.evaluate(async()=> (await (await fetch('/api/v1/me')).json()));
    const promotion=await request.post('http://127.0.0.1:8081/__browser__/admin/'+user.id,{headers:harness});expect(promotion.ok()).toBeTruthy();
    await page.goto('/#/contests');
    await page.reload();
    await page.getByRole('link',{name:'Manage InvestIQ contests',exact:true}).click();
    await page.getByRole('link',{name:'Add InvestIQ contest',exact:true}).click();
    await page.getByLabel('Contest name',{exact:true}).fill('InvestIQ shared public challenge');
    await page.getByLabel('Contest ends (IST)',{exact:true}).fill('2026-10-16T15:30');
    await page.getByRole('button',{name:'Save contest draft',exact:true}).click();
    await expect(page.getByRole('button',{name:'Publish and freeze rules',exact:true})).toBeVisible();
    const id=new URL(page.url()).hash.split('/')[2];
    await page.getByRole('button',{name:'Publish and freeze rules',exact:true}).click();
    await expect(page.getByText('InvestIQ public contest',{exact:true})).toBeVisible();
    await page.goto('/#/leaderboard/'+id);
    await expect(page.locator('.main')).toContainText('Administrators can follow public standings here.');
    await expect(page.getByRole('link',{name:'My performance',exact:true})).toHaveCount(0);
    learnerContext=await browser.newContext();const learner=await learnerContext.newPage();
    await learner.goto('/#/contests');
    await learner.getByRole('button',{name:'InvestIQ',exact:true}).click();
    await expect(learner.getByRole('heading',{name:'InvestIQ shared public challenge',exact:true})).toBeVisible();
    await verifiedAccount(learner,request,`platform-learner-${randomUUID()}@example.com`);
    await learner.goto('/#/contests/'+id);
    await learner.getByRole('button',{name:'Join contest',exact:true}).click();
    await expect(learner).toHaveURL(/#\/my-contests$/);
    await learner.locator('.main').getByRole('link',{name:'Portfolio',exact:true}).click();
    await learner.getByRole('button',{name:'Use starter weights',exact:true}).click();
    await learner.getByRole('button',{name:'Save draft',exact:true}).click();
    await expect(learner.getByText('Draft saved on the server.',{exact:true})).toBeVisible();
    await learner.getByRole('button',{name:'Review saved draft',exact:true}).click();
    await expect(learner.getByRole('heading',{name:'Review server calculation',exact:true})).toBeVisible();
    await learner.getByRole('button',{name:'Confirm contest submission',exact:true}).click();
    await expect(learner.locator('#portfolio-history')).toContainText('Version 1');
    await clock(request,'2026-10-15T13:00:00Z');
    const valued=await request.post('http://127.0.0.1:8081/__browser__/value/'+id,{headers:harness});expect(valued.ok()).toBeTruthy();
    await learner.goto('/#/leaderboard/'+id);
    await expect(learner.locator('tbody tr')).toHaveCount(1);
    await expect(learner.locator('tbody')).toContainText('· you');
    await learner.getByRole('link',{name:'My performance',exact:true}).click();
    await expect(learner.getByRole('heading',{name:'Portfolio metrics',exact:true})).toBeVisible();
    expect(errors).toEqual([]);
  } finally {await learnerContext?.close();await clock(request,'2026-10-18T12:00:00Z');}
});

test('regular learners cannot create or manage platform contests',async({page,request})=>{
  await verifiedAccount(page,request,`platform-denied-${randomUUID()}@example.com`);
  await page.goto('/#/contests');
  await expect(page.getByRole('link',{name:'Create contest →',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Manage InvestIQ contests',exact:true})).toHaveCount(0);
  await page.goto('/#/contests/create-platform');
  await expect(page.locator('.main')).toContainText('Administrator access is required.');
  await page.goto('/#/contests/admin');
  await expect(page.locator('.main')).toContainText('Administrator access is required.');
});
