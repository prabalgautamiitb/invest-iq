import { test, expect } from '@playwright/test';

const avatar = page => page.getByRole('button', { name: 'Ask Martin', exact: true });
const chat = page => page.getByRole('dialog', { name: 'Ask Martin', exact: true });
async function drag(page, x, y) {
  const box = await avatar(page).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(x, y, { steps: 12 });
  await page.mouse.up();
}
async function withinScreen(page, node) {
  await expect.poll(async () => {
    const box = await node.boundingBox(), viewport = page.viewportSize();
    return box && box.x >= 0 && box.y >= 0 && box.x + box.width <= viewport.width && box.y + box.height <= viewport.height;
  }).toBe(true);
}

test('Martin moves without opening chat, remembers its position and supports keyboard movement', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/dashboard');
  await expect(avatar(page)).toBeVisible();
  await drag(page, 160, 180);
  await expect(chat(page)).toBeHidden();
  const moved = await avatar(page).boundingBox();
  expect(moved.x + moved.width / 2).toBeCloseTo(160, 0);
  expect(moved.y + moved.height / 2).toBeCloseTo(180, 0);
  await page.evaluate(() => { location.hash = '/academy'; });
  await expect(page.getByRole('heading', { name: 'Your Academy', exact: true })).toBeVisible();
  expect(await avatar(page).boundingBox()).toEqual(moved);
  await page.reload();
  await expect(avatar(page)).toBeVisible();
  expect(await avatar(page).boundingBox()).toEqual(moved);
  await avatar(page).click();
  await expect(chat(page)).toBeVisible();
  await withinScreen(page, chat(page));
  await page.keyboard.press('Escape');
  await expect(avatar(page)).toBeFocused();
  await page.keyboard.press('ArrowRight');
  expect((await avatar(page).boundingBox()).x).toBeCloseTo(moved.x + 16, 0);
  await page.keyboard.press('Shift+ArrowDown');
  expect((await avatar(page).boundingBox()).y).toBeCloseTo(moved.y + 48, 0);
  await page.keyboard.press('Home');
  expect(await page.evaluate(() => localStorage.getItem('investiq-martin-position'))).toBeNull();
  await page.keyboard.press('Enter');
  await expect(chat(page)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await withinScreen(page, avatar(page));
  await withinScreen(page, chat(page));
  const nav = await page.getByRole('navigation', { name: 'Mobile navigation', exact: true }).boundingBox();
  const box = await avatar(page).boundingBox();
  expect(box.y + box.height).toBeLessThan(nav.y);
  expect(errors).toEqual([]);
});

test('touch dragging stays above mobile navigation and a separate tap opens the chat', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const session = await context.newCDPSession(page);
  async function touchDrag(x, y) {
    const box = await avatar(page).boundingBox();
    const start = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [start] });
    for (let step = 1; step <= 8; step++) {
      await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: start.x + (x - start.x) * step / 8, y: start.y + (y - start.y) * step / 8 }] });
    }
    await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  }
  await page.goto('http://127.0.0.1:5174/#/dashboard');
  await expect(avatar(page)).toBeVisible();
  await touchDrag(42, 100);
  await expect(chat(page)).toBeHidden();
  expect((await avatar(page).boundingBox()).x).toBeLessThan(30);
  expect(await page.evaluate(() => scrollY)).toBe(0);
  await avatar(page).tap();
  await expect(chat(page)).toBeVisible();
  await withinScreen(page, chat(page));
  await page.getByRole('button', { name: 'Minimize Ask Martin', exact: true }).tap();
  await touchDrag(388, 842);
  await expect(chat(page)).toBeHidden();
  const nav = await page.getByRole('navigation', { name: 'Mobile navigation', exact: true }).boundingBox();
  const box = await avatar(page).boundingBox();
  expect(box.y + box.height).toBeLessThan(nav.y);
  await page.setViewportSize({ width: 844, height: 390 });
  await withinScreen(page, avatar(page));
  await avatar(page).tap();
  await expect(chat(page)).toBeVisible();
  await withinScreen(page, chat(page));
  expect(errors).toEqual([]);
  await context.close();
});
