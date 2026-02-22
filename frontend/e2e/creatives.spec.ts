import { test, expect } from '@playwright/test';

test.describe('Creatives Page', () => {
  // Authenticate before each test so protected routes are accessible
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#email').fill('admin@example.com');
    await page.locator('#password').fill('admin123');
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
  });

  test('should navigate to the creatives page', async ({ page }) => {
    await page.goto('/creatives');
    await expect(page).toHaveURL(/\/creatives/);
    // Page header should contain the creatives title
    await expect(page.locator('.page-title')).toBeVisible();
  });

  test('should display a Generate button', async ({ page }) => {
    await page.goto('/creatives');

    const generateButton = page.locator('button.btn-primary', { hasText: /generate/i });
    await expect(generateButton).toBeVisible();
  });

  test('should open the Generate Creative modal when clicking the button', async ({ page }) => {
    await page.goto('/creatives');

    // Click the Generate button in the page header
    const generateButton = page.locator('button.btn-primary', { hasText: /generate/i }).first();
    await generateButton.click();

    // The modal overlay should appear
    const modal = page.locator('.modal-overlay');
    await expect(modal).toBeVisible();

    // Modal should contain the title
    await expect(page.locator('.modal-header h2')).toBeVisible();
  });

  test('should have framework and hook_style fields in the modal', async ({ page }) => {
    await page.goto('/creatives');

    // Open the modal
    const generateButton = page.locator('button.btn-primary', { hasText: /generate/i }).first();
    await generateButton.click();

    // Wait for modal to be visible
    await expect(page.locator('.modal-overlay')).toBeVisible();

    // Check for the Copywriting Framework select field
    const frameworkLabel = page.locator('.modal-form label', { hasText: /framework/i });
    await expect(frameworkLabel).toBeVisible();

    // Verify the framework select has expected options (AIDA, PAS, BAB, 4Ps)
    const frameworkSelect = frameworkLabel.locator('..').locator('select');
    await expect(frameworkSelect).toBeVisible();
    await expect(frameworkSelect.locator('option')).toHaveCount(4);

    // Check for the Hook Style select field
    const hookStyleLabel = page.locator('.modal-form label', { hasText: /hook/i });
    await expect(hookStyleLabel).toBeVisible();

    // Verify the hook style select has expected options (Question, Statistic, Story, Bold claim)
    const hookStyleSelect = hookStyleLabel.locator('..').locator('select');
    await expect(hookStyleSelect).toBeVisible();
    await expect(hookStyleSelect.locator('option')).toHaveCount(4);
  });
});
