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
    const unvaluedId=await scenario(page,false);
    await page.goto('/#/my-contests');
    const myCard=page.locator(`.my-contest-card[data-contest-id="${id}"]`);
    const draftCard=page.locator(`.my-contest-card[data-contest-id="${unvaluedId}"]`);
    await expect(myCard).toContainText('Submission confirmed · Awaiting the first published valuation.');
    await expect(myCard.locator('.my-contest-value dd')).toHaveText('—');
    await expect(draftCard).toContainText('No confirmed submission');
    await expect(draftCard.getByRole('link',{name:'Portfolio',exact:true})).toHaveAttribute('href','#/portfolio/'+unvaluedId);
    await page.goto('/#/performance/'+id);
    await expect(page.getByRole('heading',{name:'Submission confirmed',exact:true})).toBeVisible();
    await expect(page.getByRole('region',{name:'Results status'})).toContainText('Contest has not started');
    await page.getByText('Contest schedule',{exact:true}).click();
    await expect(page.getByRole('region',{name:'Contest timeline'})).toContainText('15 Oct 2026');
    await expect(page.getByRole('region',{name:'Contest timeline'})).toContainText('6:00 pm IST');
    await expect(page.getByText('Your chart starts after the first published valuation.',{exact:true})).toBeVisible();
    await page.getByText('Understand your future results',{exact:true}).click();
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
    await expect(page.getByRole('img',{name:'Portfolio and benchmark returns across 1 published daily snapshots'})).toBeVisible();
    await expect(page.getByRole('region',{name:'Portfolio allocation',exact:true})).toBeVisible();
    await expect(page.getByRole('region',{name:'Holding contributions',exact:true})).toBeVisible();
    await page.getByText('Portfolio details and holding values',{exact:true}).click();
    await expect(page.getByRole('heading',{name:'Portfolio metrics',exact:true})).toBeVisible();
    await expect(page.locator('.main')).toContainText('2026-10-15');
    await page.goto('/#/leaderboard/'+id);
    await expect(page.getByRole('region',{name:'Standings at a glance'})).toContainText('#1');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('tbody')).toContainText('Learner ');
    await expect(page.locator('tbody')).toContainText('· you');
    await page.goto('/#/dashboard');
    await expect(page.getByRole('heading',{name:'Latest valued portfolios',exact:true})).toHaveCount(0);
    await expect(page.getByRole('heading',{name:'Build and compete',exact:true})).toHaveCount(0);
    await expect(page.getByRole('img',{name:'Portfolio value across 1 published daily snapshots',exact:true})).toBeVisible();
    const homeCard=page.locator(`[data-home-contest="${id}"]`);
    await expect(homeCard).toContainText('Latest published close');
    await expect(homeCard).toContainText('#1');
    await expect(homeCard.getByRole('link',{name:'View performance',exact:true})).toHaveAttribute('href','#/performance/'+id);
    const pendingCard=page.locator(`[data-home-contest="${unvaluedId}"]`);
    await expect(pendingCard).toContainText('No confirmed submission');
    await expect(pendingCard.getByRole('link',{name:'Build portfolio',exact:true})).toHaveAttribute('href','#/portfolio/'+unvaluedId);
    await page.setViewportSize({width:390,height:844});
    await expect(homeCard.getByRole('link',{name:'Standings',exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await homeCard.screenshot({path:'/tmp/investiq-home-contest-card-mobile.png'});
    await page.setViewportSize({width:1280,height:720});
    const insight=page.getByRole('region',{name:'AI guidance',exact:true});
    await expect(insight).toContainText('Get a coach report');
    await page.getByRole('button',{name:'Generate AI insights',exact:true}).click();
    await expect(insight).toContainText('Your coach report is being prepared');
    expect((await request.post('http://127.0.0.1:8081/__browser__/coach-work',{headers:harness})).ok()).toBeTruthy();
    await expect(insight.locator('.home-insight-list li')).toHaveCount(2,{timeout:12000});
    await expect(insight.getByRole('link',{name:'Open suggested lesson',exact:true})).toHaveAttribute('href',/#\/academy\//);
    await expect(insight.getByRole('link',{name:'Read full AI report',exact:true})).toHaveAttribute('href','#/insights/'+id);
    await page.getByLabel('Contest',{exact:true}).selectOption(unvaluedId,{timeout:5000});
    await expect(page.getByText('Your value chart starts after the first published daily valuation.',{exact:false})).toBeVisible();
    await expect(insight.locator('.home-insight-list')).toHaveCount(0);
    await page.getByRole('button',{name:'Refresh results',exact:true}).click();
    await expect(page.getByLabel('Contest',{exact:true})).toBeEnabled();
    await expect(page.getByLabel('Contest',{exact:true})).toHaveValue(unvaluedId);
    await expect(page.getByText('Your value chart starts after the first published daily valuation.',{exact:false})).toBeVisible();
    await expect(insight.locator('.home-insight-list')).toHaveCount(0);
    await page.getByLabel('Contest',{exact:true}).selectOption(id,{timeout:5000});
    await expect(insight.locator('.home-insight-list li')).toHaveCount(2);
    await page.route('**/api/v1/me/coach/jobs?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Insights temporarily unavailable'}})}));
    await page.getByRole('button',{name:'Refresh results',exact:true}).click();
    await expect(insight.getByRole('alert')).toContainText('Insights temporarily unavailable');
    await expect(page.getByRole('img',{name:'Portfolio value across 1 published daily snapshots',exact:true})).toBeVisible();
    await page.unroute('**/api/v1/me/coach/jobs?*');
    await page.getByRole('button',{name:'Retry AI insights',exact:true}).click();
    await expect(insight.locator('.home-insight-list li')).toHaveCount(2);
    await page.route('**/api/v1/contests/'+id+'/performance?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Portfolio history temporarily unavailable'}})}));
    await page.getByRole('button',{name:'Refresh results',exact:true}).click();
    await expect(page.getByRole('alert').filter({hasText:'Portfolio history temporarily unavailable'})).toBeVisible();
    await expect(insight.locator('.home-insight-list li')).toHaveCount(2);
    await page.unroute('**/api/v1/contests/'+id+'/performance?*');
    await page.getByRole('button',{name:'Retry portfolio chart',exact:true}).click();
    await expect(page.getByRole('img',{name:'Portfolio value across 1 published daily snapshots',exact:true})).toBeVisible();

    await expect(page.getByRole('region',{name:'Your contest returns'})).toContainText('Historical simulation results');
    await expect(page.getByText('Your AI report for Dividend Derby is ready.',{exact:false})).toHaveCount(0);
    await page.goto('/#/my-contests');
    await expect(page.locator('.main')).toContainText('Snapshot 2026-10-15');
    const summary=await page.evaluate(async id=>(await (await fetch('/api/v1/me/dashboard')).json()).items.find(item=>item.contest_id===id),id);
    await expect(myCard.locator('.my-contest-value dd')).toHaveText('₹'+Number(summary.total_value).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}));
    await expect(myCard.locator('.my-contest-metric').nth(3)).toContainText('#1');
    await expect(myCard.locator('.my-contest-guidance')).toContainText('Current · daily close');
    await expect(myCard.getByRole('link',{name:'Performance',exact:true})).toHaveClass(/primary/);
    await page.setViewportSize({width:1440,height:1000});
    expect((await myCard.locator('.my-contest-metrics').boundingBox()).y).toBeLessThan((await myCard.locator('.my-contest-dates').boundingBox()).y);
    await page.screenshot({path:'/tmp/investiq-my-contests-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    expect(await myCard.locator('.my-contest-value dd').evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);return range.getClientRects().length;})).toBe(1);
    await page.screenshot({path:'/tmp/investiq-my-contests-mobile.png',fullPage:true});
    await page.setViewportSize({width:1440,height:1000});
    await page.route('**/api/v1/me/dashboard',route=>route.fulfill({json:{items:[{...summary,total_value:'998765.4321',pnl:'-1234.5678',return_pct:'-0.12345678',rank:null,is_current:false}]}}));
    await page.getByRole('button',{name:'Refresh contests',exact:true}).click();
    await expect(myCard.locator('.my-contest-value dd')).toHaveText('₹9,98,765.43');
    await expect(myCard.locator('.my-contest-metric').nth(1)).toContainText('−₹1,234.57');
    await expect(myCard.locator('.my-contest-metric').nth(2)).toContainText('−0.12%');
    await expect(myCard.locator('.my-contest-metric').nth(2)).toHaveClass(/is-loss/);
    await expect(myCard.locator('.my-contest-metric').nth(3)).toContainText('—');
    await expect(myCard.locator('.my-contest-guidance')).toContainText('Earlier snapshot');
    await page.unroute('**/api/v1/me/dashboard');
    // An older membership omitted from Home still gets its actual private performance.
    await page.route('**/api/v1/me/dashboard',route=>route.fulfill({json:{items:[]}}));
    await page.getByRole('button',{name:'Refresh contests',exact:true}).click();
    await expect(myCard.locator('.my-contest-value dd')).toHaveText('₹'+Number(summary.total_value).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}));
    await page.route('**/api/v1/contests/'+id+'/performance?*',route=>route.fulfill({status:503,json:{error:{message:'Results unavailable'}}}));
    await page.getByRole('button',{name:'Refresh contests',exact:true}).click();
    await expect(myCard.getByRole('alert')).toContainText('Your results could not be loaded');
    await expect(myCard.locator('.my-contest-value dd')).toHaveText('—');
    await expect(myCard).not.toContainText('No confirmed submission');
    await page.unroute('**/api/v1/contests/'+id+'/performance?*');
    await page.unroute('**/api/v1/me/dashboard');
    await page.getByRole('button',{name:'Refresh contests',exact:true}).click();
    await expect(myCard.locator('.my-contest-guidance')).toContainText('Current · daily close');
    await clock(request,'2026-10-16T13:00:00Z');
    expect((await evaluate(request,id)).status).toBe('completed');
    await page.getByRole('button',{name:'Refresh contests',exact:true}).click();
    await expect(myCard.locator('.my-contest-guidance')).toContainText('Final result');
    await page.goto('/#/contest-history');
    await expect(page.locator('tbody')).toContainText('Historical simulation results');
    await expect(page.locator('tbody')).toContainText('completed');
    await page.goto('/#/leaderboard/'+id);
    await expect(page.getByText('Final simulated results',{exact:true})).toBeVisible();
    await page.goto('/#/performance/'+id);
    await expect(page.getByRole('img',{name:'Portfolio and benchmark returns across 2 published daily snapshots'})).toBeVisible();
    const points=await page.locator('.results-chart circle').evaluateAll(nodes=>nodes.map(n=>({x:Number(n.getAttribute('cx')),label:n.querySelector('title').textContent})));
    expect(points[0].x).toBeLessThan(points[1].x);
    expect(points[0].label).toContain('2026-10-15');
    expect(points[1].label).toContain('2026-10-16');
    await page.goto('/#/dashboard');
    await expect(page.getByRole('img',{name:'Portfolio value across 2 published daily snapshots',exact:true})).toBeVisible();
    await expect(page.getByRole('region',{name:'AI guidance',exact:true})).toContainText('Earlier snapshot');
    await page.getByText('Exact portfolio values',{exact:true}).click();
    const valueRows=page.locator('.home-value-chart tbody tr');
    await expect(valueRows).toHaveCount(2);
    await expect(valueRows.first()).toContainText('2026-10-15');
    await expect(valueRows.last()).toContainText('2026-10-16');
    await page.screenshot({path:'/tmp/investiq-home-analysis-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.screenshot({path:'/tmp/investiq-home-analysis-mobile.png',fullPage:true});
    await page.goto('/#/performance/'+id);
    await page.screenshot({path:'/tmp/investiq-performance-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await expect(page.getByRole('region',{name:'Portfolio allocation',exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await page.screenshot({path:'/tmp/investiq-performance-mobile.png',fullPage:true});
    const context=await browser.newContext();const guest=await context.newPage();
    await guest.goto('/#/leaderboard/'+id);
    await expect(guest.getByRole('alert')).toContainText('Contest not found'); // default visibility is private
    await context.close();
    expect(errors).toEqual([]);
  } finally {await clock(request,normal);}
});

test('performance API failures have retry states without sample ranks or returns',async({page,request})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await verifiedAccount(page,request,`failed-results-${randomUUID()}@example.com`);
  await page.route('**/api/v1/me/dashboard',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Simulation results unavailable'}})}));
  await page.goto('/#/dashboard');
  await expect(page.getByRole('alert')).toContainText('Simulation results unavailable');
  await expect(page.getByText('+12.84',{exact:false})).toHaveCount(0);
  await page.unroute('**/api/v1/me/dashboard');
  await page.getByRole('button',{name:'Retry results',exact:true}).click();
  await expect(page.getByRole('region',{name:'Your portfolio analysis',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Latest valued portfolios',exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Build and compete',exact:true})).toHaveCount(0);
  expect(errors).toEqual([]);
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
