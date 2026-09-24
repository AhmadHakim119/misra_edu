(function () {
  'use strict';

  const host = document.getElementById('marking-preferences');
  if (!host) return;
  const esc = value => window.MisraUI.escapeHTML(String(value ?? ''));
  const scenarios = [
    { id: 'valid_alternative_method', title: 'A student uses a valid method that is different from the model answer.', help: 'Assume the reasoning is correct and reaches the required result.', options: [['full_credit', 'Full credit'], ['partial_credit', 'Partial credit'], ['reject', 'Do not accept']] },
    { id: 'minor_handwritten_syntax', title: 'The intended handwritten syntax is unambiguous, but a small symbol or quotation mark is missing.', help: 'Assume this is written work, not code that must execute exactly.', options: [['full_credit', 'Do not deduct'], ['minor_deduction', 'Minor deduction'], ['reject', 'Require exact syntax']] },
    { id: 'equivalent_notation', title: 'The student uses equivalent notation instead of the notation shown in the answer key.', help: 'The mathematical or technical meaning is unchanged.', options: [['full_credit', 'Accept as equivalent'], ['minor_deduction', 'Minor deduction'], ['reject', 'Require standard notation']] },
    { id: 'carried_forward_error', title: 'One early mistake is carried consistently through otherwise correct later work.', help: 'This concerns the same error repeated downstream, not several independent errors.', options: [['single_penalty', 'Penalize once'], ['penalize_each', 'Penalize each affected step'], ['criterion_specific', 'Decide per criterion']] },
    { id: 'language_quality_outside_criterion', title: 'The academic idea is correct, but grammar or spelling is weak and language quality is not a rubric criterion.', help: 'Language can still be assessed when an approved criterion explicitly requires it.', options: [['ignore', 'Do not deduct'], ['minor_deduction', 'Minor deduction'], ['assess', 'Assess language quality']] },
  ];
  let versions = [], current = null, answers = {}, explicitPreferences = {}, suggestions = [], dirty = false, busy = false, error = '';

  const versionBody = () => ({
    explicit_preferences: { ...explicitPreferences },
    scenario_answers: scenarios.filter(scenario => answers[scenario.id]).map(scenario => ({ scenario_id: scenario.id, selected_option: answers[scenario.id] })),
    change_summary: current?.status === 'draft' ? current.change_summary || 'Updated marking scenarios' : 'Initial marking scenarios',
  });
  const editable = () => !current || current.status === 'draft';
  function choose(version) {
    current = version || null;
    answers = Object.fromEntries((version?.scenario_answers || []).map(item => [item.scenario_id, item.selected_option]));
    explicitPreferences = { ...(version?.explicit_preferences || {}) };
    dirty = false; error = '';
  }
  function sync() {
    host.querySelectorAll('[data-scenario]').forEach(input => { if (input.checked) answers[input.dataset.scenario] = input.value; });
  }
  function proposalMarkup(proposal) {
    const labels = {
      method_credit: 'Valid-method credit', handwritten_syntax_policy: 'Handwritten syntax', notation_policy: 'Equivalent notation',
      error_carried_forward: 'Carried-forward errors', language_quality_policy: 'Language quality',
      alternative_valid_methods: 'Alternative methods', alternative_methods_allowed: 'Alternative methods',
    };
    const entries = Object.entries(proposal || {});
    return entries.length ? `<div class="preference-proposal"><h4>Proposed rubric defaults</h4><dl>${entries.map(([key, value]) => `<dt>${esc(labels[key] || key.replaceAll('_', ' '))}</dt><dd>${esc(String(value).replaceAll('_', ' '))}</dd>`).join('')}</dl><p class="field-hint">These are suggestions only. Applying them to a rubric requires a separate confirmation in Rubric Studio.</p></div>` : '';
  }
  function explicitProposal() {
    const proposal = { ...explicitPreferences };
    if ('alternative_valid_methods' in proposal) {
      if (proposal.alternative_valid_methods !== 'criterion_specific') proposal.alternative_methods_allowed = proposal.alternative_valid_methods === 'allow';
      delete proposal.alternative_valid_methods;
    }
    return proposal;
  }
  function suggestionMarkup() {
    if (!suggestions.length) return '';
    const labels = {
      valid_alternative: 'Accept valid alternative methods', minor_notation: 'Tolerate equivalent notation',
      method_credit: 'Award method credit', carried_forward_error: 'Penalize a carried-forward error once',
      language_tolerance: 'Ignore language quality unless assessed',
    };
    return `<section class="preference-observations" aria-labelledby="observed-decisions-title"><div><span class="eyebrow">Observed decisions</span><h4 id="observed-decisions-title">Patterns ready for your judgment</h4><p>MISRA found repeated instructor decisions. OCR errors, mapping problems, and rubric issues are excluded. Nothing changes unless you create, approve, and later apply a profile.</p></div><div class="preference-observation-list">${suggestions.map((suggestion, index) => `<article><div><strong>${esc(labels[suggestion.review_reason_code] || suggestion.review_reason_code.replaceAll('_', ' '))}</strong><small>Supported by ${Number(suggestion.distinct_label_count) || 0} distinct reviews</small></div><button class="btn btn-ghost" type="button" data-use-suggestion="${index}" ${busy || !editable() ? 'disabled' : ''}>Use in draft</button></article>`).join('')}</div></section>`;
  }
  function useSuggestion(suggestion) {
    const proposal = suggestion?.proposed_policy || {};
    if ('method_credit' in proposal) explicitPreferences.method_credit = proposal.method_credit;
    if ('notation_policy' in proposal) explicitPreferences.notation_policy = proposal.notation_policy;
    if ('error_carried_forward' in proposal) explicitPreferences.error_carried_forward = proposal.error_carried_forward;
    if ('language_quality_policy' in proposal) explicitPreferences.language_quality_policy = proposal.language_quality_policy;
    if ('alternative_methods_allowed' in proposal) explicitPreferences.alternative_valid_methods = proposal.alternative_methods_allowed ? 'allow' : 'disallow';
    current = current?.status === 'draft' ? current : null;
    dirty = true;
    error = '';
    render();
  }
  function render(focusTarget = null) {
    host.setAttribute('aria-busy', String(busy));
    const readonly = !editable();
    const answered = Object.keys(answers).length;
    host.innerHTML = `<div class="preference-profile-head"><div><h3>${current ? `Preference profile version ${current.version_number}` : 'Create your first preference profile'}</h3><p>${readonly ? 'This approved version is read-only and available as an optional starting point in Rubric Studio.' : 'Choose the decision closest to your normal marking. You can still override every proposed rule per assessment.'}</p></div>${window.MisraUI.badge(current ? current.status : 'Not set', readonly ? 'success' : 'draft')}</div>
      ${error ? `<p class="check-error" role="alert">${esc(error)}</p>` : ''}
      <form data-preference-form>
        ${suggestionMarkup()}
        <div class="preference-scenarios">${scenarios.map((scenario, index) => `<fieldset class="preference-scenario" ${readonly || busy ? 'disabled' : ''}><legend>${index + 1}. ${esc(scenario.title)}</legend><p>${esc(scenario.help)}</p><div class="scenario-options">${scenario.options.map(([value, label]) => `<label class="scenario-option"><input type="radio" name="scenario-${esc(scenario.id)}" value="${esc(value)}" data-scenario="${esc(scenario.id)}" ${answers[scenario.id] === value ? 'checked' : ''}><span>${esc(label)}</span></label>`).join('')}</div></fieldset>`).join('')}</div>
        ${proposalMarkup(dirty ? { ...(current?.derived_proposal || {}), ...explicitProposal() } : current?.derived_proposal)}
        <div class="preference-actions">${readonly ? '<button class="btn btn-secondary" type="button" data-preference-new>Create new draft</button>' : '<button class="btn btn-secondary" type="submit" data-preference-save>Save draft</button><button class="btn btn-primary" type="button" data-preference-approve>Save &amp; approve profile</button>'}<p class="form-message" role="status">${busy ? 'Saving…' : dirty ? `${answered} of ${scenarios.length} scenarios answered · unsaved` : readonly ? 'Approved profiles never change existing rubrics.' : `${answered} of ${scenarios.length} scenarios answered`}</p></div>
      </form>
      ${versions.length ? `<details class="preference-history"><summary>Preference history (${versions.length})</summary>${versions.map(version => `<div class="preference-history-row"><span>Version ${version.version_number} · ${esc(version.status)}</span><button class="btn btn-ghost" type="button" data-preference-version="${esc(version.id)}">View</button></div>`).join('')}</details>` : ''}`;
    host.querySelector('[data-preference-form]')?.addEventListener('change', event => {
      const changed = event.target.closest('[data-scenario]');
      sync();
      dirty = true;
      render(changed ? { scenario: changed.dataset.scenario, value: changed.value } : null);
    });
    host.querySelector('[data-preference-form]')?.addEventListener('submit', event => { event.preventDefault(); save(false); });
    host.querySelector('[data-preference-approve]')?.addEventListener('click', () => save(true));
    host.querySelector('[data-preference-new]')?.addEventListener('click', () => { current = null; dirty = true; render(); });
    host.querySelectorAll('[data-use-suggestion]').forEach(button => button.addEventListener('click', () => useSuggestion(suggestions[Number(button.dataset.useSuggestion)])));
    host.querySelectorAll('[data-preference-version]').forEach(button => button.addEventListener('click', () => {
      if (!dirty || window.confirm('Discard unsaved preference changes?')) { choose(versions.find(version => version.id === button.dataset.preferenceVersion)); render(); }
    }));
    if (focusTarget) {
      host.querySelector(`[data-scenario="${CSS.escape(focusTarget.scenario)}"][value="${CSS.escape(focusTarget.value)}"]`)?.focus();
    }
  }
  async function save(approve) {
    if (busy || !editable()) return;
    sync();
    if (!Object.keys(answers).length && !Object.keys(explicitPreferences).length) { error = 'Answer at least one scenario or use an observed decision before saving.'; render(); return; }
    if (approve && !window.confirm('Approve this preference profile? It will remain a suggestion and will not change existing rubrics.')) return;
    busy = true; error = ''; render();
    try {
      const saved = current ? await window.MisraAPI.updateInstructorPreference(current.id, versionBody()) : await window.MisraAPI.createInstructorPreference(versionBody());
      current = saved; versions = [saved, ...versions.filter(version => version.id !== saved.id)]; dirty = false;
      if (approve) {
        const approved = await window.MisraAPI.approveInstructorPreference(saved.id);
        versions = versions.map(version => version.id === approved.id ? approved : version.status === 'approved' ? { ...version, status: 'superseded' } : version);
        choose(approved);
      } else choose(saved);
      window.showToast(approve ? 'Marking preference profile approved.' : 'Marking preference draft saved.', 'success');
    } catch (requestError) {
      error = requestError.message || 'Could not save marking preferences. Your choices are still here.';
    } finally { busy = false; render(); }
  }
  window.addEventListener('beforeunload', event => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } });
  Promise.allSettled([
    window.MisraAPI.instructorPreferenceVersions(),
    window.MisraAPI.instructorPreferenceSuggestions(),
  ]).then(([versionsResult, suggestionsResult]) => {
    if (versionsResult.status === 'rejected') throw versionsResult.reason;
    versions = Array.isArray(versionsResult.value) ? versionsResult.value : [];
    const suggestionPayload = suggestionsResult.status === 'fulfilled' ? suggestionsResult.value : null;
    suggestions = Array.isArray(suggestionPayload?.suggestions) ? suggestionPayload.suggestions : [];
    choose(versions.find(version => version.status === 'draft') || versions.find(version => version.status === 'approved') || versions[0]);
  }).catch(requestError => { error = requestError.message || 'Could not load marking preferences.'; }).finally(render);
})();
