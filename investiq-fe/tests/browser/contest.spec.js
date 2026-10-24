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
  await guest.getByRole('link',{name:'View contest',exact:true}).click();
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
  await expect(page.getByText('No contests match. Check another filter or come back for the next public contest.',{exact:true})).toBeVisible();
  await page.route('**/api/v1/contests?**',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Contest service unavailable'}})}));
  await page.getByRole('button',{name:'Refresh contests',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Contest service unavailable');
  await expect(page.getByText('Nifty Sprint Weekly',{exact:true})).toHaveCount(0);
});

test('contest cards show distinct IST dates, deadlines and expandable result timing',async({browser,request})=>{
  const context=await browser.newContext({viewport:{width:1440,height:1000},timezoneId:'America/Los_Angeles'});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try {
    const template=await (await request.get('http://127.0.0.1:8081/api/v1/contest-template')).json();
    const base={...template,visibility:'public',level:'all',organizer:'platform',joined:false,is_owner:false,can_manage:false,member_count:24,capacity:100,rule_version:1,entry_opens_at:'2026-10-18T20:00:00Z',entry_closes_at:'2026-10-19T03:40:00Z',starts_at:'2026-10-19T03:45:00Z',ends_at:'2026-10-23T10:00:00Z',first_results_available_at:'2026-10-19T12:30:00Z'};
    const items=[{...base,id:randomUUID(),name:'InvestIQ weekly challenge',status:'open',description:'Build your strategy and follow your portfolio through the week.'},{...base,id:randomUUID(),name:'Next week’s learning league',status:'scheduled',organizer:'user',entry_opens_at:'2026-10-23T12:30:00Z',entry_closes_at:'2026-10-26T03:40:00Z',starts_at:'2026-10-26T03:45:00Z',ends_at:'2026-10-30T10:00:00Z',first_results_available_at:null}];
    await page.route('**/api/v1/contests?*',route=>route.fulfill({json:{items,next_cursor:null}}));
    await page.goto('/#/contests');
    const card=page.locator('.contest-scan-card').filter({has:page.getByRole('heading',{name:items[0].name,exact:true})});
    await expect(card.locator('.contest-state')).toHaveText('Entries open');
    const dates=card.locator('.contest-card-dates');
    await expect(dates).toContainText('Starts');
    await expect(dates).toContainText('Ends');
    await expect(dates.locator('time').first()).toContainText('19 Oct 2026');
    await expect(dates.locator('time').first()).toContainText('9:15 am');
    await expect(dates.locator('time').last()).toContainText('23 Oct 2026');
    await expect(dates.locator('time').last()).toContainText('3:30 pm');
    await expect(card.locator('.contest-entry-deadline')).toContainText('Entry closes');
    await expect(card.locator('.contest-entry-deadline')).toContainText('9:10 am');
    await expect(card.getByText('First results after',{exact:true})).toBeHidden();
    await card.getByText('Schedule details',{exact:true}).click();
    await expect(card.locator('.contest-schedule-details')).toContainText('19 Oct 2026 · 1:30 am');
    await expect(card.locator('.contest-schedule-details')).toContainText('19 Oct 2026 · 6:00 pm');
    await card.getByText('Schedule details',{exact:true}).click();
    const upcoming=page.locator('.contest-scan-card').last();
    await expect(upcoming.locator('.contest-state')).toHaveText('Upcoming');
    await expect(upcoming.locator('.contest-entry-deadline')).toContainText('Entry opens');
    await upcoming.getByText('Schedule details',{exact:true}).click();
    await expect(upcoming.locator('.contest-schedule-details')).toContainText('To be announced');
    await upcoming.getByText('Schedule details',{exact:true}).click();
    await page.screenshot({path:'/tmp/investiq-contest-dates-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await card.scrollIntoViewIfNeeded();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await card.screenshot({path:'/tmp/investiq-contest-dates-mobile.png'});
    for(const [status,label] of [['running','Live'],['completed','Completed'],['cancelled','Cancelled']]) {
      items[0].status=status;
      await page.getByRole('button',{name:'Refresh contests',exact:true}).click();
      await expect(card.locator('.contest-state')).toHaveText(label);
      await expect(card.locator('.contest-entry-deadline')).toContainText(status==='cancelled'?'Entry cancelled':'Entry closed');
      await expect(card.locator('.contest-card-dates')).toContainText(status==='cancelled'?'Planned end':'Ends');
    }
    expect(errors).toEqual([]);
  } finally {await context.close();}
});
