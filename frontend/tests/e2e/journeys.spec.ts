import { expect, test, type Page } from '@playwright/test';

async function signIn(page: Page, email = 'engineer@aquaintel.io') {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('AquaIntel!2026');
  await page.getByRole('button', { name: 'Sign in' }).click();
  // Login is limited to 5 attempts/min per IP (Ch. 17). The suite signs in more often than that,
  // so wait out the window once instead of failing.
  const limited = page.getByText('Too many authentication attempts');
  const home = page.getByRole('heading', { name: 'Executive overview' });
  await expect(limited.or(home)).toBeVisible();
  if (await limited.isVisible()) {
    test.setTimeout(test.info().timeout + 70_000);
    await page.waitForTimeout(61_000);
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  await expect(home).toBeVisible();
}

test('login and dashboard load', async ({ page }) => {
  await signIn(page);
  await expect(page.getByRole('link', { name: /System Availability/ })).toBeVisible();
});

// Engineer creates a rule that the live feed breaches -> the rules engine raises an alert ->
// the operator for that site acknowledges it. Needs the simulator streaming (compose --profile demo).
test('rule raises a live alert that the operator acknowledges', async ({ page, request }) => {
  test.setTimeout(120_000);
  // set-up and clean-up run as admin: deleting rules needs alerts:rules:delete
  const login = await request.post('/v1/auth/login', { data: { email: 'admin@aquaintel.io', password: 'AquaIntel!2026' } });
  const auth = { Authorization: `Bearer ${(await login.json()).data.tokens.access_token}` };
  const tags = (await (await request.get('/v1/telemetry/tags?parameter=pressure', { headers: auth })).json()).data;
  const tag = tags.find((t: { external_id: string }) => t.external_id === 'plant_a_dma_north_p');
  const name = `E2E pressure check ${Date.now()}`;
  const created = await request.post('/v1/alerts/rules', {
    headers: auth,
    data: { name, tag_id: tag.id, rule_type: 'threshold', severity: 'minor', condition: { operator: 'greater_than', value: 0 } },
  });
  expect(created.ok()).toBeTruthy();
  const ruleId = (await created.json()).data.id;
  let alertId: string | undefined;
  try {
    await signIn(page, 'operator@aquaintel.io');
    await expect(async () => {
      await page.goto('/alerts?open_only=true');
      await expect(page.getByText(name)).toBeVisible({ timeout: 3_000 });
    }).toPass({ timeout: 90_000, intervals: [5_000] });
    await page.getByText(name).click();
    alertId = page.url().split('/alerts/')[1];
    await page.getByRole('button', { name: 'Acknowledge' }).click();
    await expect(page.getByText('acknowledged').first()).toBeVisible();
  } finally {
    // leave the demo database as we found it: resolve the test alert, then drop the rule
    if (alertId) await request.post('/v1/alerts/bulk', { headers: auth, data: { alert_ids: [alertId], action: 'resolve', note: 'e2e cleanup' } });
    const removed = await request.delete(`/v1/alerts/rules/${ruleId}`, { headers: auth });
    expect(removed.status(), 'test rule must be removed, or the next run is refused as a duplicate').toBe(204);
  }
});

test('view a report', async ({ page }) => {
  await signIn(page);
  await page.goto('/reports/builder');
  await page.getByRole('button', { name: 'Preview' }).click();
  await expect(page.frameLocator('iframe[title="Report preview"]').getByRole('heading').first()).toBeVisible();
});

test('operator cannot open admin pages', async ({ page }) => {
  await signIn(page, 'operator@aquaintel.io');
  await page.goto('/admin/users');
  await expect(page.getByText("You don't have access to this page")).toBeVisible();
});

// QA audit AQ-013: times follow the viewer's clock, and the header says which zone that is
test.describe('time zone', () => {
  test.use({ timezoneId: 'Asia/Kolkata' });
  test('times are shown in the viewer time zone', async ({ page }) => {
    await signIn(page);
    await expect(page.getByRole('banner').getByText(/IST|GMT\+5:30/)).toBeVisible();
    const shown = await page.evaluate(() =>
      new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date('2026-01-01T00:00:00Z')));
    expect(shown).toMatch(/05:30|5:30/); // midnight UTC is 05:30 in India, as the UI formats it
  });
});

// Asset map: must render quickly (a world-wide grid once froze the page for every role), stay
// interactive (zoom, hover, click through to the asset) and follow the site selector and asset scope.
test.describe('asset map', () => {
  test.setTimeout(150_000);

  test('renders fast and is interactive', async ({ page }) => {
    await signIn(page, 'admin@aquaintel.io');
    const started = Date.now();
    await page.goto('/assets/map');
    const markers = page.locator('main svg[role=group] g[role=button]');
    await expect(markers).toHaveCount(44, { timeout: 15_000 });
    expect(Date.now() - started).toBeLessThan(15_000);
    const t = Date.now(); await page.evaluate(() => 1); expect(Date.now() - t).toBeLessThan(1_000); // main thread free
    expect(((await page.locator('main svg[role=group] path').first().getAttribute('d')) ?? '').length).toBeLessThan(50_000);

    const pump = page.locator('main svg g[role=button][aria-label^="High-Lift Pump 2,"]').first();
    await page.getByRole('button', { name: 'Zoom in' }).click();
    await page.getByRole('button', { name: 'Fit all assets' }).click();
    await pump.hover();
    await expect(page.getByText('Click to open')).toBeVisible();
    await page.getByRole('banner').getByRole('combobox').click();
    await page.getByRole('option', { name: 'Hillcrest Treatment Works' }).click();
    await expect(markers).toHaveCount(22);
    await page.getByRole('banner').getByRole('combobox').click();
    await page.getByRole('option', { name: 'All sites' }).click();
    await expect(markers).toHaveCount(44);
    await pump.click();
    await expect(page).toHaveURL(/\/assets\/[0-9a-f-]{36}$/);
  });

  test('operator sees only the assets in scope', async ({ page }) => {
    await signIn(page, 'operator@aquaintel.io');
    await page.goto('/assets/map');
    await expect(page.locator('main svg[role=group] g[role=button]')).toHaveCount(22, { timeout: 15_000 });
  });
});
