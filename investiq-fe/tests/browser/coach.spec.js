import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';
const harness={'X-Investiq-Browser-Test':'local-disposable-only'};
async function clock(request,at){expect((await request.post('http://127.0.0.1:8081/__browser__/clock',{headers:harness,data:{at}})).ok()).toBeTruthy();}
async function scenario(page){
 return page.evaluate(async()=>{
  const token=await (await fetch('/api/v1/auth/csrf')).json();
  const headers={'Content-Type':'application/json','X-CSRF-Token':token.csrf_token};
  async function post(path,body,key){const r=await fetch('/api/v1'+path,{method:'POST',headers:{...headers,...(key?{'Idempotency-Key':key}:{})},...(body?{body:JSON.stringify(body)}:{})});if(!r.ok)throw Error('Coach scenario failed: '+path);return r.json();}
  const input=await (await fetch('/api/v1/contest-template')).json();
  Object.assign(input,{name:'Coach evidence simulation',entry_opens_at:'2026-10-14T12:40:00Z',entry_closes_at:'2026-10-15T03:40:00Z',starts_at:'2026-10-15T03:45:00Z',ends_at:'2026-10-16T10:00:00Z'});
  const c=await post('/contests',input,crypto.randomUUID()),path='/contests/'+c.id;
  await post(path+'/transitions',{action:'publish'});await post(path+'/entries');
  const draft=await fetch('/api/v1'+path+'/portfolio/draft',{method:'PUT',headers,body:JSON.stringify({expected_revision:0,mode:'weight',positions:input.rules.eligible_instrument_ids.slice(0,5).map(instrument_id=>({instrument_id,weight_pct:'20'}))})});if(!draft.ok)throw Error('Draft failed');
  const reviewed=await post(path+'/portfolio/preview',{draft_revision:1});await post(path+'/submissions',{draft_revision:1,preview_hash:reviewed.preview_hash},crypto.randomUUID());
  return c.id;
 });
}

