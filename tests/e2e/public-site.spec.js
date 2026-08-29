const { test, expect } = require('@playwright/test');

test('public site respects the saved appearance setting and exposes a skip link', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('misra-theme', 'dark'));
  await page.goto('/index.html');
  await expect(page.getByRole('heading', { name: /Handwritten exams/ })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  const skip = page.getByRole('link', { name: 'Skip to content' });
  await skip.focus();
  await expect(skip).toBeVisible();

});

test('public mobile menu moves focus and closes with Escape', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'Mobile interaction is covered in the mobile project.');
  await page.goto('/index.html');

  const menu = page.getByRole('button', { name: 'Open menu' });
  await menu.click();
  await expect(menu).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#mobile-navigation').getByRole('link', { name: 'Platform' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  await expect(menu).toBeFocused();
});
