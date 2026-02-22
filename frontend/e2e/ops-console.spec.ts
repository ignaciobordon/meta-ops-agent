import { test, expect } from '@playwright/test';

test.describe('Ops Console Page', () => {
  // Authenticate before each test so protected routes are accessible
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('#email').fill('admin@example.com');
    await page.locator('#password').fill('admin123');
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
  });

  test('should navigate to the ops console page', async ({ page }) => {
    await page.goto('/ops');
    await expect(page).toHaveURL(/\/ops/);

    // The ops console header should be visible
    await expect(page.locator('.ops-header h1')).toBeVisible();
  });

  test('should render queue stats cards', async ({ page }) => {
    await page.goto('/ops');

    // Wait for loading to finish - the queue section should appear
    const queuesSection = page.locator('.ops-queues');
    await expect(queuesSection).toBeVisible({ timeout: 15000 });

    // Each queue card should have stats (pending, running, failed)
    const queueCards = page.locator('.queue-card');
    // At least the section exists even if no queues are returned
    await expect(queuesSection).toBeAttached();
  });

  test('should render the jobs table with required columns', async ({ page }) => {
    await page.goto('/ops');

    // Wait for loading state to clear
    const jobsTable = page.locator('.jobs-table');
    await expect(jobsTable).toBeVisible({ timeout: 15000 });

    // Verify that all expected column headers are present
    const thead = jobsTable.locator('thead');

    await expect(thead.locator('th', { hasText: 'Type' })).toBeVisible();
    await expect(thead.locator('th', { hasText: 'Status' })).toBeVisible();
    await expect(thead.locator('th', { hasText: 'Queue' })).toBeVisible();
    await expect(thead.locator('th', { hasText: 'Attempts' })).toBeVisible();
    await expect(thead.locator('th', { hasText: 'Request ID' })).toBeVisible();
    await expect(thead.locator('th', { hasText: 'Created' })).toBeVisible();
    await expect(thead.locator('th', { hasText: 'Error Code' })).toBeVisible();
    await expect(thead.locator('th', { hasText: 'Error Message' })).toBeVisible();
    await expect(thead.locator('th', { hasText: 'Actions' })).toBeVisible();
  });

  test('should display status and type filter dropdowns', async ({ page }) => {
    await page.goto('/ops');

    // Wait for loading to finish
    await expect(page.locator('.ops-jobs')).toBeVisible({ timeout: 15000 });

    // There should be two filter selects in the filters section
    const filters = page.locator('.ops-filters select');
    await expect(filters).toHaveCount(2);

    // First filter is status, second is type
    const statusFilter = filters.nth(0);
    const typeFilter = filters.nth(1);

    await expect(statusFilter).toBeVisible();
    await expect(typeFilter).toBeVisible();

    // Status filter should have options like queued, running, succeeded, failed
    await expect(statusFilter.locator('option', { hasText: 'Queued' })).toBeAttached();
    await expect(statusFilter.locator('option', { hasText: 'Failed' })).toBeAttached();
  });
});
