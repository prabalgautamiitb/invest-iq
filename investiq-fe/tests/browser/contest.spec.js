import { randomUUID } from 'node:crypto';
import { test, expect } from '@playwright/test';

async function verifiedAccount(page, request, email) {
  await page.goto('/#/signup');
  await page.getByLabel('Full name').fill('Contest Learner');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password', {exact:true}).fill('contest browser password 93');
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Create account',exact:true}).click();
  await expect(page).toHaveURL(/#\/onboarding$/);
  let id;
  await expect.poll(async () => {
    const data = await (await request.get('http://127.0.0.1:8025/api/v1/search',{params:{query:`to:${email}`}})).json();
    id = data.messages?.find(m => m.Subject.includes('Verify'))?.ID;
    return Boolean(id);
  }).toBe(true);
  const mail = await (await request.get(`http://127.0.0.1:8025/api/v1/message/${id}`)).json();
  await page.goto(mail.Text.match(/http:\/\/127\.0\.0\.1:5174\/[^\s]+/)[0]);
  await page.getByRole('button',{name:'Verify email',exact:true}).click();
  await expect.poll(() => page.evaluate(async () => (await (await fetch('/api/v1/me')).json()).email_verified)).toBe(true);
}

test('create, revise, publish, invite, accept and persist real contest membership', async ({page, request, browser}) => {
  const errors = [];
  page.on('pageerror',e=>errors.push(e.message));
  const guestContext = await browser.newContext();
  const guest = await guestContext.newPage();
  guest.on('pageerror',e=>errors.push(e.message));
  const guestEmail = `contest-guest-${randomUUID()}@example.com`;
  await verifiedAccount(page,request,`contest-host-${randomUUID()}@example.com`);
  await verifiedAccount(guest,request,guestEmail);
  await page.goto('/#/contests/create');
  await page.getByLabel('Contest name',{exact:true}).fill('Browser private league');
  await page.getByRole('button',{name:'Save contest draft',exact:true}).click();
  await expect(page).toHaveURL(/#\/contests\/[0-9a-f-]{36}$/);
  const path = page.url();
  await expect(page.getByRole('heading',{name:'Browser private league',exact:true})).toBeVisible();
  await guest.goto(path);
  await expect(guest.getByRole('alert')).toContainText('Contest not found');
  await page.getByLabel('Contest name',{exact:true}).fill('Revised browser league');
  await page.getByRole('button',{name:'Save new rule version',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Revised browser league',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Publish and freeze rules',exact:true}).click();
  await expect(page.locator('#server-contest-form')).toHaveCount(0);
  await expect(page.getByText('Rule version 2',{exact:true})).toBeVisible();
  await page.getByLabel('Invite email',{exact:true}).fill(guestEmail);
  await page.getByRole('button',{name:'Create invitation',exact:true}).click();
  await expect(page.locator('article').filter({hasText:guestEmail})).toContainText('pending');
  await guest.goto('/#/my-contests');
  await guest.getByRole('button',{name:'Accept invitation',exact:true}).click();
  await expect(guest.getByText('Joined',{exact:true})).toBeVisible();
  await guest.reload();
  await expect(guest.getByText('Joined',{exact:true})).toBeVisible();
  await guest.getByRole('link',{name:'View contest →',exact:true}).click();
  await expect(guest.getByText('You joined this contest.',{exact:true})).toBeVisible();
  await expect(guest.getByText('Current rank',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Join contest',exact:true}).click();
  await expect(page).toHaveURL(/#\/my-contests$/);
  await expect(page.getByText('Joined',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Hosted contests',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Revised browser league',exact:true})).toBeVisible();
  await expect(page.getByText('2 / 100',{exact:true})).toBeVisible();
  expect(errors).toEqual([]);
  await guestContext.close();
});

test('discovery uses server filters and reports API failures without demo fallback', async ({page}) => {
  await page.goto('/#/contests');
  await expect(page.getByRole('heading',{name:'Contest explorer',exact:true})).toBeVisible();
  await page.getByLabel('Search contests',{exact:true}).fill('nonexistent phase four league');
  await page.getByLabel('Search contests',{exact:true}).press('Tab');
  await expect(page.getByText('No contests match. Create the first learning league.',{exact:true})).toBeVisible();
  await page.route('**/api/v1/contests?**',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Contest service unavailable'}})}));
  await page.getByRole('button',{name:'Refresh contests',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Contest service unavailable');
  await expect(page.getByText('Nifty Sprint Weekly',{exact:true})).toHaveCount(0);
});
