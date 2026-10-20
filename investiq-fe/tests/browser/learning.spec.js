import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

async function course(page){
  const courses=await page.evaluate(async()=> (await (await fetch('/api/v1/courses')).json()).items);
  return courses.find(c=>c.slug==='simulation-foundations');
}
async function answer(page,choices){
  const groups=page.locator('fieldset');
  for(let i=0;i<choices.length;i++)await groups.nth(i).getByRole('radio').nth(choices[i]).check();
}

test('Academy enrolls, scores and persists real progress without repeated XP',async({page,request,browser})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('investiq-demo-v1',JSON.stringify({completed:['essentials'],courseProgress:{essentials:50}})));
  await verifiedAccount(page,request,`learning-${randomUUID()}@example.com`);
  await page.goto('/#/academy');
  await expect(page.getByRole('heading',{name:'Your Academy',exact:true})).toBeVisible();
  await expect(page.getByText('No attempts yet.',{exact:true})).toHaveCount(0);
  await expect(page.getByText('0 / 3 lessons completed',{exact:true})).toHaveCount(2);
  const c=await course(page),lesson=c.lessons[0];
  await page.goto('/#/academy/'+lesson.id);
  await page.getByRole('button',{name:'Enroll to take this quiz',exact:true}).click();
  await expect(page.getByRole('button',{name:'Submit quiz',exact:true})).toBeDisabled();
  await answer(page,[1,1]);
  await page.getByRole('button',{name:'Submit quiz',exact:true}).click();
  await expect(page.getByText('Keep learning · 0/2 correct · 0 XP awarded',{exact:true})).toBeVisible();
  await answer(page,[0,0]);
  await page.getByRole('button',{name:'Submit quiz',exact:true}).click();
  await expect(page.getByText('Quiz passed · 2/2 correct · 25 XP awarded',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Submit quiz',exact:true}).click();
  await expect(page.getByText('Quiz passed · 2/2 correct · 0 XP awarded',{exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading',{name:lesson.title,exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Your attempt history',exact:true})).toBeVisible();
  expect(await page.evaluate(async()=> (await (await fetch('/api/v1/me/learning')).json()).xp)).toBe(25);
  await page.goto('/#/profile');
  await expect(page.getByText('First lesson completed',{exact:false})).toBeVisible();
  await expect(page.getByText('Level 12',{exact:false})).toHaveCount(0);
  const context=await browser.newContext();const other=await context.newPage();
  await verifiedAccount(other,request,`other-learning-${randomUUID()}@example.com`);
  await other.goto('/#/academy');
  await expect(other.getByText('0 / 3 lessons completed',{exact:true})).toHaveCount(2);
  expect(await other.evaluate(async()=> (await (await fetch('/api/v1/me/learning')).json()).xp)).toBe(0);
  await context.close();
  expect(errors).toEqual([]);
});

test('Academy failures can be retried and guests cannot write progress',async({page})=>{
  await page.route('**/api/v1/courses?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Curriculum unavailable'}})}));
  await page.goto('/#/academy');
  await expect(page.getByRole('alert')).toContainText('Curriculum unavailable');
  await expect(page.getByText('17-day streak',{exact:false})).toHaveCount(0);
  await page.unroute('**/api/v1/courses?*');
  await page.getByRole('button',{name:'Retry Academy',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Simulation foundations',exact:true})).toBeVisible();
  const c=await course(page);
  await page.goto('/#/academy/'+c.lessons[0].id);
  await expect(page.getByRole('link',{name:'Sign in to take the quiz',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Submit quiz',exact:true})).toHaveCount(0);
});
