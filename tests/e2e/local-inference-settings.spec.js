const {test, expect} = require('@playwright/test');
const {localProfile, visionProfile, profileCatalog} = require('./fixtures/inference-profiles');
const {staticWorkspace} = require('./fixtures/static-workspace');
const choice = (page, value) => page.locator(`#inference-profile input[value="${value}"]`);

async function fixture(page, options = {}) {
  const state = {fail: !!options.fail, requests: [], ready: false};
  await staticWorkspace(page);
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({body: ''}));
  await page.route('https://fonts.gstatic.com/**', route => route.abort());
  await page.route('**/api/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace('/api', '');
    state.requests.push({path, method: request.method(), profile: request.headers()['x-misra-inference-profile'],
      checkedProfile: new URL(request.url()).searchParams.get('profile_id')});
    if (path === '/auth/me') return route.fulfill({json: {id: 'synthetic', full_name: 'Synthetic instructor', role: 'teacher'}});
    if (path === '/auth/settings') return route.fulfill({json: {use_marking_preferences: true, has_approved_profile: false, survey_completed: false}});
    if (path === '/inference-profiles') return route.fulfill({status: state.fail ? 503 : 200,
      json: state.fail ? {detail: 'Synthetic configuration unavailable'} : profileCatalog(request.headers()['x-misra-inference-profile'])});
    if (path === '/inference-profiles/local-status') return route.fulfill({json: {available: state.ready, inference_started: false,
      message: state.ready ? 'Local Qwen is installed. This check does not measure grading quality.' : 'Cannot reach local Ollama. Start Ollama on the MISRA computer, then check again.'}});
    return route.fulfill({json: []});
  });
  await page.goto('/app/account.html');
  return state;
}

test('local hybrid is the default and the explicit readiness check never starts inference', async ({page}) => {
  const state = await fixture(page);
  await expect(choice(page, localProfile)).toBeEnabled();
  await expect(choice(page, localProfile)).toBeChecked();
  await expect(page.locator('#save-inference-profile')).toBeDisabled();
  await expect(page.locator('#native-ai-agents')).toBeVisible();
  await expect(page.locator('#native-ai-agents')).toContainText('Guide drafting');
  await expect(page.locator('#native-ai-agents')).toContainText('gemini-2.5-flash');
  await expect(page.locator('#native-ai-agents')).toContainText('qwen3:4b-instruct');
  await expect(page.locator('#ai-settings')).toContainText('Every local grading proposal is sent for instructor review');
  await page.locator('#check-local-model').click();
  await expect(page.locator('#local-model-status')).toContainText('Start Ollama');
  state.ready = true;
  await page.locator('#check-local-model').click();
  await expect(page.locator('#local-model-status')).toContainText('installed');
  expect(state.requests.every(request => request.method === 'GET')).toBeTruthy();
  expect(state.requests.every(request => request.profile === localProfile)).toBeTruthy();
});

test('an unsaved choice does not change requests; saving persists only the selected profile', async ({page}) => {
  const state = await fixture(page);
  await expect(choice(page, localProfile)).toBeEnabled();
  await choice(page, 'configured').check();
  await expect(page.locator('#inference-save-status')).toContainText('Unsaved');
  await expect(page.locator('#inference-active-name')).toContainText('Local Qwen');
  await expect(page.locator('#native-ai-agents')).toContainText('Synthetic assessment model');
  await expect(page.locator('#native-ai-agents')).not.toContainText('qwen3:4b-instruct');
  await page.evaluate(() => MisraAPI.currentUser());
  expect(state.requests.at(-1).profile).toBe(localProfile);
  await page.locator('#save-inference-profile').click();
  await expect(page.locator('#inference-save-status')).toContainText('saved on this browser');
  await page.reload();
  await expect(choice(page, 'configured')).toBeChecked();
  await expect(page.locator('#inference-active-name')).toHaveText('Server configuration');
  expect(state.requests.at(-1).profile).toBe('configured');
  expect(state.requests.every(request => request.method === 'GET')).toBeTruthy();
});

