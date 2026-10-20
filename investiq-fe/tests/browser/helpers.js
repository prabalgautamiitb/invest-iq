import { expect } from '@playwright/test';

export async function verifiedAccount(page, request, email) {
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
