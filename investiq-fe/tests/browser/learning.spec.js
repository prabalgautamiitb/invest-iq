import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

async function course(page){
  const courses=await page.evaluate(async()=> (await (await fetch('/api/v1/courses')).json()).items);
  return courses.find(c=>c.slug==='simulation-foundations');
}
async function answer(page,choices){
  const groups=page.locator('fieldset');
  for(let i=0;i<choices.length;i++)await groups.nth(i).getByRole('radio').nth(choices[i]).check();
}

test('Academy enrolls, scores and persists real progress without repeated XP',async({page,request,browser})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('investiq-demo-v1',JSON.stringify({completed:['essentials'],courseProgress:{essentials:50}})));
  await verifiedAccount(page,request,`learning-${randomUUID()}@example.com`);
  await page.goto('/#/academy');
  await expect(page.getByRole('heading',{name:'Your Academy',exact:true})).toBeVisible();
  await expect(page.getByText('No attempts yet.',{exact:true})).toHaveCount(0);
  await expect(page.getByText('0 / 3 lessons completed',{exact:true})).toHaveCount(2);
  const c=await course(page),lesson=c.lessons[0];
  await page.goto('/#/academy/'+lesson.id);
  await page.getByRole('button',{name:'Enroll to take this quiz',exact:true}).click();
  await expect(page.getByRole('button',{name:'Submit quiz',exact:true})).toBeDisabled();
  await answer(page,[1,1]);
  await page.getByRole('button',{name:'Submit quiz',exact:true}).click();
  await expect(page.getByText('Keep learning · 0/2 correct · 0 XP awarded',{exact:true})).toBeVisible();
  await answer(page,[0,0]);
  await page.getByRole('button',{name:'Submit quiz',exact:true}).click();
  await expect(page.getByText('Quiz passed · 2/2 correct · 25 XP awarded',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Submit quiz',exact:true}).click();
  await expect(page.getByText('Quiz passed · 2/2 correct · 0 XP awarded',{exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading',{name:lesson.title,exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Your attempt history',exact:true})).toBeVisible();
  expect(await page.evaluate(async()=> (await (await fetch('/api/v1/me/learning')).json()).xp)).toBe(25);
  await page.goto('/#/academy');
  await expect(page.getByText('First lesson completed',{exact:false})).toBeVisible();
  await expect(page.getByText('Level 12',{exact:false})).toHaveCount(0);
  const context=await browser.newContext();const other=await context.newPage();
  await verifiedAccount(other,request,`other-learning-${randomUUID()}@example.com`);
  await other.goto('/#/academy');
  await expect(other.getByText('0 / 3 lessons completed',{exact:true})).toHaveCount(2);
  expect(await other.evaluate(async()=> (await (await fetch('/api/v1/me/learning')).json()).xp)).toBe(0);
  await context.close();
  expect(errors).toEqual([]);
});

