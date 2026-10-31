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

test('legacy contest explains its smaller universe while new Nifty 50 portfolios show all 50 stocks',async({page,request})=>{
  await signup(page,request);
  const id=await league(page);
  await page.route('**/api/v1/market/status',route=>route.fulfill({json:{mode:'yahoo'}}));
  await page.goto('/#/portfolio/'+id);
  const discovery=page.getByRole('region',{name:'Stock discovery'});
  await expect(discovery).toContainText('16 contest stocks');
  const explanation=page.getByRole('complementary',{name:'Contest stock list'});
  await expect(explanation).toContainText('It uses synthetic prices');
  await expect(explanation).toContainText('New contests offer all 50 Nifty 50 stocks');
  await expect(explanation.getByRole('link',{name:'Create a Nifty 50 contest'})).toHaveAttribute('href','#/contests/create');
  await button(page,'Use starter weights').click();
  await button(page,'Save draft').click();
  await expect.poll(async()=>(await draft(page,id)).revision).toBe(1);
  await page.reload();
  await expect(page.locator('[name="portfolio-position"]')).toHaveCount(5);
  await expect(explanation).toBeVisible();

  // Model a newly published Yahoo contest without modifying the saved legacy contest.
  const instruments=await page.evaluate(async()=> (await (await fetch('/api/v1/instruments?limit=100&eligible_only=false')).json()).items);
  const expanded=Array.from({length:50},(_,i)=>({...instruments[i%instruments.length],id:i<instruments.length?instruments[i].id:randomUUID(),symbol:'NIFTY'+i,name:'Nifty company '+i,data_kind:'yahoo'}));
  await page.route(`**/api/v1/contests/${id}`,async route=>{
    const response=await route.fetch();const contest=await response.json();
    await route.fulfill({json:{...contest,market_data_kind:'yahoo',rules:{...contest.rules,eligible_instrument_ids:expanded.map(i=>i.id)}}});
  });
  await page.route('**/api/v1/instruments?*',route=>route.fulfill({json:{items:expanded,next_cursor:null}}));
  await page.route('**/api/v1/quotes?*',route=>route.fulfill({json:{items:[],expected_session_date:'2026-10-16'}}));
  await page.reload();
  await expect(discovery).toContainText('50 contest stocks');
  await expect(page.locator('#server-stockrows .portfolio-stock')).toHaveCount(50);
  await expect(explanation).toHaveCount(0);
  await expect(page.locator('[name="portfolio-position"]')).toHaveCount(5);
});

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
  await expect(tab.getByRole('alert')).toBeFocused();
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

test('live discovery and allocation guidance preserve edits and work on mobile',async({page,request})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await signup(page,request);
  const id=await league(page,'My investment strategy');
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('/#/portfolio/'+id);
  const search=page.getByRole('searchbox',{name:'Search eligible stocks'});
  await expect(search).toBeVisible();
  await search.pressSequentially('no-such-stock');
  await expect(search).toBeFocused();
  await expect(page.getByRole('heading',{name:'No matching stocks',exact:true})).toBeVisible();
  await button(page,'Clear filters').click();
  await expect(search).toHaveValue('');
  await expect(search).toBeFocused();
  const first=page.locator('.portfolio-stock').first();
  const symbol=await first.locator('.portfolio-stock-name strong').textContent();
  await search.fill(symbol);
  await page.getByRole('button',{name:'Add '+symbol,exact:true}).click();
  const allocation=page.getByRole('spinbutton',{name:symbol+' weight percent',exact:true});
  await expect(allocation).toBeFocused();
  await allocation.fill('20');
  await expect(page.locator('#portfolio-allocation-summary')).toContainText('20%');
  await expect(page.locator('#portfolio-allocation-summary')).toContainText('Add 4 more holdings');
  await button(page,'Equalize weights').click();
  await expect(allocation).toHaveValue('25');
  await page.getByRole('button',{name:'Remove '+symbol,exact:true}).click();
  await expect(page.locator('[name="portfolio-position"]')).toHaveCount(0);
  await search.fill('');
  await button(page,'Use starter weights').click();
  const positions=page.locator('[name="portfolio-position"]');
  await expect(positions).toHaveCount(5);
  await positions.first().fill('30');
  await expect(page.locator('#portfolio-allocation-summary')).toContainText('Reduce total weights by 10 percentage points');
  await positions.first().fill('');
  await expect(page.locator('#portfolio-allocation-summary')).toContainText('Enter a positive weight for every holding');
  await button(page,'Equalize weights').click();
  await expect(page.locator('#portfolio-allocation-summary')).toContainText('100%');
  await positions.first().fill('20.0001');
  await expect(page.locator('#portfolio-allocation-summary')).toContainText('Reduce total weights by 0.0001 percentage points');
  await button(page,'Equalize weights').click();
  page.once('dialog',dialog=>dialog.dismiss());
  await button(page,'Quantity').click();
  await expect(positions.first()).toHaveValue('20');
  await expect(button(page,'Weight %')).toHaveAttribute('aria-pressed','true');
  page.once('dialog',dialog=>dialog.accept());
  await button(page,'Quantity').click();
  await expect(positions.first()).toHaveValue('');
  await positions.first().fill('1.5');
  await expect(page.locator('#portfolio-allocation-summary')).toContainText('Enter positive whole shares');
  page.once('dialog',dialog=>dialog.accept());
  await button(page,'Use starter weights').click();
  await page.screenshot({path:'/tmp/investiq-portfolio-desktop.png',fullPage:true});
  await button(page,'Save draft').click();
  await expect(page.getByText('Draft saved on the server.',{exact:true})).toBeVisible();
  await button(page,'Review saved draft').click();
  await expect(page.locator('#portfolio-review')).toBeFocused();
  await page.screenshot({path:'/tmp/investiq-portfolio-review.png',fullPage:true});
  await positions.first().fill('19');
  await expect(page.locator('#portfolio-review')).toHaveCount(0);
  await expect(button(page,'Review saved draft')).toBeDisabled();
  await expect(page.locator('#portfolio-next-step')).toContainText('Save your changes');
  await page.setViewportSize({width:390,height:844});
  await page.locator('.portfolio-editor').scrollIntoViewIfNeeded();
  await expect(page.getByRole('region',{name:'Stock discovery',exact:true})).toBeHidden();
  await button(page,'Explore stocks').click();
  await expect(page.getByRole('region',{name:'Portfolio draft',exact:true})).toBeHidden();
  await expect(page.getByRole('region',{name:'Stock discovery',exact:true})).toBeVisible();
  await page.getByRole('button',{name:/Your draft/}).click();
  await expect(page.getByRole('region',{name:'Portfolio draft',exact:true})).toBeVisible();
  await expect(positions.first()).toHaveValue('19');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:'/tmp/investiq-portfolio-mobile.png',fullPage:true});
  expect(errors).toEqual([]);
});

