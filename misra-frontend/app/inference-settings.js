/* AI setup is device-local; accepted jobs retain their own server-side snapshot. */
(function () {
  'use strict';
  const scope = MisraWorkspace.page, $ = id => document.getElementById(id);
  const picker = $('inference-profile'), save = $('save-inference-profile');
  const options = [...picker.querySelectorAll('input[type=radio]')];
  const optionIds = new Set(options.map(option => option.value));
  const check = $('check-local-model');
  const roles = [['ocr', 'Page reading'], ['setup', 'Guide drafting'], ['grading', 'Grading proposal'], ['verification', 'Verification check']];
  const providerNames = new Map([['gemini', 'Google Gemini'], ['openrouter_free', 'OpenRouter Free'], ['local', 'Local']]);
  let dirty = false, busy = false, checking = false, loaded = false, profiles = [], activeProfile;
  const translate = value => window.MisraLocale?.text(value) || value;
  const escaped = value => MisraUI.escapeHTML(value);
  const status = message => { $('inference-save-status').textContent = message; };
  const selectedProfile = () => options.find(option => option.checked)?.value;

  function render() {
    const active = MisraAPI.inferenceProfile();
    activeProfile = active;
    const selected = profiles.find(item => item.id === selectedProfile());
    const local = selected.id !== 'configured';
    $('inference-active-name').textContent = translate(profiles.find(item => item.id === active).label);
    $('inference-active').hidden = false;
    $('inference-models').hidden = false;
    $('inference-local-notes').hidden = !local;
    $('inference-local-capability').textContent = local ? translate(selected.tasks.vision_grading
      ? 'Qwen Vision reads pages and handles grading and verification when images are included. Qwen3 Instruct handles text-only work. All model calls stay local.'
      : selected.text_only_grading
      ? 'Local Qwen uses text. Use a vision-capable setup when grading requires images. Gemini page reading may incur provider charges.'
      : 'Local Qwen Vision can inspect images during grading and verification. Gemini page reading may incur provider charges.') : '';
    $('native-ai-status').textContent = selected.verification_enabled ? '' :
      translate('Verification is disabled for this setup.');
    const shownRoles=selected.tasks.vision_grading ? [...roles,['vision_grading','Image grading & verification']] : roles;
    $('native-ai-agents').innerHTML = shownRoles.map(([key, name]) => {
      const task = selected.tasks[key];
      const model = key === 'verification' && !selected.verification_enabled
        ? escaped(translate('Disabled'))
        : `<bdi>${escaped(task.model)}</bdi> <span><bdi>${escaped(translate(providerNames.get(task.provider) || task.provider))}</bdi></span>`;
      return `<div><dt data-i18n>${escaped(name)}</dt><dd>${model}</dd></div>`;
    }).join('');
    save.disabled = busy || !dirty;
    check.disabled = busy || checking;
  }
  async function load() {
    if (busy || scope.signal.aborted) return;
    busy = true; picker.disabled = save.disabled = check.disabled = true;
    $('inference-error').textContent = ''; $('reload-inference-profile').hidden = true;
    $('native-ai-status').textContent = translate('Reading configured AI services…');
    try {
      const data = await MisraAPI.inferenceProfiles();
      if (scope.signal.aborted) return;
      if (!Array.isArray(data?.profiles) || data.profiles.length !== optionIds.size || new Set(data.profiles.map(item => item?.id)).size !== optionIds.size || !data.profiles.every(item =>
        optionIds.has(item?.id) && typeof item.label === 'string' &&
        typeof item.verification_enabled === 'boolean' && typeof item.text_only_grading === 'boolean' &&
        (item.id==='local_qwen_all_v1' ? [...roles,['vision_grading']] : roles)
          .every(([task]) => typeof item.tasks?.[task]?.model === 'string' && typeof item.tasks?.[task]?.provider === 'string'))) {
        throw Error('AI services could not be confirmed. Reload or restart the API with the updated code.');
      }
      const active = MisraAPI.inferenceProfile();
      if (!data.profiles.some(item => item.id === active)) throw Error('The saved AI setup is unavailable.');
      profiles = data.profiles;
      for (const option of options) option.checked = option.value === active;
      loaded = true; dirty = false; status('');
    } catch (error) {
      if (scope.signal.aborted) return;
      loaded = false; $('inference-error').textContent = error.message;
      $('native-ai-status').textContent = '';
      $('inference-active').hidden = $('inference-models').hidden = $('inference-local-notes').hidden = true;
      $('reload-inference-profile').hidden = false;
    } finally {
      busy = false;
      if (!scope.signal.aborted && loaded) {
        picker.disabled = false;
        render();
      }
    }
  }
  scope.listen(picker, 'change', () => {
    dirty = selectedProfile() !== MisraAPI.inferenceProfile();
    $('inference-error').textContent = '';
    $('local-model-status').textContent = '';
    status(dirty ? 'Unsaved AI setup. Save to use it for new requests.' : '');
    render();
  });
  scope.listen($('inference-settings-form'), 'submit', event => {
    event.preventDefault(); if (busy || !loaded || !dirty) return;
    $('inference-error').textContent = '';
    try { MisraAPI.setInferenceProfile(selectedProfile()); dirty = false; render(); status('AI setup saved on this browser. Existing jobs and grades stay unchanged.'); }
    catch (_) { dirty = true; $('inference-error').textContent = translate('AI setup was not saved. Your selection is still here. Allow browser storage, then retry Save AI setup.'); }
  });
  scope.listen($('reload-inference-profile'), 'click', async () => { if (!dirty || await MisraWorkspace.confirm('Discard the unsaved AI setup and reload?')) load(); });
  scope.listen(check, 'click', async () => {
    if (checking) return;
    const profile = selectedProfile();
    checking = true; check.disabled = true;
    $('local-model-status').textContent = translate('Checking local Ollama; no inference is started…');
    try {
      const result = await MisraAPI.checkLocalModel(profile);
      if (scope.signal.aborted || selectedProfile() !== profile) return;
      if (typeof result?.available !== 'boolean' || result.inference_started !== false || typeof result.message !== 'string') throw Error('Local model readiness could not be confirmed. Retry the check.');
      $('local-model-status').textContent = translate(result.message);
    } catch (error) { if (!scope.signal.aborted && selectedProfile() === profile) $('local-model-status').textContent = error.message; }
    finally { checking = false; if (!scope.signal.aborted) check.disabled = busy || !loaded; }
  });
  scope.guard(() => false, () => dirty);
  scope.listen(window, 'beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  scope.listen(window, 'misra:language', () => { if (loaded) render(); });
  scope.listen(window, 'storage', () => {
    if (!loaded || busy) return;
    const active = MisraAPI.inferenceProfile();
    if (active === activeProfile) return;
    if (!dirty) {
      for (const option of options) option.checked = option.value === active;
      $('local-model-status').textContent = '';
    }
    dirty = selectedProfile() !== active;
    if (!dirty) $('inference-error').textContent = '';
    status(dirty ? 'Unsaved AI setup. Save to use it for new requests.' : '');
    render();
  });
  MisraApp.ready.then(user => {
    if (user.must_change_password) {
      $('native-ai-status').textContent = translate('Change your password before continuing.');
      return;
    }
    return load();
  }).catch(() => {});
})();
