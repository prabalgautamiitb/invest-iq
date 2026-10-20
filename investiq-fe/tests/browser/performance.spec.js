import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

const harness={'X-Investiq-Browser-Test':'local-disposable-only'};
const normal='2026-10-18T12:00:00Z';
async function clock(request,at){const r=await request.post('http://127.0.0.1:8081/__browser__/clock',{headers:harness,data:{at}});expect(r.ok()).toBeTruthy();}
async function evaluate(request,id){const r=await request.post(`http://127.0.0.1:8081/__browser__/value/${id}`,{headers:harness});expect(r.ok()).toBeTruthy();return r.json();}

async function scenario(page,confirmed=true){
  return page.evaluate(async confirmed=>{
    const csrf=await (await fetch('/api/v1/auth/csrf')).json();
    const headers={'Content-Type':'application/json','X-CSRF-Token':csrf.csrf_token};
    const post=async(path,body,key)=>{
      const response=await fetch('/api/v1'+path,{method:'POST',headers:{...headers,...(key?{'Idempotency-Key':key}:{})},...(body?{body:JSON.stringify(body)}:{})});
      if(!response.ok)throw new Error('Scenario preparation failed: '+path);
      return response.json();
    };
    const input=await (await fetch('/api/v1/contest-template')).json();
    Object.assign(input,{name:'Historical simulation results',entry_opens_at:'2026-10-14T12:40:00Z',entry_closes_at:'2026-10-15T03:40:00Z',starts_at:'2026-10-15T03:45:00Z',ends_at:'2026-10-16T10:00:00Z'});
    const c=await post('/contests',input,crypto.randomUUID());
    const path='/contests/'+c.id;
    await post(path+'/transitions',{action:'publish'});
    await post(path+'/entries');
    const draft=await fetch('/api/v1'+path+'/portfolio/draft',{method:'PUT',headers,body:JSON.stringify({expected_revision:0,mode:'weight',positions:input.rules.eligible_instrument_ids.slice(0,5).map(instrument_id=>({instrument_id,weight_pct:'20'}))})});
    if(!draft.ok)throw new Error('Scenario draft failed');
    if(confirmed){
      const reviewed=await post(path+'/portfolio/preview',{draft_revision:1});
      await post(path+'/submissions',{draft_revision:1,preview_hash:reviewed.preview_hash},crypto.randomUUID());
    }
    return c.id;
  },confirmed);
}

test('simulated results, dashboard aggregates, private performance and final history use persisted snapshots',async({page,request,browser})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await clock(request,'2026-10-14T13:00:00Z');
  try {
    await verifiedAccount(page,request,`performance-${randomUUID()}@example.com`);
    const id=await scenario(page);
    await page.goto('/#/performance/'+id);
    await expect(page.getByRole('heading',{name:'Submission confirmed',exact:true})).toBeVisible();
    await expect(page.getByRole('region',{name:'Results status'})).toContainText('Contest has not started');
    await expect(page.getByRole('region',{name:'Contest timeline'})).toContainText('15 Oct 2026');
    await expect(page.getByRole('region',{name:'Contest timeline'})).toContainText('6:00 pm IST');
    await expect(page.getByRole('heading',{name:'What will appear after valuation',exact:true})).toBeVisible();
    await clock(request,'2026-10-15T04:00:00Z');
    await page.getByRole('button',{name:'Refresh results',exact:true}).click();
    await expect(page.getByRole('region',{name:'Results status'})).toContainText('Waiting for the session close');
    await clock(request,'2026-10-15T13:00:00Z');
    await page.getByRole('button',{name:'Refresh results',exact:true}).click();
    await expect(page.getByRole('region',{name:'Results status'})).toContainText('Valuation is being prepared');
    await evaluate(request,id);
    await page.getByRole('button',{name:'Refresh results',exact:true}).click();
    await expect(page.getByText('Current published snapshot',{exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'Portfolio metrics',exact:true})).toBeVisible();
    await expect(page.locator('.main')).toContainText('2026-10-15');
    await page.goto('/#/leaderboard/'+id);
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('tbody')).toContainText('Learner ');
    await expect(page.locator('tbody')).toContainText('· you');
    await page.goto('/#/dashboard');
    await expect(page.getByRole('heading',{name:'Latest valued portfolios',exact:true})).toBeVisible();
    await expect(page.getByText('Your AI report for Dividend Derby is ready.',{exact:false})).toHaveCount(0);
    await page.goto('/#/my-contests');
    await expect(page.locator('.main')).toContainText('Snapshot 2026-10-15');
    await clock(request,'2026-10-16T13:00:00Z');
    expect((await evaluate(request,id)).status).toBe('completed');
    await page.goto('/#/contest-history');
    await expect(page.locator('tbody')).toContainText('Historical simulation results');
    await expect(page.locator('tbody')).toContainText('completed');
    await page.goto('/#/leaderboard/'+id);
    await expect(page.getByText('Final simulated results',{exact:true})).toBeVisible();
    const context=await browser.newContext();const guest=await context.newPage();
    await guest.goto('/#/leaderboard/'+id);
    await expect(guest.getByRole('alert')).toContainText('Contest not found'); // default visibility is private
    await context.close();
    expect(errors).toEqual([]);
  } finally {await clock(request,normal);}
});

test('performance API failures have retry states without sample ranks or returns',async({page,request})=>{
  await verifiedAccount(page,request,`failed-results-${randomUUID()}@example.com`);
  await page.route('**/api/v1/me/dashboard',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Simulation results unavailable'}})}));
  await page.goto('/#/dashboard');
  await expect(page.getByRole('alert')).toContainText('Simulation results unavailable');
  await expect(page.getByText('+12.84',{exact:false})).toHaveCount(0);
  await page.unroute('**/api/v1/me/dashboard');
  await page.getByRole('button',{name:'Retry results',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Latest valued portfolios',exact:true})).toBeVisible();
});


test('saved drafts show a confirmation action and do not look like ranked submissions',async({page,request})=>{
  await clock(request,'2026-10-14T13:00:00Z');
  try {
    await verifiedAccount(page,request,`draft-status-${randomUUID()}@example.com`);
    const id=await scenario(page,false);
    await page.goto('/#/performance/'+id);
    await expect(page.getByRole('heading',{name:'No confirmed submission',exact:true})).toBeVisible();
    await expect(page.getByRole('region',{name:'Your submission'})).toContainText('Saved drafts are not ranked.');
    await expect(page.getByRole('link',{name:'Open portfolio builder',exact:true})).toBeVisible();
    await page.goto('/#/leaderboard/'+id);
    await expect(page.locator('.main')).toContainText('Confirmed portfolios: 0');
    await expect(page.locator('.main')).toContainText('Ranked portfolios: 0');
    await expect(page.getByRole('region',{name:'Results status'})).toContainText('Contest has not started');
  } finally {await clock(request,normal);}
});