test('the vision option previews and checks its installed model, then persists for new requests', async ({page}) => {
  const state = await fixture(page);
  await expect(choice(page, visionProfile)).toBeEnabled();
  await choice(page, visionProfile).check();
  await expect(page.locator('#inference-local-capability')).toContainText('can inspect images');
  await expect(page.locator('#native-ai-agents')).toContainText('qwen3-vl:4b-instruct');
  await page.locator('#check-local-model').click();
  await expect(page.locator('#local-model-status')).toContainText('Start Ollama');
  expect(state.requests.at(-1)).toMatchObject({profile: localProfile, checkedProfile: visionProfile});
  await page.locator('#save-inference-profile').click();
  await expect(page.locator('#inference-active-name')).toContainText('Local Qwen Vision');
  await page.reload();
  await expect(choice(page, visionProfile)).toBeChecked();
  expect(state.requests.at(-1).profile).toBe(visionProfile);
});

test('the active setup follows a save in another browser tab', async ({page, context}) => {
  await fixture(page);
  await expect(choice(page, localProfile)).toBeChecked();
  const second = await context.newPage();
  await fixture(second);
  await choice(second, 'configured').check();
  await second.locator('#save-inference-profile').click();
  await expect(page.locator('#inference-active-name')).toHaveText('Server configuration');
  await expect(choice(page, 'configured')).toBeChecked();
  await expect(page.locator('#native-ai-agents')).toContainText('Synthetic assessment model');
  await expect(page.locator('#save-inference-profile')).toBeDisabled();
  await second.close();
});

test('storage failure keeps the unsaved choice and protects navigation until retry', async ({page}) => {
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    window.blockInferenceSave = true;
    Storage.prototype.setItem = function (key, value) {
      if (key === 'misra.inference-profile.v1' && window.blockInferenceSave) throw Error('Synthetic storage failure');
      return original.call(this, key, value);
    };
  });
  await fixture(page);
  await expect(choice(page, localProfile)).toBeEnabled();
  await choice(page, 'configured').check();
  await page.locator('#save-inference-profile').click();
  await expect(page.locator('#inference-error')).toContainText('was not saved');
  await expect(choice(page, 'configured')).toBeChecked();
  expect(await page.evaluate(() => MisraAPI.inferenceProfile())).toBe(localProfile);
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('link', {name: 'Dashboard', exact: true}).click();
  await expect(page).toHaveURL(/account.html/);
  await page.evaluate(() => { window.blockInferenceSave = false; });
  await page.locator('#save-inference-profile').click();
  await expect(page.locator('#inference-save-status')).toContainText('saved on this browser');
});

test('configuration failures disable saving and offer a working reload', async ({page}) => {
  const state = await fixture(page, {fail: true});
  await expect(page.locator('#inference-error')).toContainText('Synthetic configuration unavailable');
  await expect(page.locator('#save-inference-profile')).toBeDisabled();
  await expect(choice(page, localProfile)).toBeDisabled();
  await expect(page.locator('#inference-models')).toBeHidden();
  state.fail = false;
  await page.locator('#reload-inference-profile').click();
  await expect(choice(page, localProfile)).toBeEnabled();
  await expect(page.locator('#inference-error')).toBeEmpty();
});

test('AI settings preserve the theme, keyboard controls and RTL without overflow', async ({page}, info) => {
  await fixture(page);
  await expect(choice(page, localProfile)).toBeEnabled();
  const panel = page.locator('#ai-settings');
  await panel.scrollIntoViewIfNeeded();
  await choice(page, localProfile).focus();
  await page.keyboard.press('ArrowDown');
  await expect(choice(page, visionProfile)).toBeChecked();
  await page.keyboard.press('Tab');
  await expect(page.locator('#save-inference-profile')).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  const capture = async variant => {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: `.impeccable/review/local-qwen-settings-${variant}-${info.project.name}.png`, fullPage: true, animations: 'disabled'});
  };
  await capture('light');
  await page.locator('[data-theme-option][value=dark]').check();
  await capture('dark');
  await page.locator('#app-language').click();
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.locator('#save-inference-profile')).toContainText('حفظ');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await capture('rtl');
});
