import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { verifiedAccount } from './helpers.js';

async function picture(page) {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 600; canvas.height = 400;
    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 600, 400);
    gradient.addColorStop(0, '#f04444'); gradient.addColorStop(1, '#286beb');
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 600, 400);
    ctx.fillStyle = '#fff'; ctx.fillRect(100, 40, 80, 120);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  return { name: 'portrait.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
}

for (const width of [1280, 390]) {
  test(`profile photos upload, edit, persist and remove at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await verifiedAccount(page, request, `photo-${randomUUID()}@example.com`);
    await page.goto('/#/profile/details');
    await page.getByLabel('Display name', { exact: true }).fill('Unsaved profile edit');
    const file = await picture(page);
    const chooserPromise = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: 'Upload photo', exact: true }).click();
    await (await chooserPromise).setFiles(file);
    const editor = page.getByRole('dialog', { name: 'Edit profile photo', exact: true });
    await expect(editor).toBeVisible();
    const initial = await editor.locator('canvas').evaluate(node => node.toDataURL());
    await editor.getByRole('slider', { name: 'Photo zoom', exact: true }).focus();
    await page.keyboard.press('End');
    await editor.getByRole('button', { name: 'Rotate photo', exact: true }).click();
    await editor.locator('canvas').focus();
    await page.keyboard.press('ArrowLeft');
    expect(await editor.locator('canvas').evaluate(node => node.toDataURL())).not.toBe(initial);
    await page.screenshot({ path: `/tmp/investiq-photo-editor-${width}.png` });
    await editor.getByRole('button', { name: 'Save photo', exact: true }).click();
    await expect(editor).toBeHidden();
    await expect(page.getByLabel('Display name', { exact: true })).toHaveValue('Unsaved profile edit');
    await expect(page.locator('.appbar [data-account-photo]')).toBeVisible();
    await expect.poll(() => page.locator('.appbar [data-account-photo]').evaluate(node => node.complete && node.naturalWidth === 256)).toBe(true);
    const first = await page.evaluate(async () => (await (await fetch('/api/v1/me')).json()).photo_version);
    await page.reload();
    await expect(page.locator('.appbar [data-account-photo]')).toBeVisible();
    await page.getByRole('button', { name: 'Edit photo', exact: true }).click();
    await expect(editor).toBeVisible();
    await editor.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect(await page.evaluate(async () => (await (await fetch('/api/v1/me')).json()).photo_version)).toBe(first);
    await page.getByRole('button', { name: 'Edit photo', exact: true }).click();
    await editor.getByRole('button', { name: 'Rotate photo', exact: true }).click();
    await editor.getByRole('button', { name: 'Save photo', exact: true }).click();
    await expect(editor).toBeHidden();
    const second = await page.evaluate(async () => (await (await fetch('/api/v1/me')).json()).photo_version);
    expect(second).not.toBe(first);
    await page.getByRole('link', { name: '← Your profile', exact: true }).click();
    await expect(page.locator('.account-identity [data-account-photo]')).toBeVisible();
    await page.getByRole('button', { name: 'Remove photo', exact: true }).click();
    await expect(page.locator('[data-account-photo]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Edit photo', exact: true })).toBeHidden();
    await page.reload();
    await expect(page.locator('[data-account-photo]')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

test('invalid files and failed saves preserve the current photo and editable crop', async ({ page, request }) => {
  await verifiedAccount(page, request, `photo-error-${randomUUID()}@example.com`);
  await page.goto('/#/profile');
  const input = page.locator('[data-photo-file]');
  await input.setInputFiles({ name: 'bad.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg/>') });
  await expect(page.locator('.photo-notice')).toContainText('Choose a JPG, PNG, or WebP photo.');
  const editor = page.getByRole('dialog', { name: 'Edit profile photo', exact: true });
  await expect(editor).toBeHidden();
  await input.setInputFiles({ name: 'too-large.png', mimeType: 'image/png', buffer: Buffer.alloc(5 * 1024 * 1024 + 1) });
  await expect(page.locator('.photo-notice')).toContainText('smaller than 5 MB');
  await input.setInputFiles(await picture(page));
  await expect(editor).toBeVisible();
  await page.route('**/api/v1/me/photo', route => route.request().method() === 'PUT' ? route.fulfill({ status: 503, json: { error: { message: 'Photo saving temporarily unavailable' } } }) : route.continue());
  await editor.getByRole('button', { name: 'Save photo', exact: true }).click();
  await expect(editor.getByRole('status')).toContainText('Photo saving temporarily unavailable');
  await expect(editor).toBeVisible();
  await expect(editor.getByRole('button', { name: 'Save photo', exact: true })).toBeEnabled();
  await page.unroute('**/api/v1/me/photo');
  await editor.getByRole('button', { name: 'Save photo', exact: true }).click();
  await expect(editor).toBeHidden();
  await expect(page.locator('.appbar [data-account-photo]')).toBeVisible();
});
