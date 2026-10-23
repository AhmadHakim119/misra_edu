(function () {
  'use strict';

  const host = document.getElementById('marking-preferences');
  if (!host) return;
  const esc = value => window.MisraUI.escapeHTML(String(value ?? ''));
  const t = value => window.MisraLocale?.text(value) || value;
  const format = (value, fields) => Object.entries(fields).reduce((text,[key,item])=>text.replaceAll(`{${key}}`,String(item)),t(value));
  const questionTypes = [
    ['calculation', 'Calculations'], ['short_answer', 'Short answers'],
    ['multiple_choice', 'Multiple choice'], ['essay', 'Essays'],
    ['proof', 'Proofs'], ['code', 'Code'],
    ['data_analysis', 'Data analysis'], ['diagram', 'Diagrams'], ['other', 'Other'],
  ];
  const contextLabels = {
    subjects: 'Subjects', course_level: 'Course level', marking_style: 'Usual marking style',
    question_types: 'Question types', question_style_notes: 'How you set questions',
    other_question_types: 'Other question types', exam_language: 'Usual exam language',
    marking_style_notes: 'How you award partial credit', rubric_style_notes: 'How you prefer marking guides written',
  };
  function saveError(requestError) {
    if (!Array.isArray(requestError.detail)) return t(requestError.message || 'Could not save marking preferences. Your choices are still here.');
    const messages = requestError.detail.map(item => {
      const loc = Array.isArray(item?.loc) ? item.loc : [];
      const contextKey = loc.find(key => Object.hasOwn(contextLabels, key));
      const scenarioIndex = loc.indexOf('scenario_answers');
      const label = contextKey ? t(contextLabels[contextKey])
        : scenarioIndex >= 0 && Number.isInteger(loc[scenarioIndex + 1]) ? format('Scenario {number}',{number:loc[scenarioIndex + 1] + 1})
        : t('Profile');
      return typeof item?.msg === 'string' ? `${label}: ${item.msg}` : '';
    }).filter(Boolean);
    // Validation input/ctx may contain private field values; show only messages.
    return messages.length ? [...new Set(messages)].slice(0, 8).join(' · ') + ' ' + t('Your entries are still here.')
      : t('Some profile fields were rejected. Your entries are still here; check the teaching profile and retry.');
  }
  const scenarios = [
    { id: 'valid_alternative_method', title: 'A student uses a valid method that is different from the model answer.', help: 'Assume the reasoning is correct and reaches the required result.', options: [['full_credit', 'Full credit'], ['partial_credit', 'Partial credit'], ['reject', 'Do not accept']] },
    { id: 'minor_handwritten_syntax', title: 'The intended handwritten syntax is unambiguous, but a small symbol or quotation mark is missing.', help: 'Assume this is written work, not code that must execute exactly.', options: [['full_credit', 'Do not deduct'], ['minor_deduction', 'Minor deduction'], ['reject', 'Require exact syntax']] },
    { id: 'equivalent_notation', title: 'The student uses equivalent notation instead of the notation shown in the answer key.', help: 'The mathematical or technical meaning is unchanged.', options: [['full_credit', 'Accept as equivalent'], ['minor_deduction', 'Minor deduction'], ['reject', 'Require standard notation']] },
    { id: 'carried_forward_error', title: 'One early mistake is carried consistently through otherwise correct later work.', help: 'This concerns the same error repeated downstream, not several independent errors.', options: [['single_penalty', 'Penalize once'], ['penalize_each', 'Penalize each affected step'], ['criterion_specific', 'Decide per criterion']] },
    { id: 'language_quality_outside_criterion', title: 'The academic idea is correct, but grammar or spelling is weak and language quality is not a rubric criterion.', help: 'Language can still be assessed when an approved criterion explicitly requires it.', options: [['ignore', 'Do not deduct'], ['minor_deduction', 'Minor deduction'], ['assess', 'Assess language quality']] },
  ];
  let versions = [], current = null, answers = {}, explicitPreferences = {}, suggestions = [], dirty = false, busy = false, error = '';

  const versionBody = () => ({
    explicit_preferences: { ...explicitPreferences, ...(explicitPreferences.teaching_context ? {teaching_context:{
      ...explicitPreferences.teaching_context,
      other_question_types:explicitPreferences.teaching_context.question_types?.includes('other') ? explicitPreferences.teaching_context.other_question_types || '' : '',
    }} : {}) },
    scenario_answers: scenarios.filter(scenario => answers[scenario.id]).map(scenario => ({ scenario_id: scenario.id, selected_option: answers[scenario.id] })),
    change_summary: current?.status === 'draft' ? current.change_summary || 'Updated marking scenarios' : 'Initial marking scenarios',
  });
  const editable = () => !current || current.status === 'draft';
  const native=window.location.pathname.startsWith('/app/')&&!window.location.pathname.startsWith('/app/pages/');
  if(native)scenarios.push(
    {id:'correct_method_arithmetic_error',title:'The method is correct, but one arithmetic error changes the final result.',help:'Choose a starting policy; the approved rubric still controls the available marks.',options:[['single_penalty','Deduct for the original calculation error'],['penalize_each','Deduct at each affected calculation'],['criterion_specific','Follow the criterion rules']]},
    {id:'missing_units',title:'The numerical result is correct, but its physical unit is missing.',help:'Consider a question where units are relevant to the answer.',options:[['required_when_applicable','Require units when relevant'],['required','Require units explicitly'],['do_not_penalize','Do not deduct for units']]},
    {id:'rounding_difference',title:'A correct calculation differs slightly because of rounding.',help:'Choose the maximum percentage tolerance to propose for numerical results.',options:[['exact','Exact result required'],['within_point_one_percent','Allow up to 0.1% difference'],['within_one_percent','Allow up to 1% difference']]},
    {id:'correct_result_without_working',title:'The final answer is correct, but the student shows no working.',help:'Choose the evidence you normally expect; individual questions can require more.',options:[['key_steps','Require the key steps'],['final_answer_only','Accept the final answer alone'],['complete_reasoning','Require complete reasoning']]},
    {id:'illegible_handwriting',title:'Part of the handwritten answer cannot be read reliably.',help:'Uncertain handwriting should remain visible as uncertainty rather than guessed text.',options:[['manual_review','Send unclear work for instructor review'],['grade_visible_only','Assess readable evidence only'],['zero','Propose zero for the unreadable response']]},
    {id:'incomplete_solution',title:'A student starts correctly but leaves the solution unfinished.',help:'No credit should be invented for steps that are not present.',options:[['completed_criteria','Credit completed criteria only'],['published_levels','Use the published partial-credit levels'],['manual_review','Review incomplete solutions personally']]},
    {id:'contradictory_answers',title:'The response contains two contradictory answers or conflicting working.',help:'MISRA must retain the conflicting evidence and explain the uncertainty.',options:[['manual_review','Flag the contradiction for review'],['identified_final_answer','Use a clearly identified final answer'],['criterion_specific','Follow an explicit criterion rule']]}
  );
  const workspaceName=native?'the marking guide':'Rubric Studio';
  function choose(version) {
    current = version || null;
    answers = Object.fromEntries((version?.scenario_answers || []).map(item => [item.scenario_id, item.selected_option]));
    explicitPreferences = { ...(version?.explicit_preferences || {}) };
    dirty = false; error = '';
  }
  function sync() {
    host.querySelectorAll('[data-scenario]').forEach(input => { if (input.checked) answers[input.dataset.scenario] = input.value; });
    if(native && host.querySelector('[data-context="subjects"]')) {
      const context={...(explicitPreferences.teaching_context || {})};
      host.querySelectorAll('[data-context]').forEach(input=>{
        if(input.dataset.context==='question_types')return;
        context[input.dataset.context]=input.dataset.context==='subjects'
          ? input.value.split(',').map(v=>v.trim()).filter(Boolean) : input.value;
      });
      context.question_types = [...host.querySelectorAll('[data-context="question_types"]:checked')].map(input=>input.value);
      explicitPreferences.teaching_context=context;
      const other=host.querySelector('#profile-other-question-types');
      if(other)other.hidden=!context.question_types.includes('other');
    }
  }
  function contextMarkup(readonly) {
    if(!native)return '';
    const c=explicitPreferences.teaching_context || {};
    const names={unspecified:'No preference',school:'School',undergraduate:'Undergraduate',postgraduate:'Postgraduate',lenient:'Lenient',balanced:'Balanced',strict:'Strict',en:'English',ar:'Arabic',mixed:'Arabic and English'};
    const select=(key,label,values)=>`<label><span data-i18n>${label}</span><select data-context="${key}">${values.map(value=>`<option data-i18n value="${value}" ${(c[key] || 'unspecified')===value?'selected':''}>${esc(key==='exam_language'&&value==='unspecified'?'Choose per exam':names[value])}</option>`).join('')}</select></label>`;
    return `<fieldset class="preference-scenario" ${readonly||busy?'disabled':''}>
      <legend>Your teaching profile</legend><p data-i18n>Saved across exams. Use subjects and teaching preferences only; do not enter student names, answers or private records. Approved context helps draft questions and rubrics when enabled in Settings. Each assessment still requires its own guide approval.</p>
      <div class="form-grid"><label><span data-i18n>Subjects (comma separated, up to 12)</span><input data-context="subjects" dir="auto" maxlength="1450" value="${esc((c.subjects || []).join(', '))}"></label>${select('course_level','Course level',['unspecified','school','undergraduate','postgraduate'])}${select('marking_style','Usual marking style',['unspecified','lenient','balanced','strict'])}${select('exam_language','Usual exam language',['unspecified','en','ar','mixed'])}</div>
      <p class="field-hint" data-i18n>The language chosen for an exam takes precedence over this saved preference.</p>
      <div role="group" aria-labelledby="profile-question-types"><p id="profile-question-types" data-i18n>Question types (select all that apply)</p><div class="scenario-options">${questionTypes.map(([value,label])=>`<label class="scenario-option"><input type="checkbox" data-context="question_types" value="${value}" ${(c.question_types || []).includes(value)?'checked':''}><span data-i18n>${label}</span></label>`).join('')}</div></div>
      <div id="profile-other-question-types" ${(c.question_types || []).includes('other')?'':'hidden'}><label><span data-i18n>Other question types (optional description)</span><textarea data-context="other_question_types" dir="auto" maxlength="500" rows="2">${esc(c.other_question_types || '')}</textarea></label></div>
      <p class="field-hint" data-i18n>Leniency never supplies missing evidence or overrides an approved rule.</p>${[['question_style_notes','How you set questions'],['marking_style_notes','How you award partial credit'],['rubric_style_notes','How you prefer marking guides written']].map(([key,label])=>`<label><span data-i18n>${label}</span><textarea data-context="${key}" dir="auto" maxlength="1500" rows="3">${esc(c[key] || '')}</textarea></label>`).join('')}</fieldset>`;
  }
  function proposalMarkup(proposal) {
    const labels = {
      method_credit: 'Valid-method credit', handwritten_syntax_policy: 'Handwritten syntax', notation_policy: 'Equivalent notation',
      error_carried_forward: 'Carried-forward errors', language_quality_policy: 'Language quality',
      alternative_valid_methods: 'Alternative methods', alternative_methods_allowed: 'Alternative methods',
      arithmetic_error_policy:'Arithmetic errors',units_policy:'Units',rounding_tolerance_percent:'Rounding tolerance (%)',
      evidence_requirement:'Required working',illegible_response_policy:'Unclear handwriting',custom_instructions:'Additional marking guidance',
    };
    const entries = Object.entries(proposal || {});
    return entries.length ? `<div class="preference-proposal"><h4>Proposed rubric defaults</h4><dl>${entries.map(([key, value]) => `<dt>${esc(labels[key] || key.replaceAll('_', ' '))}</dt><dd ${key==='custom_instructions'?'dir="auto"':'data-i18n'}>${esc(key==='custom_instructions'?String(value):String(value).replaceAll('_', ' '))}</dd>`).join('')}</dl><p class="field-hint" data-i18n>These are suggestions only. Applying them to a rubric requires a separate confirmation in ${workspaceName}.</p></div>` : '';
  }
  function explicitProposal() {
    const proposal = { ...explicitPreferences };
    delete proposal.teaching_context;
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
    const visibleScenarios=native&&readonly?scenarios.filter(scenario=>answers[scenario.id]):scenarios;
    const count=value=>new Intl.NumberFormat(window.MisraLocale?.language()==='ar'?'ar':'en').format(value);
    const answeredText=format('{answered} of {total} scenarios answered',{answered:count(answered),total:count(scenarios.length)});
    host.innerHTML = `<div class="preference-profile-head"><div><h3>${esc(current ? format('Preference profile version {version}',{version:count(current.version_number)}) : t('Create your first preference profile'))}</h3><p data-i18n>${readonly ? (native?'Saved profile. Manage automatic use in Settings.':`This approved version is read-only and available as an optional starting point in ${workspaceName}.`) : 'Choose the decision closest to your normal marking. You can still override every proposed rule per assessment.'}</p>${native&&readonly?'<button class="btn btn-secondary" type="button" data-preference-new>Create new draft</button>':''}</div>${window.MisraUI.badge(t(current ? current.status : 'Not set'), readonly ? 'success' : 'draft')}</div>
      ${error ? `<p class="check-error" role="alert">${esc(error)}</p>` : ''}
      ${native&&readonly&&answered<scenarios.length?'<p data-i18n>This earlier profile remains unchanged. Create a new draft to complete the expanded survey.</p>':''}
      <form data-preference-form>
        ${contextMarkup(readonly)}
        ${suggestionMarkup()}
        <div class="preference-scenarios">${visibleScenarios.map(scenario => `<fieldset class="preference-scenario" ${readonly || busy ? 'disabled' : ''}><legend>${scenarios.indexOf(scenario) + 1}. ${esc(scenario.title)}</legend><p data-i18n>${esc(scenario.help)}</p><div class="scenario-options">${scenario.options.map(([value, label]) => `<label class="scenario-option"><input type="radio" name="scenario-${esc(scenario.id)}" value="${esc(value)}" data-scenario="${esc(scenario.id)}" ${answers[scenario.id] === value ? 'checked' : ''}><span data-i18n>${esc(label)}</span></label>`).join('')}</div></fieldset>`).join('')}</div>
        ${proposalMarkup(dirty ? { ...(current?.derived_proposal || {}), ...explicitProposal() } : current?.derived_proposal)}
        <div class="preference-actions">${readonly ? native?'':'<button class="btn btn-secondary" type="button" data-preference-new>Create new draft</button>' : '<button class="btn btn-secondary" type="submit" data-preference-save>Save draft</button><button class="btn btn-primary" type="button" data-preference-approve>Save &amp; approve profile</button>'}<p class="form-message" role="status">${esc(busy ? t('Saving…') : dirty ? `${answeredText} · ${t('unsaved')}` : readonly ? t('Approved profiles never change existing rubrics.') : answeredText)}</p></div>
      </form>
      ${versions.length ? `<details class="preference-history"><summary>${esc(format('Preference history ({count})',{count:count(versions.length)}))}</summary>${versions.map(version => `<div class="preference-history-row"><span>${esc(format('Version {version}',{version:count(version.version_number)}))} · ${esc(t(version.status))}</span><button class="btn btn-ghost" type="button" data-preference-version="${esc(version.id)}">View</button></div>`).join('')}</details>` : ''}`;
    host.querySelector('[data-preference-form]')?.addEventListener('change', event => {
      const changed = event.target.closest('[data-scenario]');
      sync();
      dirty = true;
      error = '';
      if(!event.target.matches('[data-context]')) render(changed ? { scenario: changed.dataset.scenario, value: changed.value } : null);
    });
    host.querySelector('[data-preference-form]')?.addEventListener('input',event=>{
      if(!event.target.matches('[data-context]'))return;
      sync(); dirty=true; error='';
      const message=host.querySelector('.form-message');if(message)message.textContent=t('Teaching profile changes · unsaved');
    });
    host.querySelector('[data-preference-form]')?.addEventListener('submit', event => { event.preventDefault(); save(false); });
    host.querySelector('[data-preference-approve]')?.addEventListener('click', () => save(true));
    host.querySelector('[data-preference-new]')?.addEventListener('click', () => { current = null; dirty = true; render(); });
    host.querySelectorAll('[data-use-suggestion]').forEach(button => button.addEventListener('click', () => useSuggestion(suggestions[Number(button.dataset.useSuggestion)])));
    host.querySelectorAll('[data-preference-version]').forEach(button => button.addEventListener('click', () => {
      if (!dirty || window.confirm(t('Discard unsaved preference changes?'))) { choose(versions.find(version => version.id === button.dataset.preferenceVersion)); render(); }
    }));
    if (focusTarget) {
      host.querySelector(`[data-scenario="${CSS.escape(focusTarget.scenario)}"][value="${CSS.escape(focusTarget.value)}"]`)?.focus();
    }
  }
  async function save(approve) {
    if (busy || !editable()) return;
    sync();
    const subjects = explicitPreferences.teaching_context?.subjects || [];
    if(native && (subjects.length > 12 || subjects.some(subject=>subject.length > 120))){
      error=t('Subjects: enter up to 12 subjects, with no more than 120 characters each. Your entries are still here.');render();return;
    }
    if (!Object.keys(answers).length && !Object.keys(explicitPreferences).length) { error = t('Answer at least one scenario or use an observed decision before saving.'); render(); return; }
    if(native && approve && Object.keys(answers).length<scenarios.length){error=t('Answer all 12 scenarios before approving this expanded profile. You can save a partial draft.');render();return;}
    if (approve && !window.confirm(t(native?'Approve this profile? Its rules will fill new guide drafts when automatic preferences are enabled in Settings. Existing guides are unchanged.':'Approve this preference profile? It will remain a suggestion and will not change existing rubrics.'))) return;
    busy = true; error = ''; render();
    try {
      const saved = current ? await window.MisraAPI.updateInstructorPreference(current.id, versionBody()) : await window.MisraAPI.createInstructorPreference(versionBody());
      current = saved; versions = [saved, ...versions.filter(version => version.id !== saved.id)]; dirty = false;
      if (approve) {
        const approved = await window.MisraAPI.approveInstructorPreference(saved.id);
        versions = versions.map(version => version.id === approved.id ? approved : version.status === 'approved' ? { ...version, status: 'superseded' } : version);
        choose(approved);
      } else choose(saved);
      window.showToast(t(approve ? 'Marking preference profile approved.' : 'Marking preference draft saved.'), 'success');
      window.dispatchEvent(new CustomEvent('misra:preferences-saved',{detail:{approved:approve,version:current}}));
    } catch (requestError) {
      error = saveError(requestError);
    } finally { busy = false; render(); }
  }
  window.addEventListener('beforeunload', event => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } });
  window.MisraInstructorPreferences={hasUnsaved:()=>dirty,isBusy:()=>busy,current:()=>current};
  if(native)window.addEventListener('misra:language',()=>{sync();render();});
  if(native)document.addEventListener('click',event=>{
    if(!event.target.closest('a,#native-sign-out'))return;
    if(busy||dirty&&!confirm(t('Leave without saving your marking preferences?'))){event.preventDefault();event.stopImmediatePropagation();}
  },true);
  Promise.allSettled([
    window.MisraAPI.instructorPreferenceVersions(),
    window.MisraAPI.instructorPreferenceSuggestions(),
  ]).then(([versionsResult, suggestionsResult]) => {
    if (versionsResult.status === 'rejected') throw versionsResult.reason;
    versions = Array.isArray(versionsResult.value) ? versionsResult.value : [];
    const suggestionPayload = suggestionsResult.status === 'fulfilled' ? suggestionsResult.value : null;
    suggestions = Array.isArray(suggestionPayload?.suggestions) ? suggestionPayload.suggestions : [];
    choose(versions.find(version => version.status === 'draft') || versions.find(version => version.status === 'approved') || versions[0]);
  }).catch(requestError => { error = t(requestError.message || 'Could not load marking preferences.'); }).finally(render);
})();
