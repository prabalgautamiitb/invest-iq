import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

test('mobile search, navigation, learning and account controls stay connected', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await verifiedAccount(page, request, `mobile-account-${randomUUID()}@example.com`);
  await page.goto('/#/contests');
  const bottom = page.getByRole('navigation', { name: 'Mobile navigation', exact: true });
  const workspace = page.getByRole('navigation', { name: 'Contest workspace', exact: true });
  await expect(bottom.getByRole('link')).toHaveText(['Home', 'Contests', 'AI Insights', 'Rewards', 'Community']);
  await expect(page.getByRole('searchbox', { name: 'Search the application', exact: true })).toBeHidden();
  await expect(page.locator('input[type="search"]:visible')).toHaveCount(1);
  await page.getByRole('searchbox', { name: 'Search contests', exact: true }).fill('No matching contest 937');
  await page.getByRole('searchbox', { name: 'Search contests', exact: true }).press('Tab');
  await expect(page.getByText('No contests match.', { exact: false })).toBeVisible();
  await workspace.getByRole('link', { name: 'My Contests', exact: true }).click();
  await expect(page).toHaveURL(/#\/my-contests$/);
  await expect(bottom.getByRole('link', { name: 'Contests', exact: true })).toHaveAttribute('aria-current', 'page');
  await workspace.getByRole('link', { name: 'Portfolio', exact: true }).click();
  await expect(page).toHaveURL(/#\/portfolio$/);
  await bottom.getByRole('link', { name: 'AI Insights', exact: true }).click();
  const learning = page.getByRole('navigation', { name: 'Insights and learning', exact: true });
  await expect(learning).toBeVisible();
  await learning.getByRole('link', { name: 'Learn', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your Academy', exact: true })).toBeVisible();
  await expect(bottom.getByRole('link', { name: 'AI Insights', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('[data-learning-course]').first()).toBeVisible();
  for (const [name, route] of [['Rewards', 'marketplace'], ['Community', 'social'], ['Home', 'dashboard']]) {
    await bottom.getByRole('link', { name, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`#/${route}$`));
    await expect(bottom.getByRole('link', { name, exact: true })).toHaveAttribute('aria-current', 'page');
  }
  await page.locator('.appbar').getByRole('link', { name: 'Your profile', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your profile', exact: true })).toBeVisible();
  await expect(page.locator('[data-learning-course]')).toHaveCount(0);
  await page.getByRole('link', { name: /^Profile information/ }).click();
  await page.getByLabel('Display name', { exact: true }).fill('Mobile Learner');
  await page.getByRole('combobox', { name: 'Weekly learning goal', exact: true }).selectOption('105');
  await expect(page.getByLabel('Email address', { exact: true })).toHaveAttribute('readonly', '');
  await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
  await expect(page.locator('#toast')).toContainText('Profile saved.');
  await page.reload();
  await expect(page.getByLabel('Display name', { exact: true })).toHaveValue('Mobile Learner');
  await expect(page.getByRole('combobox', { name: 'Weekly learning goal', exact: true })).toHaveValue('105');
  await page.getByRole('link', { name: '← Your profile', exact: true }).click();
  await page.getByRole('link', { name: /^Subscription/ }).click();
  await expect(page.getByRole('heading', { name: 'Free simulation access', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Manage billing', exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: '← Your profile', exact: true }).click();
  await page.getByRole('link', { name: /^Settings & privacy/ }).click();
  await page.getByRole('switch', { name: 'Community replies', exact: true }).click();
  await expect(page.getByRole('switch', { name: 'Community replies', exact: true })).toHaveAttribute('aria-checked', 'true');
  await page.reload();
  await expect(page.getByRole('switch', { name: 'Community replies', exact: true })).toHaveAttribute('aria-checked', 'true');
  await page.locator('.appbar').getByRole('link', { name: 'Your profile', exact: true }).click();
  await page.getByRole('button', { name: /Security & password/ }).click();
  await expect(page.getByRole('heading', { name: 'Sessions and password', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Revoke and sign out', exact: true }).click();
  await expect(page).toHaveURL(/#\/login$/);
  expect(errors).toEqual([]);
});

test('account hub stays usable on narrow mobile and desktop without duplicating courses', async ({ page }) => {
  await page.goto('/#/profile');
  for (const width of [360, 600, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole('heading', { name: 'Your profile', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /^Profile information/ })).toBeVisible();
    await expect(page.locator('[data-learning-course]')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `/tmp/investiq-account-${width}.png`, fullPage: true });
  }
  await page.goto('/#/contests');
  await expect(page.getByRole('searchbox', { name: 'Search the application', exact: true })).toBeVisible();
  await expect(page.getByRole('searchbox', { name: 'Search contests', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Contest workspace', exact: true })).toBeHidden();
  await expect(page.getByRole('navigation', { name: 'Application navigation', exact: true }).getByRole('link', { name: 'Learn', exact: true })).toBeVisible();
});