test('stock discovery shows dated opening/closing prices and signed changes without inventing missing data',async({page,request})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await signup(page,request);
  const id=await league(page,'Daily price discovery');
  let symbols=[];
  await page.route('**/api/v1/quotes?*',async route=>{
    const response=await route.fetch();const body=await response.json();
    const cases=[
      {open:'100.0000',close:'110.0000',day_change_pct:'10.0000'},
      {open:'100.0000',close:'95.0000',day_change_pct:'-5.0000'},
      {open:'100.0000',close:'100.0000',day_change_pct:'0.0000'},
      {open:null,close:'102.0000',day_change_pct:null},
      {open:'100.0000',close:'99.0000',day_change_pct:'-1.0000',freshness:'stale',session_date:'2026-10-15',eligible_for_simulation:false},
      {open:null,close:null,day_change_pct:null,freshness:'missing',session_date:null,eligible_for_simulation:false},
    ];
    body.items=body.items.map((quote,index)=>({...quote,...(cases[index]||{})}));
    symbols=body.items.slice(0,6).map(q=>q.symbol);
    body.all_current=false;
    await route.fulfill({response,json:body});
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('/#/portfolio/'+id);
  await expect.poll(()=>symbols.length).toBe(6);
  const card=index=>page.getByRole('article',{name:symbols[index]+' stock information',exact:true});
  await expect(card(0).locator('.portfolio-stock-expanded')).not.toBeVisible();
  await card(0).getByLabel('Details for '+symbols[0],{exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(card(0).locator('.portfolio-stock-expanded')).toBeVisible();
  await expect(card(0)).toContainText('NSE');
  await expect(card(0).locator('.portfolio-stock-prices dt')).toHaveText(['Open','Close']);
  await expect(card(0).locator('.portfolio-stock-quote dd')).toHaveText(['₹110.00','↗ +10.00%']);
  await expect(card(0).locator('time')).toHaveAttribute('datetime','2026-10-16');
  await expect(card(0)).toContainText('16 Oct 2026');
  await expect(card(0)).toContainText('Latest close');
  await expect(card(0)).toContainText('Synthetic prices');
  await expect(card(1).locator('.portfolio-stock-move')).toHaveText('↘ -5.00%');
  await expect(card(1).locator('.portfolio-stock-move')).toHaveClass(/is-down/);
  await expect(card(2).locator('.portfolio-stock-move')).toHaveText('→ 0.00%');
  await expect(card(2).locator('.portfolio-stock-move')).toHaveClass(/is-flat/);
  await expect(card(3).locator('.portfolio-stock-quote dd')).toHaveText(['₹102.00','Unavailable']);
  await expect(card(3).getByRole('button',{name:'Add '+symbols[3],exact:true})).toBeEnabled();
  await expect(card(4)).toContainText('Earlier close');
  await expect(card(4).locator('time')).toHaveAttribute('datetime','2026-10-15');
  await expect(card(4).getByRole('button',{name:'Add '+symbols[4],exact:true})).toBeDisabled();
  await expect(card(5).locator('.portfolio-stock-quote dd')).toHaveText(['Unavailable','Unavailable']);
  await expect(card(5)).toContainText('Awaiting prices');
  await expect(card(5)).toContainText('No trading session');
  await expect(card(5).getByRole('button',{name:'Add '+symbols[5],exact:true})).toBeDisabled();
  await card(0).getByRole('button',{name:'Add '+symbols[0],exact:true}).click();
  await page.getByRole('spinbutton',{name:symbols[0]+' weight percent',exact:true}).fill('20');
  const search=page.getByRole('searchbox',{name:'Search eligible stocks'});
  await search.fill(symbols[1]);
  await expect(page.locator('.portfolio-stock')).toHaveCount(1);
  await expect(card(1).locator('.portfolio-stock-move')).toHaveText('↘ -5.00%');
  await search.fill('');
  await expect(page.getByRole('spinbutton',{name:symbols[0]+' weight percent',exact:true})).toHaveValue('20');
  await page.getByRole('region',{name:'Stock discovery',exact:true}).screenshot({path:'/tmp/investiq-stock-prices-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await button(page,'Explore stocks').click();
  await expect(card(0).locator('.portfolio-stock-quote dd')).toHaveText(['₹110.00','↗ +10.00%']);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.getByRole('region',{name:'Stock discovery',exact:true}).screenshot({path:'/tmp/investiq-stock-prices-mobile.png'});
  for(const width of [360,768,1200,1440]){
    await page.setViewportSize({width,height:900});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    const line=card(1).locator('.portfolio-stock-line');
    expect(await line.evaluate(el=>{const name=el.querySelector('.portfolio-stock-name').getBoundingClientRect(),quote=el.querySelector('.portfolio-stock-quote').getBoundingClientRect(),add=el.querySelector('button').getBoundingClientRect();return Math.abs((name.top+name.bottom)/2-(quote.top+quote.bottom)/2)<2&&add.left>=quote.right&&el.getBoundingClientRect().height<85;})).toBe(true);
    await page.getByRole('region',{name:'Stock discovery',exact:true}).screenshot({path:`/tmp/investiq-stock-list-${width}.png`});
  }
  expect(errors).toEqual([]);
});

test('stock ordering uses numeric prices and signed daily returns, keeps missing quotes last and preserves allocations',async({page,request})=>{
  await signup(page,request);
  const id=await league(page,'Sortable discovery');
  await page.route('**/api/v1/quotes?*',async route=>{
    const response=await route.fetch(),body=await response.json();
    body.items=body.items.sort((a,b)=>a.symbol.localeCompare(b.symbol)).map((q,index)=>({...q,
      ...(index===0?{open:'1',close:'2',day_change_pct:'100'}:
        index===1?{open:'20',close:'10',day_change_pct:'-50'}:
        index===2?{open:'100',close:'100',day_change_pct:'0'}:
        {open:null,close:null,day_change_pct:null,eligible_for_simulation:false}),
    }));
    await route.fulfill({response,json:body});
  });
  await page.goto('/#/portfolio/'+id);
  const order=page.getByRole('combobox',{name:'Sort stocks',exact:true});
  const rows=page.locator('.portfolio-stock');
  await expect(rows).toHaveCount(16);
  const initial=await rows.locator('.portfolio-stock-name strong').allTextContents();
  const [low,mid,high]=initial;
  await page.getByRole('button',{name:'Add '+low,exact:true}).click();
  const allocation=page.getByRole('spinbutton',{name:low+' weight percent',exact:true});
  await allocation.fill('17.5');
  for(const [value,expected] of [
    ['price-asc',[low,mid,high]],['price-desc',[high,mid,low]],
    ['return-desc',[low,high,mid]],['return-asc',[mid,high,low]],
  ]){
    await order.focus();
    await order.selectOption(value);
    await expect(rows.locator('.portfolio-stock-name strong')).toHaveText([...expected,...initial.slice(3)]);
    await expect(allocation).toHaveValue('17.5');
    await expect(page.locator('#portfolio-dirty')).toHaveText('Unsaved changes');
    await expect(order).toBeFocused();
  }
  await page.getByRole('searchbox',{name:'Search eligible stocks',exact:true}).fill(low);
  await expect(rows).toHaveCount(1);
  await expect(order).toHaveValue('return-asc');
  await page.getByRole('searchbox',{name:'Search eligible stocks',exact:true}).fill('');
  await page.setViewportSize({width:360,height:844});
  await button(page,'Explore stocks').click();
  await order.selectOption('price-desc');
  await expect(rows.first().locator('.portfolio-stock-name strong')).toHaveText(high);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
