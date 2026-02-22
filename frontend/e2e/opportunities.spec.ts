import { test, expect } from '@playwright/test';

test.describe('Opportunities Page', () => {
  // Authenticate before each test so protected routes are accessible
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#email').fill('admin@example.com');
    await page.locator('#password').fill('admin123');
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
  });

  test('should navigate to the opportunities page', async ({ page }) => {
    await page.goto('/opportunities');
    await expect(page).toHaveURL(/\/opportunities/);

    // Page header should show the title
    await expect(page.locator('.page-title')).toHaveText('Market Opportunities');
  });

  test('should display the Analyze button', async ({ page }) => {
    await page.goto('/opportunities');

    const analyzeButton = page.locator('button.btn-primary', { hasText: /analyze/i });
    await expect(analyzeButton).toBeVisible();
    await expect(analyzeButton).toContainText('Analyze');
  });

  test('should show polling status after clicking Analyze', async ({ page }) => {
    await page.goto('/opportunities');

    const analyzeButton = page.locator('button.btn-primary', { hasText: /analyze/i });
    await analyzeButton.click();

    // After clicking, the button text should change to indicate analysis is in progress
    // Either the button shows "Analyzing..." or the info banner appears
    const analyzingIndicator = page.locator('text=Analyzing');
    await expect(analyzingIndicator.first()).toBeVisible({ timeout: 10000 });
  });
});
