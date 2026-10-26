import { test, expect } from '@playwright/test';

const items = [
  'Indian markets steady as investors track corporate earnings',
  'Banking shares lead sector gains in the afternoon session',
  'Rupee holds its range as traders monitor global cues',
  'Institutional flows remain in focus for domestic equities',
  'Energy stocks in focus as crude prices shift',
].map((title, i) => ({
  id: String(i), title, source: 'The Economic Times',
  url: `https://economictimes.indiatimes.com/markets/test-${i}.cms`,
  published_at: '2026-10-26T08:30:00Z',
}));

async function prepare(page, news = {}) {
  let reads = 0;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let json = { items: [], next_cursor: null };
    if (path === '/api/v1/me') json = {
      id: 'test-account', name: 'Seebu', email_verified: true, role: 'learner',
      preferences: {}, privacy: {}, onboarding: { answers: {}, version: 'test' },
    };
    else if (path === '/api/v1/onboarding/questions') json = { version: 'test', questions: [] };
    else if (path === '/api/v1/me/dashboard') json = {
      items: [], joined_count: 0, active_count: 0, completed_count: 0, wins: 0,
      latest_snapshot_value: null, latest_snapshot_pnl: null, valued_count: 0,
      submitted_count: 0, all_valued_current: true,
    };
    else if (path === '/api/v1/market/status') json = { mode: 'yahoo', benchmark_id: 'nifty' };
    else if (path === '/api/v1/quotes') json = { items: [{
      open: '22524.4', close: '22753.2', day_change_pct: '1.02',
      session_date: '2026-10-26', freshness: 'current_eod',
    }] };
    else if (path === '/api/v1/market/news') {
      reads++;
      if (news.fail) return route.fulfill({ status: 503, json: { error: { message: 'Unavailable' } } });
      json = { items, status: 'ready', updated_at: '2026-10-26T08:45:00Z', ...news };
    }
    await route.fulfill({ json });
  });
  if (page.url().endsWith('/#/home')) await page.reload();
  else await page.goto('/#/home');
  await expect(page.getByRole('region', { name: 'Nifty 50 market overview' })).toBeVisible();
  return () => reads;
}

test('home rotates every three seconds; portfolio shares five original article links', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const reads = await prepare(page);
  const carousel = page.getByRole('region', { name: 'Market news highlights' });
  await expect(carousel.locator('h3')).toContainText(items[0].title);
  await expect(carousel.locator('h3 a')).toHaveAttribute('href', items[0].url);
  const overview = page.getByRole('region', { name: 'Nifty 50 market overview' });
  await expect(overview.locator('.market-index-level')).toContainText('22,753.2');
  await expect(overview.locator('.market-day-change')).toHaveClass(/is-up/);
  await page.mouse.move(0, 0);
  await page.clock.install();
  await page.clock.runFor(3100);
  await expect(carousel.locator('h3')).toContainText(items[1].title);
  await carousel.getByRole('button', { name: 'Pause headline rotation' }).click();
  await page.mouse.move(0, 0);
  await page.clock.runFor(6200);
  await expect(carousel.locator('h3')).toContainText(items[1].title);
  await carousel.getByRole('button', { name: 'Show headline 5', exact: true }).click();
  await expect(carousel.locator('h3')).toContainText(items[4].title);
  await page.screenshot({ path: '/tmp/investiq-news-desktop.png', fullPage: true });
  await page.evaluate(() => { location.hash = '/portfolio'; });
  const list = page.getByRole('region', { name: 'Top five market news' });
  await expect(list.locator('h3 a')).toHaveCount(5);
  for (let i = 0; i < items.length; i++) {
    const link = list.locator('h3 a').nth(i);
    await expect(link).toHaveAttribute('href', items[i].url);
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  }
  expect(reads()).toBe(1);
  await page.clock.runFor(3100);
  await expect(list.locator('h3 a')).toHaveCount(5);
  expect(errors).toEqual([]);
});

test('mobile layout keeps headlines readable without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await prepare(page);
  const carousel = page.getByRole('region', { name: 'Market news highlights' });
  await expect(carousel.locator('h3')).toContainText(items[0].title);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/investiq-news-mobile.png', fullPage: true });
});

