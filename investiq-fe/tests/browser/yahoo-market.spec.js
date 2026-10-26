import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

test('Home labels Yahoo Nifty levels and keeps missing prices unavailable',async({page,request})=>{
  await verifiedAccount(page,request,`yahoo-overview-${randomUUID()}@example.com`);
  const benchmark=randomUUID();let missing=false;
  await page.route('**/api/v1/market/status',route=>route.fulfill({json:{mode:'yahoo',benchmark_id:benchmark,latest_session_date:'2026-10-16'}}));
  await page.route('**/api/v1/quotes?**',route=>{
    if(new URL(route.request().url()).searchParams.get('instrument_ids')!==benchmark)return route.continue();
    return route.fulfill({json:{data_kind:'yahoo',all_current:!missing,expected_session_date:'2026-10-16',items:[{instrument_id:benchmark,symbol:'NIFTY50',open:missing?null:'25000.0000',close:missing?null:'25250.0000',day_change_pct:missing?null:'1.0000',session_date:missing?null:'2026-10-16',freshness:missing?'missing':'current_eod',source:'yahoo-finance'}]}});
  });
  await page.goto('/#/home');await page.reload();
  const overview=page.getByRole('region',{name:'Nifty 50 market overview'});
  await expect(overview).toContainText('25,000');
  await expect(overview).toContainText('25,250');
  await expect(overview).toContainText('1%');
  await expect(overview).toContainText('2026-10-16');
  await expect(overview).toContainText('Yahoo Finance');
  missing=true;
  await page.getByRole('button',{name:'Refresh results',exact:true}).click();
  await expect(overview).toContainText('Awaiting a complete daily price import');
  await expect(overview).toContainText('Awaiting data');
  await expect(overview).not.toContainText('25,250');
});
