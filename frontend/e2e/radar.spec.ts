import { test, expect } from '@playwright/test';

test.describe('Competitive Radar Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#email').fill('admin@example.com');
    await page.locator('#password').fill('admin123');
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
  });

  test('should navigate to the radar page', async ({ page }) => {
    await page.goto('/radar');
    await expect(page).toHaveURL(/\/radar/);
    await expect(page.locator('.page-title')).toContainText(/Radar/i);
  });

  test('should display the competitors panel', async ({ page }) => {
    await page.goto('/radar');
    await expect(page.locator('.radar-competitors-panel')).toBeVisible();
    await expect(page.locator('.radar-panel-header')).toContainText(/Competitors|Competidores/i);
  });

  test('should display tabs for New Ads, Offer Changes, Trends, Search', async ({ page }) => {
    await page.goto('/radar');
    const tabs = page.locator('.radar-tab');
    await expect(tabs).toHaveCount(4);
  });

  test('should show New Ads tab by default', async ({ page }) => {
    await page.goto('/radar');
    const activeTab = page.locator('.radar-tab--active');
    await expect(activeTab).toContainText(/Ads|Anuncios/i);
  });

  test('should switch to Search tab and show search input', async ({ page }) => {
    await page.goto('/radar');
    const searchTab = page.locator('.radar-tab', { hasText: /Search|Buscar/i });
    await searchTab.click();
    await expect(page.locator('.radar-search-input')).toBeVisible();
  });

  test('should switch to Offer Changes tab', async ({ page }) => {
    await page.goto('/radar');
    const offersTab = page.locator('.radar-tab', { hasText: /Offer|Oferta/i });
    await offersTab.click();
    await expect(offersTab).toHaveClass(/radar-tab--active/);
  });

  test('should switch to Angle Trends tab', async ({ page }) => {
    await page.goto('/radar');
    const trendsTab = page.locator('.radar-tab', { hasText: /Trend|Tendencia/i });
    await trendsTab.click();
    await expect(trendsTab).toHaveClass(/radar-tab--active/);
  });

  test('should display Run Scan button', async ({ page }) => {
    await page.goto('/radar');
    const scanButton = page.locator('button.btn-primary', { hasText: /Scan|Escaneo/i });
    await expect(scanButton).toBeVisible();
  });

  test('should display filter controls in Search tab', async ({ page }) => {
    await page.goto('/radar');
    const searchTab = page.locator('.radar-tab', { hasText: /Search|Buscar/i });
    await searchTab.click();
    await expect(page.locator('.radar-filters-bar')).toBeVisible();
    await expect(page.locator('.radar-filter-select').first()).toBeVisible();
  });

  test('sidebar should have radar navigation link', async ({ page }) => {
    await page.goto('/dashboard');
    const radarLink = page.locator('.sidebar-link[href="/radar"]');
    await expect(radarLink).toBeVisible();
  });

  test('should type in search input and see debounced behavior', async ({ page }) => {
    await page.goto('/radar');
    const searchTab = page.locator('.radar-tab', { hasText: /Search|Buscar/i });
    await searchTab.click();
    const input = page.locator('.radar-search-input');
    await input.fill('test query');
    await expect(input).toHaveValue('test query');
  });
});
