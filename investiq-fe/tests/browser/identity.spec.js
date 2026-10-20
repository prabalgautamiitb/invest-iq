import { randomUUID } from 'node:crypto';
import { test, expect } from '@playwright/test';

const password = 'browser test password 93';
const address = () => `browser-${randomUUID()}@example.com`;

async function signUp(page, email) {
  await page.goto('/#/signup');
  await page.getByLabel('Full name').fill('Browser Learner');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page).toHaveURL(/#\/onboarding$/);
  await expect(page.getByText('Step 1 of 5', { exact: true })).toBeVisible();
}

async function mailLink(request, email, subject) {
  let id;
  await expect.poll(async () => {
    const response = await request.get('http://127.0.0.1:8025/api/v1/search', {
      params: { query: `to:${email}` },
    });
    const data = await response.json();
    id = data.messages?.find(m => m.Subject.includes(subject))?.ID;
    return Boolean(id);
  }).toBe(true);
  const message = await (await request.get(`http://127.0.0.1:8025/api/v1/message/${id}`)).json();
  return message.Text.match(/http:\/\/127\.0\.0\.1:5174\/[^\s]+/)[0];
}

async function me(page) {
  return page.evaluate(async () => (await fetch('/api/v1/me', { credentials: 'include' })).json());
}

test('signup, onboarding, persistence, verification, recovery and revocation', async ({ page, request }) => {
  const email = address();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await signUp(page, email);
  for (let i = 0; i < 5; i++) {
    await page.locator('.answer').first().click();
    await page.getByRole('button', { name: i === 4 ? 'Reveal my learning path' : 'Continue', exact: true }).click();
  }
  await expect(page.getByRole('heading', { name: 'Foundation Explorer' })).toBeVisible();
  await expect.poll(async () => (await me(page)).onboarding?.experience).toBe('beginner');
  await page.goto('/#/settings');
  await page.getByLabel('Display name').fill('Persistent Learner');
  await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
  await expect.poll(async () => (await me(page)).name).toBe('Persistent Learner');
  await page.getByRole('switch', { name: 'Community replies', exact: true }).click();
  await expect(page.getByRole('switch', { name: 'Community replies', exact: true })).toHaveAttribute('aria-checked', 'true');
  await page.reload();
  await expect(page.getByLabel('Display name')).toHaveValue('Persistent Learner');
  await expect(page.getByRole('switch', { name: 'Community replies', exact: true })).toHaveAttribute('aria-checked', 'true');
  expect(await page.evaluate(() => document.cookie)).not.toContain('investiq_dev_session');

  await page.goto(await mailLink(request, email, 'Verify'));
  await page.getByRole('button', { name: 'Verify email', exact: true }).click();
  await expect.poll(async () => (await me(page)).email_verified).toBe(true);
  expect(page.url()).not.toContain('token=');
  await page.goto('/#/settings');
  await page.locator('.sidebar [data-action="logout"]').click();
  await expect(page).toHaveURL(/#\/login$/);
  await page.goto('/#/reset-password');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByRole('button', { name: 'Request reset link', exact: true }).click();
  await expect(page.locator('[data-form-status]')).toContainText('If the account is eligible');
  await page.goto(await mailLink(request, email, 'Reset'));
  await page.getByLabel('New password', { exact: true }).fill('changed browser password 27');
  await page.getByLabel('Confirm password', { exact: true }).fill('changed browser password 27');
  await page.getByRole('button', { name: 'Change password', exact: true }).click();
  await expect(page).toHaveURL(/#\/login$/);
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password', { exact: true }).fill('changed browser password 27');
  await page.getByRole('button', { name: 'Enter workspace' }).click();
  await expect(page).toHaveURL(/#\/dashboard$/);
  await page.goto('/#/settings');
  await page.getByRole('button', { name: 'Security & password' }).click();
  await page.getByRole('button', { name: 'Revoke and sign out' }).click();
  await expect(page).toHaveURL(/#\/login$/);
  expect(errors).toEqual([]);
});

test('demo activity stays local and login failures remain visible', async ({ page }) => {
  const fixture = { referenceVersion: 2, name: 'Demo Person', answers: [3, 3, 3, 3, 3], onboard: true, coins: 99999, completed: ['essentials'] };
  await page.addInitScript(value => localStorage.setItem('investiq-demo-v1', JSON.stringify(value)), fixture);
  await signUp(page, address());
  const profile = await me(page);
  expect(profile.onboarding).toBeNull();
  expect(profile.name).toBe('Browser Learner');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('investiq-demo-v1')))).toEqual(fixture);
  await page.goto('/#/settings');
  await page.locator('.sidebar [data-action="logout"]').click();
  await page.getByLabel('Email address').fill(address());
  await page.getByLabel('Password', { exact: true }).fill('wrong password');
  await page.getByRole('button', { name: 'Enter workspace' }).click();
  await expect(page.locator('[data-form-status]')).toContainText('Invalid email or password');
  await expect(page).toHaveURL(/#\/login$/);
});