test('coach waits for real evidence, retries accepted requests, saves cited reports and private reflections',async({page,request,browser})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await clock(request,'2026-10-14T13:00:00Z');
 try{
  await verifiedAccount(page,request,`coach-${randomUUID()}@example.com`);
  const id=await scenario(page);await page.goto('/#/insights/'+id);
  await expect(page.locator('.main')).toContainText('A confirmed portfolio and at least one published valuation are required');
  await expect(page.getByRole('button',{name:'Generate coach report',exact:true})).toHaveCount(0);
  await page.getByRole('navigation',{name:'AI Insights sections'}).getByRole('button',{name:'Journal',exact:true}).click();
  await page.getByLabel('My reasoning',{exact:true}).fill('Private reflection <script>alert(1)</script>');
  await page.getByRole('button',{name:'Save reflection',exact:true}).click();
  await expect(page.getByText('Private reflection <script>alert(1)</script>',{exact:true})).toBeVisible();
  await clock(request,'2026-10-15T13:00:00Z');
  expect((await request.post(`http://127.0.0.1:8081/__browser__/value/${id}`,{headers:harness})).ok()).toBeTruthy();
  await page.getByRole('button',{name:'Refresh coach',exact:true}).click();
  await page.getByRole('navigation',{name:'AI Insights sections'}).getByRole('button',{name:'Evidence',exact:true}).click();
  await expect(page.locator('.main')).toContainText('Portfolio return is');
  const keys=[];let interrupted=false;
  await page.route('**/api/v1/me/coach/jobs',async route=>{
   if(route.request().method()!=='POST')return route.continue();keys.push(route.request().headers()['idempotency-key']);
   if(!interrupted){interrupted=true;const accepted=await route.fetch();expect(accepted.status()).toBe(202);return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Coach response interrupted'}})});}
   return route.continue();
  });
  await page.getByRole('button',{name:'Generate coach report',exact:true}).click();
  await expect(page.locator('.main')).toContainText('Coach response interrupted');
  await page.getByRole('button',{name:'Generate coach report',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Report queued',exact:true})).toBeVisible();
  expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1]);
  expect((await request.post('http://127.0.0.1:8081/__browser__/coach-work',{headers:harness})).ok()).toBeTruthy();
  await page.getByRole('navigation',{name:'AI Insights sections'}).getByRole('button',{name:'Overview',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Report ready',exact:true})).toBeVisible({timeout:10000});
  await expect(page.locator('.coach-takeaways li')).toHaveCount(2);
  await expect(page.getByText('Technical report details',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Explore learning',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Suggested learning actions',exact:true})).toBeVisible();
  await expect(page.locator('.main')).not.toContainText('You sold Infosys too early');
  await page.getByRole('button',{name:'Write a reflection',exact:true}).click();
  await page.getByLabel('My reasoning',{exact:true}).fill('Draft preserved between sections');
  await page.getByRole('navigation',{name:'AI Insights sections'}).getByRole('button',{name:'Overview',exact:true}).click();
  await page.getByRole('navigation',{name:'AI Insights sections'}).getByRole('button',{name:'Journal',exact:true}).click();
  await expect(page.getByLabel('My reasoning',{exact:true})).toHaveValue('Draft preserved between sections');
  await page.reload();await expect(page.getByRole('heading',{name:'Report ready',exact:true})).toBeVisible();
  await expect(page.locator('[data-coach-job]')).toHaveCount(1);
  await page.getByRole('navigation',{name:'AI Insights sections'}).getByRole('button',{name:'Journal',exact:true}).click();
  await expect(page.getByText('Private reflection <script>alert(1)</script>',{exact:true})).toBeVisible();
  await page.getByRole('navigation',{name:'AI Insights sections'}).getByRole('button',{name:'Past reports',exact:true}).click();
  await page.getByRole('button',{name:'Open report',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your key takeaways',exact:true})).toBeVisible();
  await page.screenshot({path:'/tmp/investiq-coach-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/investiq-coach-mobile.png',fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await clock(request,'2026-10-16T13:00:00Z');
  expect((await request.post(`http://127.0.0.1:8081/__browser__/value/${id}`,{headers:harness})).ok()).toBeTruthy();
  await page.getByRole('button',{name:'Refresh coach',exact:true}).click();
  await expect(page.locator('.coach-older')).toContainText('Earlier snapshot');
  await page.getByRole('button',{name:'Generate coach report',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Report queued',exact:true})).toBeVisible();
  expect((await request.post('http://127.0.0.1:8081/__browser__/coach-work',{headers:harness})).ok()).toBeTruthy();
  await page.getByRole('navigation',{name:'AI Insights sections'}).getByRole('button',{name:'Past reports',exact:true}).click();
  await expect(page.getByRole('button',{name:'Open report',exact:true})).toHaveCount(2,{timeout:10000});
  await page.getByRole('button',{name:'Show latest report',exact:true}).click();
  await expect(page.locator('.coach-report-context')).toContainText('2026-10-16');
  await expect(page.locator('.coach-older')).toHaveCount(0);
  const context=await browser.newContext();const other=await context.newPage();
  await verifiedAccount(other,request,`coach-other-${randomUUID()}@example.com`);await other.goto('/#/insights/'+id);
  await expect(other.getByRole('alert')).toContainText('Contest not found');
  await expect(other.getByText('Private reflection <script>alert(1)</script>',{exact:true})).toHaveCount(0);
  await context.close();expect(errors).toEqual([]);
 }finally{await clock(request,'2026-10-18T12:00:00Z');}
});

test('coach guests and API failures have explicit states without sample AI claims',async({page,request})=>{
 await page.goto('/#/insights');await expect(page.getByRole('link',{name:'Sign in',exact:true})).toBeVisible();
 await expect(page.locator('.main')).not.toContainText('Dividend Derby');
 await verifiedAccount(page,request,`coach-failure-${randomUUID()}@example.com`);
 await page.route('**/api/v1/me/contests?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Coach contest list unavailable'}})}));
 await page.goto('/#/insights');await expect(page.getByRole('alert')).toContainText('Coach contest list unavailable');
 await page.unroute('**/api/v1/me/contests?*');await page.getByRole('button',{name:'Retry coach',exact:true}).click();
 await expect(page.locator('.main')).toContainText('Join a contest and submit a portfolio');
});

test('daily user summary updates from closing results and keeps contest reports below it',async({page,request})=>{
 await clock(request,'2026-10-14T13:00:00Z');
 try{
  await verifiedAccount(page,request,`daily-coach-${randomUUID()}@example.com`);
  await page.goto('/#/insights');
  const summary=page.getByRole('region',{name:'Your daily insights',exact:true});
  await expect(summary.getByRole('heading',{name:'No AI insights yet',exact:true})).toBeVisible();
  await expect(summary.getByRole('heading',{name:'Strengths',exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Per-contest reports',exact:true})).toHaveCount(0);
  const id=await scenario(page);
  await page.getByRole('button',{name:'Refresh coach',exact:true}).click();
  await expect(summary).toContainText('Waiting for your first results');
  await expect(page.getByRole('heading',{name:'Per-contest reports',exact:true})).toBeVisible();
  await clock(request,'2026-10-15T13:00:00Z');
  expect((await request.post(`http://127.0.0.1:8081/__browser__/value/${id}`,{headers:harness})).ok()).toBeTruthy();
  await page.getByRole('button',{name:'Refresh coach',exact:true}).click();
  await expect(summary).toContainText('AI review in progress');
  await expect(summary).toContainText('Overall contest return');
  expect((await request.post('http://127.0.0.1:8081/__browser__/coach-daily-work',{headers:harness})).ok()).toBeTruthy();
  await expect(summary).toContainText('Up to date',{timeout:10000});
  await expect(summary.getByRole('heading',{name:'Strengths',exact:true})).toBeVisible();
  await expect(summary.getByRole('heading',{name:'Areas to improve',exact:true})).toBeVisible();
  await expect(summary).toContainText('Know the risk you can live with');
  await expect(summary).toContainText('Try next');
  await expect(summary).toContainText('Your progress:');
  await expect(summary).not.toContainText('contributed positively');
  await expect(summary).not.toContainText('largest-position weight');
  await expect(summary).toContainText('15 Oct 2026');
  const perContest=page.getByRole('heading',{name:'Per-contest reports',exact:true});
  expect(await summary.evaluate((node)=>node.compareDocumentPosition(document.querySelector('.coach-intro'))&Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy();
  await expect(perContest).toBeVisible();
  await page.screenshot({path:'/tmp/investiq-daily-insights-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/tmp/investiq-daily-insights-mobile.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.getByRole('link',{name:'Open performance coach',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Report ready',exact:true})).toBeVisible();
  await expect(summary).toContainText('Up to date');
  await page.setViewportSize({width:1280,height:900});
  await page.goto('/#/insights');
  await clock(request,'2026-10-16T13:00:00Z');
  expect((await request.post(`http://127.0.0.1:8081/__browser__/value/${id}`,{headers:harness})).ok()).toBeTruthy();
  await page.getByRole('button',{name:'Refresh coach',exact:true}).click();
  await expect(summary).toContainText('AI review in progress');
  await expect(summary).toContainText('16 Oct 2026');
  await expect(summary.locator('.coach-habit')).toHaveCount(4);
  expect((await request.post('http://127.0.0.1:8081/__browser__/coach-daily-work',{headers:harness})).ok()).toBeTruthy();
  await expect(summary).toContainText('Up to date',{timeout:10000});
  await expect(summary).toContainText('1 completed');
 }finally{await clock(request,'2026-10-18T12:00:00Z');}
});
