import { test, expect } from '@playwright/test';

test.describe('Login Page', () => {
  test('should navigate to the login page', async ({ page }) => {
    await page.goto('/login');
    await expect(page).toHaveURL(/\/login/);
    await expect(page.locator('h1')).toHaveText('Meta Ops Agent');
  });

  test('should display email and password inputs', async ({ page }) => {
    await page.goto('/login');

    const emailInput = page.locator('#email');
    const passwordInput = page.locator('#password');

    await expect(emailInput).toBeVisible();
    await expect(emailInput).toHaveAttribute('type', 'email');
    await expect(emailInput).toHaveAttribute('placeholder', 'admin@example.com');

    await expect(passwordInput).toBeVisible();
    await expect(passwordInput).toHaveAttribute('type', 'password');
  });

  test('should display Sign In button', async ({ page }) => {
    await page.goto('/login');

    const signInButton = page.locator('button[type="submit"]');
    await expect(signInButton).toBeVisible();
    await expect(signInButton).toContainText('Sign In');
  });

  test('should redirect to dashboard after valid login', async ({ page }) => {
    await page.goto('/login');

    await page.locator('#email').fill('admin@example.com');
    await page.locator('#password').fill('admin123');
    await page.locator('button[type="submit"]').click();

    // After successful login the app redirects to /dashboard
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
  });

  test('should show an error message for invalid credentials', async ({ page }) => {
    await page.goto('/login');

    await page.locator('#email').fill('wrong@example.com');
    await page.locator('#password').fill('wrongpassword');
    await page.locator('button[type="submit"]').click();

    // The error message container should become visible
    const errorBanner = page.locator('.login-error');
    await expect(errorBanner).toBeVisible({ timeout: 10000 });
  });
});
