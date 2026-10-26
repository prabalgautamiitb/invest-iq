import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

const password='contest browser password 93';
const me=page=>page.evaluate(async()=> (await (await fetch('/api/v1/me')).json()));
async function login(page,email){
  await page.getByLabel('Email address',{exact:true}).fill(email);
  await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Open admin workspace',exact:false}).click();
}

test('admin and learner stay signed in side by side in the same browser context',async({page,context,browser,request})=>{
  const learnerEmail=`portal-learner-${randomUUID()}@example.com`;
  await verifiedAccount(page,request,learnerEmail);
  const learner=await me(page);
  await page.goto('/#/academy');

  // Provision an existing admin without replacing the learner's browser session.
  const setup=await browser.newContext();
  const adminEmail=`portal-admin-${randomUUID()}@example.com`;
  let adminId;
  try{
    const setupPage=await setup.newPage();
    await verifiedAccount(setupPage,request,adminEmail);
    adminId=(await me(setupPage)).id;
    const promotion=await request.post('http://127.0.0.1:8081/__browser__/admin/'+adminId,{headers:{'X-Investiq-Browser-Test':'local-disposable-only'}});
    expect(promotion.ok()).toBeTruthy();
  }finally{await setup.close();}

  const admin=await context.newPage();
  await admin.goto('http://admin.localhost:5174/');
  await expect(admin).toHaveURL('http://admin.localhost:5174/#/login');
  await expect(admin.getByRole('heading',{name:'Admin sign in',exact:true})).toBeVisible();
  await expect(admin.getByRole('link',{name:'Create an account',exact:true})).toHaveCount(0);
  await admin.goto('http://admin.localhost:5174/#/signup');
  await expect(admin).toHaveURL('http://admin.localhost:5174/#/login');
  await login(admin,learnerEmail);
  await expect(admin.locator('[data-form-status]')).toContainText('Administrator access is required');
  expect((await me(page)).id).toBe(learner.id);

  await login(admin,adminEmail);
  await expect(admin).toHaveURL('http://admin.localhost:5174/#/contests/admin');
  await expect(admin.getByRole('navigation',{name:'Admin navigation',exact:true})).toBeVisible();
  expect((await me(admin)).id).toBe(adminId);
  await page.reload();
  await expect(page.getByRole('heading',{name:'Your Academy',exact:true})).toBeVisible();
  expect((await me(page)).id).toBe(learner.id);
  const cookies=(await context.cookies()).filter(c=>c.name==='investiq_dev_session');
  expect(cookies.map(c=>c.domain).sort()).toEqual(['127.0.0.1','admin.localhost']);
  expect(new Set(cookies.map(c=>c.value)).size).toBe(2);

  await admin.getByRole('button',{name:'Sign out',exact:true}).first().click();
  await expect(admin.getByRole('heading',{name:'Admin sign in',exact:true})).toBeVisible();
  expect((await me(page)).id).toBe(learner.id);
  await admin.goto('http://admin.localhost:5174/#/admin/courses');
  await expect(admin).toHaveURL('http://admin.localhost:5174/#/login');
});
