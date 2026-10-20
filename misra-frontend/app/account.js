(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  let busy = false, passwordDirty = false, deletionDirty = false, preferenceDirty = false, settings = null, currentUser = null;
  const hasUnsaved = () => passwordDirty || deletionDirty || preferenceDirty;
  const text = value => window.MisraLocale.text(value);
  function lock(value) {
    busy = value;
    document.querySelectorAll('.settings-content button,.settings-content input').forEach(el => el.disabled = value);
    if (!settings) $('use-marking-preferences').disabled = true;
  }
  function showSettings(value, saved = false) {
    settings = MisraMarkingProfile.validate(value);
    $('use-marking-preferences').checked = settings.use_marking_preferences;
    $('use-marking-preferences').disabled = false;
    preferenceDirty = false;
    $('marking-settings-error').textContent = '';
    $('retry-marking-setting').hidden = $('reload-marking-setting').hidden = true;
    $('marking-settings-status').textContent = text(settings.has_approved_profile ? saved?'Saved.':'' : 'Complete and approve the survey to use these defaults.');
    $('marking-completion').innerHTML = MisraMarkingProfile.completion(settings);
    $('settings-survey-link').textContent = text(settings.survey_completed ? 'Review or update survey' : 'Open marking survey');
  }
  async function loadSettings() {
    if (busy) return;
    lock(true);
    try { showSettings(await MisraAPI.accountSettings()); }
    catch (e) { $('marking-settings-status').textContent = ''; $('marking-settings-error').textContent = e.message; $('reload-marking-setting').hidden = false; }
    finally { lock(false); }
  }
  async function saveSetting() {
    if (busy || !settings) return;
    preferenceDirty = true; lock(true); $('marking-settings-error').textContent = '';
    $('marking-settings-status').textContent = text('Saving…');
    try { showSettings(await MisraAPI.saveAccountSettings({use_marking_preferences: $('use-marking-preferences').checked}), true); }
    catch (e) {
      $('marking-settings-status').textContent = '';
      $('marking-settings-error').textContent = text('Save not confirmed. Your choice is still here. Retry or reload the saved setting.') + ' ' + e.message;
      $('retry-marking-setting').hidden = $('reload-marking-setting').hidden = false;
    } finally { lock(false); }
  }
  $('use-marking-preferences').addEventListener('change', saveSetting);
  $('retry-marking-setting').addEventListener('click', saveSetting);
  $('reload-marking-setting').addEventListener('click', () => { if (!preferenceDirty || confirm(text('Discard the unsaved setting and reload?'))) loadSettings(); });
  window.MisraCurrentUser.then(user => {
    currentUser = user;
    $('native-account-facts').textContent = [user.full_name, user.email, user.role === 'admin' ? text('Institution administrator') : text('Instructor')].filter(Boolean).join(' · ');
    $('password-required').hidden = !user.must_change_password;
    if (user.must_change_password) $('native-password').open = true;
    return loadSettings();
  }).catch(() => {});
  MisraAPI.health().then(health => {
    if (!health.agents) throw Error('This API does not report agent configuration. Restart it with the updated backend.');
    $('native-ai-status').textContent = text(health.verification_enabled ? 'Three AI roles configured. Model outputs remain proposals until instructor approval.' : 'Verification is disabled in the server configuration. Only extraction and assessment run.');
    const roles = {extraction:['Extraction agent','Reads original pages and maps student answers.'],assessment:['Assessment agent','Uses approved criteria, answer keys, scoring policies, student evidence and applicable course passages.'],verification:['Verification agent','Checks the proposed criterion marks against the same evidence and flags concerns.']};
    $('native-ai-agents').innerHTML = Object.entries(roles).map(([key,[name,description]]) => '<section class="record-row"><div><h3>'+MisraUI.escapeHTML(name)+'</h3><p data-i18n>'+MisraUI.escapeHTML(description)+'</p></div><p data-no-translate>'+MisraUI.escapeHTML(health.agents[key]?.provider || 'Unavailable')+' · '+MisraUI.escapeHTML(health.agents[key]?.model || 'No model configured')+(key === 'verification' && !health.verification_enabled ? ' · Disabled' : '')+'</p></section>').join('');
  }).catch(e => $('native-ai-status').textContent = e.message);
  $('native-themes').addEventListener('change', e => {
    if (e.target.matches('[data-theme-option]')) { MisraTheme.set(e.target.value); $('native-settings-status').textContent = text('Theme saved on this device.'); }
  });
  $('native-password-form').addEventListener('input', () => passwordDirty = true);
  $('delete-account-form').addEventListener('input', () => deletionDirty = true);
  for (const [formId,errorId] of [['native-password-form','native-password-error'],['delete-account-form','delete-account-error']]) {
    $(formId).addEventListener('reset', e => {
      if (busy) { e.preventDefault(); return; }
      if (formId === 'native-password-form') passwordDirty = false; else deletionDirty = false;
      $(errorId).textContent = '';
    });
  }
  window.addEventListener('beforeunload', e => { if (busy || hasUnsaved()) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('click', e => {
    const anchor = e.target.closest('a');
    if (anchor?.getAttribute('href')?.startsWith('#')) return;
    if ((anchor || e.target.closest('#native-sign-out')) && (busy || hasUnsaved() && !confirm(text('Discard unsaved settings and password entries?')))) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  $('native-password-form').addEventListener('submit', async e => {
    e.preventDefault(); if (busy) return;
    const body = Object.fromEntries(new FormData(e.currentTarget));
    if (body.new_password !== body.confirm_password) { $('native-password-error').textContent = text('The new passwords do not match.'); return; }
    if (body.new_password.length < 10 || body.new_password === body.current_password) { $('native-password-error').textContent = text('Use a different password with at least 10 characters.'); return; }
    if ((preferenceDirty || deletionDirty) && !confirm(text('Changing your password signs you out. Discard other unsaved entries?'))) return;
    lock(true); $('native-password-error').textContent = '';
    try { await MisraAPI.changePassword({current_password:body.current_password,new_password:body.new_password}); passwordDirty = preferenceDirty = deletionDirty = busy = false; location.replace('login.html'); }
    catch (e) { $('native-password-error').textContent = e.message; }
    finally { lock(false); }
  });
  $('delete-account-form').addEventListener('submit', async e => {
    e.preventDefault(); if (busy) return;
    const body = Object.fromEntries(new FormData(e.currentTarget));
    if (body.confirmation !== 'DELETE') { $('delete-account-error').textContent = text('Type DELETE to confirm.'); return; }
    lock(true); $('delete-account-error').textContent = '';
    try { await MisraAPI.deleteAccount(body); passwordDirty = preferenceDirty = deletionDirty = busy = false; location.replace('login.html?account_deleted=1'); }
    catch (e) { $('delete-account-error').textContent = e.message; }
    finally { lock(false); }
  });
  window.addEventListener('misra:language', () => {
    if (settings && !preferenceDirty) showSettings(settings);
    if (currentUser) $('native-account-facts').textContent = [currentUser.full_name,currentUser.email,text(currentUser.role==='admin'?'Institution administrator':'Instructor')].filter(Boolean).join(' · ');
    if ($('native-settings-status').textContent) $('native-settings-status').textContent = text('Theme saved on this device.');
  });
})();
