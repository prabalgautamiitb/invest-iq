import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

async function createCommunity(page,name){
  await page.goto('/#/social');
  await page.locator('.community-create-prompt').getByRole('link',{name:'Create community',exact:true}).click();
  await page.getByLabel('Community name',{exact:true}).fill(name);
  await page.getByLabel('Description',{exact:true}).fill('A learning circle for MBA students comparing investing ideas.');
  await page.getByRole('button',{name:'Create community',exact:true}).click();
  await expect(page).toHaveURL(/#\/social\/group\/[0-9a-f-]+$/);
  await expect(page.locator('.community-banner')).toContainText('Created by you');
  await expect(page.locator('.community-banner')).toContainText('1 member');
  return page.url().split('/').at(-1);
}
const postCard=(page,text)=>page.locator('[data-community-post]').filter({hasText:text});
const nav=page=>page.getByRole('navigation',{name:'Community sections',exact:true});

test('community discovery, membership and personal feeds unlock posts and revoke access after leaving',async({page,request,browser})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('investiq-demo-v1',JSON.stringify({posts:[{text:'A fake local community import'}]})));
  await verifiedAccount(page,request,`community-owner-${randomUUID()}@example.com`);
  const name='MBA circle '+randomUUID(),id=await createCommunity(page,name);
  const text='Diversification question '+randomUUID();
  await page.getByLabel('Your post',{exact:true}).fill(text);
  await page.getByRole('button',{name:'Publish post',exact:true}).click();
  const card=postCard(page,text);
  await expect(card).toHaveCount(1);
  await card.getByRole('button',{name:'Save',exact:true}).click();
  await card.getByRole('button',{name:'Like · 0',exact:true}).click();
  await expect(card.getByRole('button',{name:'Unlike · 1',exact:true})).toBeVisible();
  await card.getByRole('link',{name:'0 replies',exact:true}).click();
  await page.getByLabel('Your reply',{exact:true}).fill('This is a genuine saved reply.');
  await page.getByRole('button',{name:'Reply',exact:true}).click();
  await expect(page.getByText('This is a genuine saved reply.',{exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByText('This is a genuine saved reply.',{exact:true})).toBeVisible();
  await nav(page).getByRole('link',{name:'My feed',exact:true}).click();
  await expect(card).toHaveCount(1);
  await expect(page.locator('.main')).not.toContainText('A fake local community import');
  await nav(page).getByRole('link',{name:'Saved posts',exact:true}).click();
  await expect(card).toHaveCount(1);
  const context=await browser.newContext({viewport:{width:390,height:844}}),other=await context.newPage();
  await other.goto('/#/social/group/'+id);
  await expect(other.getByRole('heading',{name:'Join the conversation',exact:true})).toBeVisible();
  await expect(postCard(other,text)).toHaveCount(0);
  await verifiedAccount(other,request,`community-member-${randomUUID()}@example.com`);
  await other.goto('/#/social');
  await expect(other.getByRole('heading',{name:'Find your people',exact:true})).toBeVisible();
  await nav(other).getByRole('link',{name:'Discover',exact:true}).click();
  await other.getByRole('searchbox',{name:'Search communities',exact:true}).fill(name);
  await other.getByRole('button',{name:'Search',exact:true}).click();
  const group=other.locator('[data-community-group="'+id+'"]');
  await expect(group).toBeVisible();
  await group.getByRole('link',{name:'Open community',exact:false}).click();
  await expect(postCard(other,text)).toHaveCount(0);
  await other.getByRole('button',{name:'Join community',exact:true}).click();
  await expect(postCard(other,text)).toHaveCount(1);
  await expect(postCard(other,text)).toContainText('Private learner');
  await postCard(other,text).getByRole('button',{name:'Save',exact:true}).click();
  await nav(other).getByRole('link',{name:'My feed',exact:true}).click();
  await expect(postCard(other,text)).toHaveCount(1);
  await other.locator('.community-composer summary').click();
  await expect(other.getByRole('combobox',{name:'Post community',exact:true})).toHaveValue(id);
  await other.getByLabel('Your post',{exact:true}).fill('A member contribution to the joined feed.');
  await other.getByRole('button',{name:'Publish post',exact:true}).click();
  await expect(postCard(other,'A member contribution')).toHaveCount(1);
  await other.goto('/#/social/group/'+id);
  await expect(postCard(other,text)).toHaveCount(1);
  await other.screenshot({path:'/tmp/investiq-community-mobile.png',fullPage:true});
  expect(await other.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  other.once('dialog',d=>d.accept());
  await other.getByRole('button',{name:'Leave community',exact:true}).click();
  await expect(postCard(other,text)).toHaveCount(0);
  await expect(other.getByRole('heading',{name:'Join the conversation',exact:true})).toBeVisible();
  await nav(other).getByRole('link',{name:'Saved posts',exact:true}).click();
  await expect(postCard(other,text)).toHaveCount(0);
  await other.goto('/#/social/group/'+id);
  await other.getByRole('button',{name:'Join community',exact:true}).click();
  await nav(other).getByRole('link',{name:'Saved posts',exact:true}).click();
  await expect(postCard(other,text)).toHaveCount(1);
  await page.goto('/#/social/groups');
  await page.getByRole('button',{name:'Created by you',exact:true}).click();
  await expect(page.locator('[data-community-group="'+id+'"]')).toContainText(name);
  await page.screenshot({path:'/tmp/investiq-community-desktop.png',fullPage:true});
  await context.close();expect(errors).toEqual([]);
});

test('community polls retry idempotently with their full draft and keep votes private',async({page,request})=>{
  await verifiedAccount(page,request,`community-poll-${randomUUID()}@example.com`);
  const id=await createCommunity(page,'Poll circle '+randomUUID());
  await page.getByRole('combobox',{name:'Post category',exact:true}).selectOption('poll');
  const poll='Poll '+randomUUID();
  await page.getByLabel('Your post',{exact:true}).fill(poll);
  await page.getByLabel('Poll options (one per line, 2–6)',{exact:true}).fill('Diversify\nConcentrate');
  const keys=[];let interrupted=false;
  await page.route('**/api/v1/community/posts',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    keys.push(route.request().headers()['idempotency-key']);
    if(!interrupted){interrupted=true;const accepted=await route.fetch();expect(accepted.status()).toBe(201);return route.fulfill({status:503,json:{error:{message:'Post response interrupted'}}});}
    return route.continue();
  });
  await page.getByRole('button',{name:'Publish post',exact:true}).click();
  await expect(page.locator('.main').getByRole('status')).toContainText('Post response interrupted');
  await expect(page.getByLabel('Your post',{exact:true})).toHaveValue(poll);
  await expect(page.getByLabel('Poll options (one per line, 2–6)',{exact:true})).toHaveValue('Diversify\nConcentrate');
  await page.getByRole('button',{name:'Publish post',exact:true}).click();
  const card=postCard(page,poll);await expect(card).toHaveCount(1);expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1]);
  await card.getByRole('button',{name:'Diversify 0 votes',exact:true}).click();
  await expect(card).toContainText('1 vote · Your vote');
  await page.reload();await expect(card).toContainText('1 vote · Your vote');
  await page.goto('/#/social');await expect(card).toHaveCount(1);
  await page.screenshot({path:'/tmp/investiq-community-feed-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/tmp/investiq-community-feed-mobile.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.goto('/#/social/group/'+id);await expect(card).toHaveCount(1);
});

test('community errors retry and public general discussions remain available',async({page,request})=>{
  await page.route('**/api/v1/community/posts?*',route=>route.fulfill({status:503,json:{error:{message:'Community feed unavailable'}}}));
  await page.goto('/#/social');
  await expect(page.getByRole('alert')).toContainText('Community feed unavailable');
  await page.unroute('**/api/v1/community/posts?*');
  await page.getByRole('button',{name:'Retry community',exact:true}).click();
  await expect(page.getByRole('link',{name:'Sign in to join the discussion',exact:true})).toBeVisible();
  await verifiedAccount(page,request,`community-lounge-${randomUUID()}@example.com`);
  await page.goto('/#/social/lounge');
  const text='General discussion '+randomUUID();
  await page.getByLabel('Your post',{exact:true}).fill(text);
  await page.getByRole('button',{name:'Publish post',exact:true}).click();
  const card=postCard(page,text);await expect(card).toHaveCount(1);
  await card.getByLabel('Post options',{exact:true}).click();
  await card.getByRole('button',{name:'Report',exact:true}).click();
  await page.getByLabel('Reason',{exact:true}).fill('Please review this discussion.');
  await page.getByRole('button',{name:'Submit report',exact:true}).click();
  await expect(page.locator('.main').getByRole('status')).toContainText('Report sent');
  await nav(page).getByRole('link',{name:'My feed',exact:true}).click();
  await expect(card).toHaveCount(0);
});

test('community feed stays usable across screen sizes and retains a writing draft while filtering',async({page,request})=>{
  await verifiedAccount(page,request,`community-layout-${randomUUID()}@example.com`);
  for(const [name,body] of [
    ['The Investing Classroom','What helped you get comfortable with market ups and downs? I am learning to think in years rather than days.'],
    ['Nifty 50 Collective','A useful habit: write down why you picked a company before looking at its daily price changes. What is on your research checklist?'],
    ['The Diversification Club','Five stocks can still mean one big bet if they all belong to the same sector. How do you balance your portfolio across different businesses?'],
  ]){
    await createCommunity(page,name);
    await page.getByLabel('Your post',{exact:true}).fill(body);
    await page.getByRole('button',{name:'Publish post',exact:true}).click();
    await expect(postCard(page,body)).toHaveCount(1);
  }
  await page.goto('/#/social');
  await expect(page.locator('[data-community-post]')).toHaveCount(3);
  const composer=page.locator('.community-composer');
  await expect(composer.getByLabel('Your post',{exact:true})).not.toBeVisible();
  await composer.locator('summary').focus();
  await page.keyboard.press('Enter');
  await composer.getByLabel('Your post',{exact:true}).fill('A draft worth keeping while I browse.');
  await page.getByRole('button',{name:'Ideas',exact:true}).click();
  await expect(composer.getByLabel('Your post',{exact:true})).toHaveValue('A draft worth keeping while I browse.');
  await page.getByRole('button',{name:'All',exact:true}).click();
  await expect(page.locator('[data-community-post]')).toHaveCount(3);
  await composer.locator('summary').click();
  for(const width of [1440,768,390,360]){
    await page.setViewportSize({width,height:900});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`/tmp/investiq-community-polished-feed-${width}.png`,fullPage:true});
  }
  const first=page.locator('[data-community-post]').first();
  await first.getByLabel('Post options',{exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(first.getByRole('button',{name:'Delete',exact:true})).toBeVisible();
  page.once('dialog',d=>d.dismiss());
  await first.getByRole('button',{name:'Delete',exact:true}).click();
  await expect(page.locator('[data-community-post]')).toHaveCount(3);
  await page.goto('/#/social/groups');
  await expect(page.locator('[data-community-group]')).toHaveCount(3);
  for(const width of [1440,768,360]){
    await page.setViewportSize({width,height:900});
    await page.screenshot({path:`/tmp/investiq-community-polished-directory-${width}.png`,fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
});
