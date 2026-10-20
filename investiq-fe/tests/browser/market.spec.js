import { test, expect } from '@playwright/test';

test('backend catalogue, server filters, pagination and timestamped prices', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/portfolio');
  await expect(page.locator('#market-status')).toContainText('Synthetic EOD market data');
  await expect(page.locator('#market-status')).toContainText('investiq-synthetic');
  await expect(page.locator('#market-status')).toContainText('2026-10-16');
  await expect(page.locator('#stockrows .stockrow')).toHaveCount(8);
  await page.getByRole('button', { name: 'Load more instruments' }).click();
  await expect(page.locator('#stockrows .stockrow')).toHaveCount(16);
  const search = page.waitForResponse(response => response.url().includes('/instruments?') && response.url().includes('query=INFY'));
  await page.locator('#stocksearch').fill('INFY');
  await search;
  await expect(page.locator('#stockrows .stockrow')).toHaveCount(1);
  await expect(page.locator('#stockrows')).toContainText('Infosys');
  await expect(page.locator('#stockrows')).toContainText('₹1,874.35');
  await page.locator('#stockrows [data-action="add-stock"]').click();
  await expect(page.locator('#allocations')).toContainText('INFY');
  await page.getByRole('button', { name: 'Quantity', exact: true }).click();
  await page.getByLabel('Infosys quantity', { exact: true }).fill('10');
  await page.getByLabel('Infosys quantity', { exact: true }).dispatchEvent('change');
  await page.locator('#stocksearch').fill('');
  await page.getByRole('button', { name: 'Small Cap', exact: true }).click();
  await expect(page.locator('#stockrows .stockrow')).toHaveCount(4);
  const sector = await page.locator('#sector-select option').evaluateAll(options => options.find(o => o.text === 'IT').value);
  await page.locator('#sector-select').selectOption(sector);
  await expect(page.locator('#stockrows')).toContainText('No instruments match');
  expect(errors).toEqual([]);
});

test('failed quote requests show an error and never fall back to browser prices', async ({ page }) => {
  await page.route('**/api/v1/quotes?*', route => route.fulfill({
    status: 503, contentType: 'application/json',
    body: JSON.stringify({ error: { code: 'provider_unavailable', message: 'Quote service unavailable' } }),
  }));
  await page.goto('/#/portfolio');
  await expect(page.locator('#stockrows')).toContainText('Quote service unavailable');
  await expect(page.locator('#stockrows .stockrow')).toHaveCount(0);
  await expect(page.locator('#stockrows [data-action="add-stock"]')).toHaveCount(0);
  await page.unroute('**/api/v1/quotes?*');
  await page.locator('#stockrows').getByRole('button', { name: 'Retry market data' }).click();
  await expect(page.locator('#stockrows .stockrow')).toHaveCount(8);
});

test('stale fixture prices remain labeled and cannot be selected', async ({ page }) => {
  await page.route('**/api/v1/quotes?*', async route => {
    const response = await route.fetch();
    const body = await response.json();
    body.all_current = false;
    body.items = body.items.map(item => ({ ...item, freshness: 'stale', eligible_for_simulation: false }));
    await route.fulfill({ response, json: body });
  });
  await page.goto('/#/portfolio');
  await expect(page.locator('#market-status')).toContainText('Some quotes are stale or missing');
  await expect(page.locator('#stockrows .stockrow')).toHaveCount(8);
  for (const button of await page.locator('#stockrows [data-action="add-stock"]').all()) await expect(button).toBeDisabled();
});
