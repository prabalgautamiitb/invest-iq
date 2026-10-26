import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';
const harness={'X-Investiq-Browser-Test':'local-disposable-only'};
const launcher=page=>page.getByRole('button',{name:'Ask Martin',exact:true});
const editor=page=>page.getByLabel('Your question',{exact:true});
const panel=page=>page.getByRole('dialog',{name:'Ask Martin',exact:true});
const send=page=>page.getByRole('button',{name:'Send question to Martin',exact:true});
async function open(page){await launcher(page).click();await expect(panel(page)).toBeVisible();}
async function work(request){expect((await request.post('http://127.0.0.1:8081/__browser__/martin-work',{headers:harness})).ok()).toBeTruthy();}
async function signIn(page,request){await verifiedAccount(page,request,`martin-${randomUUID()}@example.com`);await page.goto('/#/dashboard');await open(page);await expect(panel(page).locator('#martin-availability')).toContainText('Private chat');}

test('Martin is keyboard accessible, explains sign-in and fits mobile and short screens',async({page})=>{
  await page.goto('/#/dashboard');await launcher(page).focus();await page.keyboard.press('Enter');
  await expect(panel(page)).toHaveAttribute('aria-modal','false');
  await expect(panel(page)).toContainText('Sign in to ask Martin');await expect(send(page)).toBeDisabled();
  await expect(panel(page).getByRole('link',{name:'Sign in',exact:false})).toHaveCount(2);
  await page.keyboard.press('Escape');await expect(panel(page)).toBeHidden();await expect(launcher(page)).toBeFocused();
  await page.setViewportSize({width:390,height:844});await open(page);
  const bounds=await panel(page).boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.y).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(390);
  const circle=await launcher(page).boundingBox(),nav=await page.getByRole('navigation',{name:'Mobile navigation'}).boundingBox();expect(circle.y+circle.height).toBeLessThanOrEqual(nav.y);
  await page.setViewportSize({width:844,height:390});await expect(editor(page)).toBeVisible();
  expect((await panel(page).boundingBox()).y).toBeGreaterThanOrEqual(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('Martin sends idempotently, answers with citations, supports follow-ups and persists private history',async({page,request})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));await signIn(page,request);
  const draft='What is diversification? <img src=x onerror=alert(1)>';
  await editor(page).fill(draft);
  const start=await launcher(page).boundingBox();
  await page.mouse.move(start.x+start.width/2,start.y+start.height/2);await page.mouse.down();await page.mouse.move(130,140,{steps:10});await page.mouse.up();
  await expect(panel(page)).toBeVisible();await expect(editor(page)).toHaveValue(draft);
  await page.evaluate(()=>{window.martinInput=document.getElementById('martin-question');location.hash='/academy';});
  await expect(panel(page).locator('[data-martin-context]')).toHaveText('Academy');
  expect(await page.evaluate(()=>window.martinInput===document.getElementById('martin-question'))).toBe(true);
  const keys=[];let interrupted=false;
  await page.route('**/api/v1/me/martin/turns',async route=>{keys.push(route.request().headers()['idempotency-key']);if(!interrupted){interrupted=true;const accepted=await route.fetch();expect(accepted.status()).toBe(202);return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Martin response interrupted'}})});}return route.continue();});
  await send(page).click();await expect(panel(page).getByRole('alert')).toContainText('Martin response interrupted');
  await send(page).click();await expect(panel(page)).toContainText('Your question is queued');expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1]);
  await expect(send(page)).toBeDisabled();await work(request);
  await expect(panel(page).locator('.martin-source')).toHaveCount(1,{timeout:10000});
  const citation=panel(page).locator('.martin-source').first();await expect(citation).not.toHaveAttribute('open','');await expect(citation.locator('a')).toBeHidden();await citation.locator('summary').click();await expect(citation.locator('a')).toBeVisible();
  await expect(panel(page).locator('.martin-source a')).toHaveAttribute('href',/#\/academy\//);await expect(panel(page).locator('img')).toHaveCount(0);
  await editor(page).fill('Can you explain that further?');await page.keyboard.press('Enter');await expect(panel(page).locator('.martin-user-message')).toHaveCount(2);await work(request);
  await expect(panel(page).locator('.martin-source')).toHaveCount(2,{timeout:10000});
  await page.getByRole('button',{name:'Minimize Ask Martin',exact:true}).click();await open(page);await expect(panel(page).locator('.martin-user-message')).toHaveCount(2);
  await page.reload();await open(page);await panel(page).getByRole('button',{name:'Chat history',exact:true}).click();await panel(page).locator('[data-martin="conversation"]').click();await expect(panel(page).locator('.martin-user-message')).toHaveCount(2);
  await page.screenshot({path:'/tmp/investiq-martin-connected-desktop.png',fullPage:false});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/investiq-martin-connected-mobile.png',fullPage:false});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.setViewportSize({width:1280,height:900});await panel(page).getByRole('button',{name:'Chat history',exact:true}).click();page.once('dialog',dialog=>dialog.accept());await panel(page).getByRole('button',{name:'Delete chat: '+draft,exact:true}).click();await expect(panel(page)).toContainText('Chat deleted.');await expect(panel(page)).toContainText('No saved chats yet');expect(errors).toEqual([]);
});

test('Martin handles pending performance data, cancellation, reload and account boundaries',async({page,request,browser})=>{
  await signIn(page,request);await panel(page).getByRole('button',{name:'My performance',exact:true}).click();
  await editor(page).fill('Where can I improve?');await send(page).click();await expect(panel(page)).toContainText('Your question is queued');
  await panel(page).getByRole('button',{name:'Cancel question',exact:true}).click();await expect(panel(page)).toContainText('Question cancelled.');
  await panel(page).getByRole('button',{name:'New chat',exact:true}).click();await editor(page).fill('How did I perform?');await send(page).click();await expect(panel(page)).toContainText('Your question is queued');await work(request);
  await expect(panel(page).locator('.martin-source')).toContainText('No published portfolio valuations',{timeout:10000});
  const threads=await page.evaluate(async()=>(await (await fetch('/api/v1/me/martin/conversations')).json()).items);expect(threads).toHaveLength(2);
  const context=await browser.newContext(),other=await context.newPage();await signIn(other,request);await panel(other).getByRole('button',{name:'Chat history',exact:true}).click();await expect(panel(other)).toContainText('No saved chats yet');
  expect(await other.evaluate(async id=>(await fetch('/api/v1/me/martin/conversations/'+id)).status,threads[0].id)).toBe(404);await context.close();
  await page.getByRole('button',{name:'Minimize Ask Martin',exact:true}).click();await page.getByRole('link',{name:'Sign out',exact:true}).click();await expect(launcher(page)).toBeHidden();await page.goto('/#/dashboard');await open(page);await expect(editor(page)).toHaveValue('');await expect(panel(page)).toContainText('Sign in to ask Martin');
});