test('Academy failures can be retried and guests cannot write progress',async({page})=>{
  await page.route('**/api/v1/courses?*',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Curriculum unavailable'}})}));
  await page.goto('/#/academy');
  await expect(page.getByRole('alert')).toContainText('Curriculum unavailable');
  await expect(page.getByText('17-day streak',{exact:false})).toHaveCount(0);
  await page.unroute('**/api/v1/courses?*');
  await page.getByRole('button',{name:'Retry Academy',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Simulation foundations',exact:true})).toBeVisible();
  const c=await course(page);
  await page.goto('/#/academy/'+c.lessons[0].id);
  await expect(page.getByRole('link',{name:'Sign in to take the quiz',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Submit quiz',exact:true})).toHaveCount(0);
});

test('Academy shows the full catalogue and separates enrolled courses from courses to discover',async({page,request})=>{
  await verifiedAccount(page,request,`catalogue-${randomUUID()}@example.com`);
  await page.goto('/#/academy');
  const cards=page.locator('[data-learning-course]');
  const all=page.getByRole('button',{name:'All courses (2)',exact:true});
  await expect(all).toHaveAttribute('aria-pressed','true');
  await expect(cards).toHaveCount(2);
  await page.getByRole('button',{name:'My courses (0)',exact:true}).click();
  await expect(page.getByText('You haven’t enrolled in a course yet.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Browse all courses',exact:true}).click();
  const firstId=await cards.first().getAttribute('data-learning-course');
  await cards.first().getByRole('button',{name:'Enroll in course',exact:true}).click();
  await expect(page.getByRole('button',{name:'My courses (1)',exact:true})).toBeVisible();
  await expect(all).toHaveAttribute('aria-pressed','true');
  await expect(cards).toHaveCount(2);
  await page.getByRole('button',{name:'My courses (1)',exact:true}).click();
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toHaveAttribute('data-learning-course',firstId);
  await page.getByRole('button',{name:'Not enrolled (1)',exact:true}).click();
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).not.toHaveAttribute('data-learning-course',firstId);
  await cards.first().getByRole('button',{name:'Enroll in course',exact:true}).click();
  await expect(page.getByText('You’re enrolled in every published course.',{exact:false})).toBeVisible();
  await expect(page.getByRole('button',{name:'Not enrolled (0)',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.reload();
  await expect(all).toHaveAttribute('aria-pressed','true');
  await expect(cards).toHaveCount(2);
  await expect(page.getByRole('status').filter({hasText:'complete course catalogue'})).toContainText('2 published courses · 2 enrolled · 0 not enrolled');
});

async function lessonFields(page,title){
  await page.getByLabel('Lesson title',{exact:true}).fill(title);
  await page.getByLabel('Completion XP',{exact:true}).fill('60');
  await page.getByLabel('Lesson content',{exact:false}).fill('Spread investments across different assets.\n\nReview exposure regularly.');
  await page.getByLabel('Question text',{exact:true}).fill('What spreads risk?');
  await page.getByLabel('Answer options',{exact:false}).fill('Diversification\nConcentration');
  await page.getByLabel('Correct option number',{exact:true}).fill('1');
  await page.getByLabel('Answer explanation',{exact:true}).fill('Diversification spreads exposure across assets.');
}

test('admin has a focused workspace and publishes courses and lessons learners can complete',async({page,request,browser})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await verifiedAccount(page,request,`content-admin-${randomUUID()}@example.com`);
  const user=await page.evaluate(async()=> (await (await fetch('/api/v1/me')).json()));
  const promoted=await request.post('http://127.0.0.1:8081/__browser__/admin/'+user.id,{headers:{'X-Investiq-Browser-Test':'local-disposable-only'}});
  expect(promoted.ok()).toBeTruthy();
  await page.goto('/#/dashboard');
  await page.reload();
  await expect(page).toHaveURL(/#\/contests\/admin$/);
  const nav=page.getByRole('navigation',{name:'Admin navigation',exact:true});
  await expect(nav.getByRole('link')).toHaveCount(2);
  await expect(nav.getByRole('link',{name:'Contests',exact:true})).toBeVisible();
  await expect(nav.getByRole('link',{name:'Learning content',exact:true})).toBeVisible();
  await expect(page.locator('#martin-root')).toBeHidden();
  await page.goto('/#/portfolio');
  await expect(page).toHaveURL(/#\/contests\/admin$/);
  await nav.getByRole('link',{name:'Learning content',exact:true}).click();
  await page.getByRole('link',{name:'Add course',exact:true}).click();
  const title='Portfolio practice '+randomUUID().slice(0,8);
  await page.getByLabel('Course title',{exact:true}).fill(title);
  await page.getByLabel('URL name',{exact:false}).fill('portfolio-'+randomUUID());
  await page.getByLabel('Course description',{exact:true}).fill('Build confidence in portfolio construction.');
  await lessonFields(page,'Diversification in practice');
  await page.getByRole('button',{name:'Add question',exact:true}).click();
  await expect(page.locator('.admin-question')).toHaveCount(2);
  await page.locator('.admin-question').last().getByRole('button',{name:'Remove question',exact:true}).click();
  await expect(page.getByLabel('Question text',{exact:true})).toHaveValue('What spreads risk?');
  await page.getByLabel('Correct option number',{exact:true}).fill('3');
  await page.getByRole('button',{name:'Publish course',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('choose a correct option number from 1 to 2');
  await expect(page.getByLabel('Lesson content',{exact:false})).toHaveValue(/Spread investments/);
  await page.getByLabel('Correct option number',{exact:true}).fill('1');
  await page.route('**/api/v1/admin/courses',route=>route.fulfill({status:503,json:{error:{message:'Publishing temporarily unavailable'}}}),{times:1});
  await page.getByRole('button',{name:'Publish course',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Publishing temporarily unavailable');
  await expect(page.getByLabel('Course title',{exact:true})).toHaveValue(title);
  await page.getByRole('button',{name:'Publish course',exact:true}).click();
  await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
  await expect(page.getByRole('status').filter({hasText:'Course published'})).toBeVisible();
  await expect(page.locator('.admin-course-summary')).toContainText('Diversification in practice');
  await lessonFields(page,'Review your exposure');
  await page.getByRole('button',{name:'Publish lesson',exact:true}).click();
  await expect(page.locator('.admin-course-summary li')).toHaveCount(2);
  await expect(page.getByRole('status').filter({hasText:'Lesson published'})).toBeVisible();
  await page.reload();
  await expect(page.locator('.admin-course-summary li')).toHaveCount(2);
  await page.screenshot({path:'/tmp/investiq-admin-learning-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('navigation',{name:'Mobile admin navigation'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  await page.screenshot({path:'/tmp/investiq-admin-learning-mobile.png',fullPage:true});

  const context=await browser.newContext();
  try{
    const learner=await context.newPage();
    await verifiedAccount(learner,request,`content-learner-${randomUUID()}@example.com`);
    await learner.goto('/#/academy');
    const card=learner.locator('[data-learning-course]').filter({has:learner.getByRole('heading',{name:title,exact:true})});
    await expect(card).toBeVisible();
    await card.getByRole('link',{name:'Diversification in practice',exact:true}).click();
    await expect(learner.locator('.lessonbody')).toContainText('Review exposure regularly.');
    await learner.getByRole('button',{name:'Enroll to take this quiz',exact:true}).click();
    await learner.getByRole('radio').first().check();
    await learner.getByRole('button',{name:'Submit quiz',exact:true}).click();
    await expect(learner.getByText('Quiz passed · 1/1 correct · 60 XP awarded',{exact:true})).toBeVisible();
    await learner.goto('/#/admin/courses');
    await expect(learner.getByRole('heading',{name:'Admin access required',exact:true})).toBeVisible();
    await expect(learner.getByRole('link',{name:'Add course',exact:true})).toHaveCount(0);
  }finally{await context.close();}
  expect(errors).toEqual([]);
});
