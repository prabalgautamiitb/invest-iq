import { randomUUID } from 'node:crypto';
import { test, expect } from '@playwright/test';
import { verifiedAccount } from './helpers.js';

async function league(page,name='Portfolio browser league') {
  return page.evaluate(async({name,key})=>{
    const csrf=await (await fetch('/api/v1/auth/csrf')).json();
    const headers={'Content-Type':'application/json','X-CSRF-Token':csrf.csrf_token};
    const template=await (await fetch('/api/v1/contest-template')).json();
    const c=await (await fetch('/api/v1/contests',{method:'POST',headers:{...headers,'Idempotency-Key':key},body:JSON.stringify({...template,name})})).json();
    for(const [endpoint,body] of [['transitions',{action:'publish'}],['entries',undefined]]) {
      const r=await fetch(`/api/v1/contests/${c.id}/${endpoint}`,{method:'POST',headers,...(body?{body:JSON.stringify(body)}:{})});
      if(!r.ok) throw new Error('Could not prepare test membership');
    }
    return c.id;
  },{name,key:randomUUID()});
}
const signup=(page,request)=>verifiedAccount(page,request,`portfolio-${randomUUID()}@example.com`);
const draft=(page,id)=>page.evaluate(async id=>(await (await fetch(`/api/v1/contests/${id}/portfolio/draft`)).json()),id);
const button=(page,name)=>page.getByRole('button',{name,exact:true});

test('save, reload, review, submit, convert to quantities and retain immutable versions',async({page,request})=>{
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await signup(page,request);
  const id=await league(page);
  await page.goto('/#/contests/'+id);
  await page.getByRole('link',{name:'Open contest portfolio',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your contest draft',exact:true})).toBeVisible();
  await button(page,'Use starter weights').click();
  await expect(page.locator('[name="portfolio-position"]')).toHaveCount(5);
  await expect(button(page,'Review saved draft')).toBeDisabled();
  await button(page,'Save draft').click();
  await expect(page.getByText('Draft saved on the server.',{exact:true})).toBeVisible();
  expect((await draft(page,id)).revision).toBe(1);
  await page.reload();
  await expect(page.locator('[name="portfolio-position"]')).toHaveCount(5);
  const reviewing=page.waitForResponse(r=>r.url().endsWith('/portfolio/preview') && r.request().method()==='POST');
  await button(page,'Review saved draft').click();
  const initial=await (await reviewing).json();
  await expect(page.getByRole('heading',{name:'Review server calculation',exact:true})).toBeVisible();
  await expect(page.locator('#portfolio-review')).toContainText('2026-10-16');
  await button(page,'Confirm contest submission').click();
  await expect(page.locator('#portfolio-history')).toContainText('Version 1');
  await page.reload();
  await expect(page.locator('#portfolio-history')).toContainText('Version 1');
  await button(page,'Review saved draft').click();
  await button(page,'Use reviewed quantities').click();
  await expect(page.locator('[name="portfolio-position"]').first()).toHaveAttribute('step','1');
  await button(page,'Save draft').click();
  await expect.poll(async()=>(await draft(page,id)).mode).toBe('quantity');
  const rerun=page.waitForResponse(r=>r.url().endsWith('/portfolio/preview') && r.request().method()==='POST');
  await button(page,'Review saved draft').click();
  const converted=await (await rerun).json();
  expect(converted.notional).toBe(initial.notional);
  expect(converted.fee).toBe(initial.fee);
  await button(page,'Confirm contest submission').click();
  await expect(page.locator('#portfolio-history')).toContainText('Version 2');
  await expect(page.locator('#portfolio-history')).toContainText('Version 1');
  expect(errors).toEqual([]);
});

test('stale tab cannot overwrite a newer revision, quote failures preserve drafts, contests stay isolated',async({page,context,request})=>{
  await signup(page,request);
  const first=await league(page,'First saved portfolio');
  const second=await league(page,'Second separate portfolio');
  const tab=await context.newPage();
  await page.goto('/#/portfolio/'+first);
  await tab.goto('/#/portfolio/'+first);
  await button(page,'Use starter weights').click();
  await button(tab,'Use starter weights').click();
  await button(page,'Save draft').click();
  await expect.poll(async()=>(await draft(page,first)).revision).toBe(1);
  await button(tab,'Save draft').click();
  await expect(tab.getByRole('alert')).toContainText('Draft changed in another tab');
  await expect(tab.locator('#portfolio-dirty')).toContainText('Unsaved changes');
  tab.once('dialog',dialog=>dialog.accept());
  await button(tab,'Reload portfolio').click();
  await expect(tab.locator('#portfolio-dirty')).toContainText('Saved on server');
  await tab.route('**/api/v1/quotes?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Quotes temporarily unavailable'}})}));
  await tab.reload();
  await expect(tab.getByRole('alert')).toContainText('Quotes temporarily unavailable');
  await expect(tab.locator('[name="portfolio-position"]')).toHaveCount(5);
  for(const item of await tab.locator('#server-stockrows [data-portfolio-action="add"]').all()) await expect(item).toBeDisabled();
  await page.goto('/#/portfolio/'+second);
  await expect(page.getByRole('heading',{name:'Second separate portfolio',exact:true})).toBeVisible();
  await expect(page.locator('[name="portfolio-position"]')).toHaveCount(0);
  expect((await draft(page,second)).revision).toBe(0);
  await page.goto('/#/portfolio');
  await expect(page.getByRole('heading',{name:'First saved portfolio',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Second separate portfolio',exact:true})).toBeVisible();
  await tab.close();
});

test('switching contests during a pending save does not overwrite or disable another portfolio',async({page,request})=>{
  await signup(page,request);
  const first=await league(page,'Pending save portfolio');
  const second=await league(page,'Independent portfolio');
  await page.goto('/#/portfolio/'+first);
  await button(page,'Use starter weights').click();
  let release,started;
  const gate=new Promise(resolve=>release=resolve);
  const saving=new Promise(resolve=>started=resolve);
  await page.route(`**/contests/${first}/portfolio/draft`,async route=>{
    if(route.request().method()==='PUT') {started();await gate;}
    await route.continue();
  });
  try {
    await button(page,'Save draft').click();
    await saving;
    await page.evaluate(id=>{location.hash='/portfolio/'+id;},second);
    await expect(page.getByRole('heading',{name:'Independent portfolio',exact:true})).toBeVisible();
    await expect(button(page,'Save draft')).toBeEnabled();
    await expect(page.locator('[name="portfolio-position"]')).toHaveCount(0);
    release();
    await expect.poll(async()=>(await draft(page,first)).revision).toBe(1);
    await expect(page.getByRole('heading',{name:'Independent portfolio',exact:true})).toBeVisible();
    expect((await draft(page,second)).revision).toBe(0);
  } finally {release();}
});
