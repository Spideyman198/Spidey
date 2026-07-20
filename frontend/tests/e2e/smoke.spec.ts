import { expect, test } from '@playwright/test';

// Smoke e2e: an unauthenticated visit lands on the login screen. The full
// M7–M11 flow specs (create run → approve plan → approve edits → PR, replay,
// memory) run against the fixture-LLM backend in CI where the stack is live.
test('unauthenticated visitors reach the sign-in screen', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();
});