test('headline selection crossfades without moving the card and respects reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await prepare(page);
  const carousel = page.getByRole('region', { name: 'Market news highlights' });
  await expect(carousel.locator('h3')).toContainText(items[0].title);
  await page.evaluate(() => document.fonts.ready);
  const height = await carousel.evaluate(node => node.offsetHeight);
  await carousel.getByRole('button', { name: 'Show headline 2', exact: true }).click();
  const transition = await carousel.evaluate(node => {
    const slides = [...node.querySelectorAll('.news-slide')];
    for (const slide of slides) {
      for (const animation of slide.getAnimations()) {
        animation.pause();
        animation.currentTime = 225;
      }
    }
    return slides.map(slide => ({ opacity: Number(getComputedStyle(slide).opacity), text: slide.textContent }));
  });
  expect(transition).toHaveLength(2);
  expect(transition[0].text).toContain(items[1].title);
  expect(transition[1].text).toContain(items[0].title);
  for (const slide of transition) expect(slide.opacity).toBeCloseTo(0.5, 1);
  expect(await carousel.evaluate(node => node.offsetHeight)).toBe(height);
  await expect(carousel.getByRole('link', { name: 'Read the original story', exact: false })).toHaveCount(1);
  await carousel.evaluate(node => node.querySelectorAll('.news-slide').forEach(slide => slide.getAnimations().forEach(animation => animation.finish())));
  await expect(carousel.locator('.news-slide-outgoing')).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await carousel.getByRole('button', { name: 'Show headline 3', exact: true }).click();
  await expect(carousel.locator('h3')).toContainText(items[2].title);
  await expect(carousel.locator('.news-slide')).toHaveCount(1);
  expect(await carousel.locator('.news-slide').evaluate(node => node.getAnimations().length)).toBe(0);
});

for (const width of [1280, 900, 390]) {
  test(`headline changes keep the Home layout stationary at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const varied = items.map((item, i) => ({
      ...item,
      title: i % 2 ? 'Markets rise' : 'Investors review company earnings, industry developments and changing global market conditions before the next trading session '.repeat(4),
      source: i % 2 ? 'ET' : 'A publisher with a considerably longer name than the other headlines',
    }));
    await prepare(page, { items: varied });
    const carousel = page.getByRole('region', { name: 'Market news highlights' });
    await expect(carousel.locator('h3')).toContainText(varied[0].title);
    await page.evaluate(() => document.fonts.ready);
    const bounds = () => carousel.evaluate(node => {
      const grid = node.closest('.market-context-grid');
      return {
        card: node.getBoundingClientRect().height,
        grid: grid.getBoundingClientRect().height,
        following: grid.nextElementSibling?.getBoundingClientRect().top + scrollY,
        controls: node.querySelector('.news-controls').getBoundingClientRect().top + scrollY,
      };
    });
    const initial = await bounds();
    expect(Number.isFinite(initial.following)).toBe(true);
    await page.mouse.move(0, 0);
    await page.clock.install();
    await page.clock.runFor(3100);
    await expect(carousel.locator('h3')).toContainText(varied[1].title);
    expect(await bounds()).toEqual(initial);
    for (const number of [3, 4, 5, 1]) {
      await carousel.getByRole('button', { name: `Show headline ${number}`, exact: true }).click();
      await expect(carousel.locator('h3')).toContainText(varied[number - 1].title);
      expect(await bounds()).toEqual(initial);
      await expect(carousel.getByRole('link', { name: 'Read the original story', exact: false })).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test('empty, stale and failed news keep the overview usable', async ({ page }) => {
  await prepare(page, { items: [], next_refresh_at: '2026-10-27T03:45:00Z' });
  const carousel = page.getByRole('region', { name: 'Market news highlights' });
  await expect(carousel).toContainText('Headlines will appear after the next news refresh.');
  await expect(carousel).toContainText('Next scheduled update:');
  await expect(carousel.locator('h3 a')).toHaveCount(0);
  await page.unroute('**/api/v1/**');
  await prepare(page, { status: 'stale' });
  await expect(carousel).toContainText('Saved headlines');
  await expect(carousel.locator('h3 a')).toHaveCount(1);
  await page.unroute('**/api/v1/**');
  await prepare(page, { fail: true });
  await expect(carousel).toContainText('Market news is temporarily unavailable.');
  await expect(page.getByRole('region', { name: 'Nifty 50 market overview' })).toContainText('22,753.2');
});
