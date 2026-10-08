(function () {
  'use strict';

  const examSelect = document.getElementById('rubric-exam');
  const questionList = document.getElementById('question-list');
  const questionCount = document.getElementById('question-count');
  const workspace = document.getElementById('rubric-workspace');
  const uploadLink = document.getElementById('upload-link');
  const questionForm = document.getElementById('question-form');
  const questionTemplate = document.getElementById('question-template');
  const composer = document.getElementById('question-composer');
  const openComposer = document.getElementById('open-question-form');
  const closeComposer = document.getElementById('close-question-form');
  const formError = document.getElementById('question-form-error');
  const formStatus = document.getElementById('question-form-status');
  const applyTemplate = document.getElementById('apply-question-template');
  let formDirty = false;
  let editorDirty = false;
  let savingRubric = false;
  let persistedRubric = null;
  const busyControls = new Map();
  let savingQuestion = false;
  let loadedExamId = '';
  let questionRequest = 0;
  let renderedQuestionId = '';
  let openPanels = {};
  const state = { exams: [], questions: [], question: null, rubric: null, version: null, versions: [], gradingMode: 'adaptive', instructorProfile: null };

  function setRubricBusy(busy) {
    savingRubric = busy;
    workspace.setAttribute('aria-busy', String(busy));
    if (busy) {
      workspace.querySelectorAll('input, textarea, select, button').forEach(control => {
        if (!busyControls.has(control)) busyControls.set(control, control.disabled);
        control.disabled = true;
      });
    } else {
      busyControls.forEach((disabled, control) => { if (control.isConnected) control.disabled = disabled; });
      busyControls.clear();
    }
  }

  function discardRubricEdits() {
    if (editorDirty && persistedRubric) { state.rubric = structuredClone(persistedRubric); renderEditor(); }
    editorDirty = false;
  }

  const gradingModeHelp = {
    adaptive: 'MISRA uses the original page for diagrams, mathematical working, and other visual evidence. Plain written answers use OCR text only.',
    image_text_required: 'The grader always receives the original source page together with the extracted text.',
    text_only: 'The grader receives extracted text only. Use this for answers where layout, symbols, and markings do not affect credit.',
  };

  const questionTemplates = {
    short_answer: {
      title: 'Core concept and relevance',
      description: 'Award credit when the response identifies the required concept and applies it directly to the question. Accept equivalent wording.',
    },
    calculation: {
      title: 'Correct method, working, and result',
      description: 'Award method credit for a valid setup and meaningful intermediate work. Apply one proportional penalty for a carried arithmetic error instead of repeatedly penalizing the same mistake.',
    },
    proof: {
      title: 'Valid claim and logical justification',
      description: 'Award credit for the correct conclusion supported by logically connected steps. Accept equivalent proof strategies and notation when the reasoning is valid.',
    },
    programming: {
      title: 'Correct logic and intended outcome',
      description: 'Award credit for logically correct code or queries that produce the intended result. Treat minor written-exam syntax issues leniently when intent is unambiguous.',
    },
    diagram: {
      title: 'Correct structure and relationships',
      description: 'Award credit for the required entities, labels, and relationships. Inspect the original image and accept visually equivalent layouts.',
    },
    subjective: {
      title: 'Reasoned position addressing the core idea',
      description: 'Award credit for a defensible response that reaches the central idea with relevant reasoning. Do not require the answer key wording or one specific position.',
    },
  };

  questionTemplate.addEventListener('change', () => {
    applyTemplate.disabled = !questionTemplate.value;
  });
  applyTemplate.addEventListener('click', () => {
    const template = questionTemplates[questionTemplate.value];
    if (!template) return;
    if ((questionForm.criterion_title.value.trim() || questionForm.criterion_description.value.trim()) &&
        !window.confirm('Replace the marking guide you typed with this template? The question text will stay unchanged.')) return;
    questionForm.criterion_title.value = template.title;
    questionForm.criterion_description.value = template.description;
    formDirty = true;
    formStatus.textContent = 'Template applied. Adapt the marking guide to this question before saving.';
    questionForm.criterion_description.focus();
  });

  function showComposer(focus = true) {
    if (!loadedExamId || savingQuestion || savingRubric) return;
    if (!window.MisraAnswerKeys.canLeave()) return;
    if (editorDirty && !window.confirm('Discard unsaved rubric edits and add a question?')) return;
    window.MisraAnswerKeys.discard();
    discardRubricEdits();
    composer.hidden = false;
    workspace.hidden = true;
    closeComposer.hidden = state.questions.length === 0;
    openComposer.setAttribute('aria-expanded', 'true');
    const exam = state.exams.find((item) => item.id === loadedExamId);
    document.getElementById('question-exam-context').textContent = exam ? `${exam.course_code ? exam.course_code + ' · ' : ''}${exam.title}` : '';
    if (focus) {
      document.getElementById('question-composer-title').focus();
      composer.scrollIntoView({ block: 'start' });
    }
  }

  function hideComposer() {
    composer.hidden = true;
    workspace.hidden = false;
    openComposer.setAttribute('aria-expanded', 'false');
  }

  openComposer.addEventListener('click', () => showComposer());
  closeComposer.addEventListener('click', () => { hideComposer(); openComposer.focus(); });
  questionForm.addEventListener('input', () => { formDirty = true; formError.hidden = true; });
  window.addEventListener('beforeunload', (event) => {
    if (formDirty || editorDirty || savingQuestion || savingRubric || window.MisraAnswerKeys.hasUnsaved()) { event.preventDefault(); event.returnValue = ''; }
  });
  workspace.addEventListener('input', event => {
    if (event.target.matches('[data-reference], [data-policy], [data-key]')) {
      editorDirty = true;
      const status = workspace.querySelector('[data-rubric-save-state]');
      if (status) status.textContent = 'Unsaved changes · save a draft or approve when ready';
    }
  });
  examSelect.addEventListener('change', event => {
    if (savingRubric || !window.MisraAnswerKeys.canLeave() || (editorDirty && !window.confirm('Discard unsaved rubric edits and switch assessments?'))) {
      examSelect.value = loadedExamId; event.stopImmediatePropagation(); return;
    }
    // Do not clear dirty state here: a later composer/import guard can still
    // cancel the same event. loadExam clears it only when navigation proceeds.
  }, true);

  function simpleGradingMode(mode) {
    if (mode === 'image_text' || mode === 'image_text_required') return 'image_text_required';
    if (mode === 'text_only') return 'text_only';
    return 'adaptive';
  }

  function criterionId() {
    return `criterion_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
  }

  function blankCriterion() {
    return { id: criterionId(), title: 'New criterion', description: '', points: 1, scoring_type: 'scaled', partial_credit_allowed: true, performance_levels: [], required_evidence: [], common_errors: [], alternative_methods: [] };
  }

  function normalizeRubric(raw, maxScore) {
    const rubric = structuredClone(raw || {});
    rubric.schema_version = 2;
    rubric.max_score = Number(rubric.max_score || maxScore);
    rubric.criteria = (rubric.criteria || []).map((criterion) => ({
      id: criterion.id || criterionId(),
      title: criterion.title || criterion.description || 'Criterion',
      description: criterion.description || criterion.title || '',
      points: Number(criterion.points || 0),
      scoring_type: criterion.scoring_type || 'scaled',
      partial_credit_allowed: criterion.scoring_type === 'binary' ? false : criterion.partial_credit_allowed !== false,
      performance_levels: criterion.performance_levels || [],
      required_evidence: criterion.required_evidence || [],
      common_errors: criterion.common_errors || [],
      alternative_methods: criterion.alternative_methods || [],
    }));
    rubric.policy = {
      assessment_scope: rubric.policy?.assessment_scope || 'paper',
      grading_approach: rubric.policy?.grading_approach || rubric.grading_approach || 'balanced',
      method_credit: rubric.policy?.method_credit || 'partial',
      arithmetic_error_policy: rubric.policy?.arithmetic_error_policy || 'single_penalty',
      rounding_tolerance_percent: rubric.policy?.rounding_tolerance_percent ?? null,
      units_policy: rubric.policy?.units_policy || 'required_when_applicable',
      notation_policy: rubric.policy?.notation_policy || 'equivalent_allowed',
      alternative_methods_allowed: rubric.policy?.alternative_methods_allowed !== false,
      evidence_requirement: rubric.policy?.evidence_requirement || 'key_steps',
      illegible_response_policy: rubric.policy?.illegible_response_policy || 'manual_review',
      language_quality_policy: rubric.policy?.language_quality_policy || 'criterion_specific',
      error_carried_forward: rubric.policy?.error_carried_forward || 'criterion_specific',
      handwritten_syntax_policy: rubric.policy?.handwritten_syntax_policy || 'criterion_specific',
      custom_instructions: rubric.policy?.custom_instructions || null,
    };
    return rubric;
  }

  function field(label, control, extraClass = '', controlId = '') {
    return `<div class="field ${extraClass}"><label${controlId ? ` for="${controlId}"` : ''}>${label}</label>${control}</div>`;
  }

  function renderCriterion(criterion, index) {
    return `<article class="criterion" data-criterion-index="${index}">
      <div class="criterion-head">
        ${field('Criterion title', `<input class="input" id="criterion-${index}-title" data-key="title" value="${MisraUI.escapeHTML(criterion.title)}">`, '', `criterion-${index}-title`)}
        ${field('Points', `<input class="input numeric" id="criterion-${index}-points" data-key="points" type="number" min="0.01" step="0.25" value="${criterion.points}">`, '', `criterion-${index}-points`)}
        <button class="icon-button" type="button" data-remove-criterion aria-label="Remove ${MisraUI.escapeHTML(criterion.title)}"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5M14 11v5"/></svg></button>
      </div>
      ${field('What earns credit', `<textarea class="input textarea" id="criterion-${index}-description" data-key="description">${MisraUI.escapeHTML(criterion.description)}</textarea>`, '', `criterion-${index}-description`)}
      <div class="criterion-fields">
        ${field('Scoring', `<select class="input select" id="criterion-${index}-scoring" data-key="scoring_type"><option value="scaled" ${criterion.scoring_type === 'scaled' ? 'selected' : ''}>Scaled with partial credit</option><option value="binary" ${criterion.scoring_type === 'binary' ? 'selected' : ''}>Binary, full or zero</option></select>`, '', `criterion-${index}-scoring`)}
        ${field('Required evidence', `<input class="input" id="criterion-${index}-evidence" data-key="required_evidence" value="${MisraUI.escapeHTML((criterion.required_evidence || []).join(', '))}" placeholder="e.g. substitution, final units">`, '', `criterion-${index}-evidence`)}
      </div>
    </article>`;
  }

  function renderEditor() {
    if (!state.question || !state.rubric) {
      renderedQuestionId = '';
      workspace.innerHTML = `<div class="workspace-card">${MisraUI.emptyState('Select a question', 'Choose an assessment and question to inspect its active rubric.', MisraUI.icons.rubric)}</div>`;
      return;
    }
    const draft = state.version?.status === 'draft';
    const total = state.rubric.criteria.reduce((sum, item) => sum + Number(item.points || 0), 0);
    if (renderedQuestionId === state.question.id) {
      workspace.querySelectorAll('details[data-rubric-panel]').forEach(panel => { openPanels[panel.dataset.rubricPanel] = panel.open; });
    } else {
      openPanels = { criteria: true };
      renderedQuestionId = state.question.id;
    }
    const expanded = name => openPanels[name] ? ' open' : '';
    workspace.innerHTML = `
      <div class="workspace-card rubric-toolbar">
        <div><div class="rubric-toolbar-meta"><strong>Question ${MisraUI.escapeHTML(state.question.question_number)}</strong>${MisraUI.badge(state.version ? `Version ${state.version.version_number}` : 'Legacy rubric', draft ? 'draft' : 'success')}${MisraUI.badge(state.rubric.policy.grading_approach, 'slate')}</div><p class="section-copy">${MisraUI.escapeHTML(state.question.question_text || 'Question text is not available.')}</p></div>
        <div><div class="rubric-toolbar-actions">
          ${draft ? '<button class="btn btn-secondary" type="button" data-save-rubric>Save draft</button><button class="btn btn-primary" type="button" data-approve-rubric>Approve</button>' : '<button class="btn btn-secondary" type="button" data-create-draft>Create editable draft</button>'}
        </div><p class="rubric-edit-state" data-rubric-save-state role="status">${editorDirty ? 'Unsaved changes' : draft ? 'Saved draft · not used for grading yet' : 'Approved · create a draft to change the marking guide'}</p></div>
      </div>
      <nav class="rubric-shortcuts" aria-label="Rubric sections">${[['criteria', 'Marking criteria'], ['answer-key', 'Answer key'], ['policy', 'Scoring policy'], ['suggestion', 'AI draft'], ['input', 'Grading input']].map(([target, label]) => `<button class="btn btn-secondary" type="button" data-rubric-jump="${target}">${label}</button>`).join('')}<button class="btn btn-ghost" type="button" data-fold-rubric>Collapse sections</button></nav>

      <details class="workspace-card card-pad rubric-section answer-key-section" data-rubric-panel="answer-key"${expanded('answer-key')}>
        <summary class="rubric-section-summary"><span><strong>Answer key</strong><small>Reference solution and accepted alternatives</small></span></summary>
        <div id="answer-key-panel" class="answer-key-panel" aria-labelledby="answer-key-title"></div>
      </details>
      <details class="workspace-card card-pad rubric-section rubric-reference" data-rubric-panel="legacy"${expanded('legacy')}>
        <summary class="rubric-section-summary"><span><strong>Legacy rubric reference</strong><small>Used until a standalone answer key is approved</small></span></summary>
        <p class="section-copy">Preserved with this rubric; approving a standalone key does not delete it. Criteria still decide the marks.</p>
        <div class="field"><label for="rubric-reference">Answer key, worked solution, or supporting context</label><textarea class="input textarea" id="rubric-reference" data-reference="reference_context" rows="6" placeholder="Add your reference solution, shared table data, or the core idea a correct response must reach.">${MisraUI.escapeHTML(state.rubric.reference_context || '')}</textarea></div>
        <div class="field"><label for="rubric-alternatives">Other acceptable answers (one per line)</label><textarea class="input textarea" id="rubric-alternatives" data-reference="acceptable_answers" rows="3" placeholder="Record valid alternatives without requiring an exact wording match.">${MisraUI.escapeHTML((state.rubric.acceptable_answers || []).join('\n'))}</textarea></div>
        <p class="field-hint">${draft ? 'Save draft to keep these references. Approve the draft to use them for future grading.' : 'This reference belongs to the approved version. Create an editable draft to change it.'} For diagrams, also select Image + text required and verify the mapped source pages.</p>
      </details>

      <details class="workspace-card card-pad rubric-section suggestion-panel" data-rubric-panel="suggestion"${expanded('suggestion')}>
        <summary class="rubric-section-summary"><span><strong>Ask AI for a granular draft</strong><small>Optional · never approved automatically</small></span></summary>
        <p class="section-copy" style="margin:7px 0 16px">The suggestion is saved as a new draft version. It never becomes active automatically.</p>
        <form id="suggestion-form">
          <div class="suggestion-fields">
            ${field('Grading approach', `<select class="input select" id="suggestion-grading-approach" name="grading_approach"><option value="lenient">Lenient</option><option value="balanced" selected>Balanced</option><option value="strict">Strict</option></select>`, '', 'suggestion-grading-approach')}
            ${field('Course level', '<input class="input" id="suggestion-course-level" name="course_level" placeholder="e.g. undergraduate, year 2">', '', 'suggestion-course-level')}
            ${field('Additional context for this draft', '<textarea class="input textarea" id="suggestion-additional-context" name="answer_key" aria-describedby="suggestion-context-help" placeholder="Optional details that are not already captured in the approved answer key."></textarea><span class="field-hint" id="suggestion-context-help">This only guides the AI rubric suggestion. It is not an approved answer key and does not become grading authority. Approved standalone answer keys are used separately during grading.</span>', 'wide', 'suggestion-additional-context')}
            ${field('Expected method', '<input class="input" id="suggestion-expected-method" name="expected_method" placeholder="e.g. induction, bisection, adjacency matrix">', '', 'suggestion-expected-method')}
            ${field('Instructor notes', '<input class="input" id="suggestion-instructor-notes" name="instructor_notes" placeholder="What should the grader be careful about?">', '', 'suggestion-instructor-notes')}
          </div>
          <button class="btn btn-primary" type="submit">Generate draft</button>
        </form>
      </details>

      <details class="workspace-card card-pad rubric-section routing-policy" data-rubric-panel="input"${expanded('input')}>
        <summary class="rubric-section-summary"><span><strong>Grading input</strong><small>What the AI can inspect for this question</small></span>${MisraUI.badge(state.gradingMode.replaceAll('_', ' '), 'slate')}</summary>
        <div class="routing-policy-control">
          <div class="field">
            <label for="grading-input-mode">Evidence source</label>
            <select class="input select" id="grading-input-mode">
              <option value="adaptive" ${state.gradingMode === 'adaptive' ? 'selected' : ''}>Adaptive (recommended)</option>
              <option value="image_text_required" ${state.gradingMode === 'image_text_required' ? 'selected' : ''}>Image + text required</option>
              <option value="text_only" ${state.gradingMode === 'text_only' ? 'selected' : ''}>Text only</option>
            </select>
          </div>
          <p class="field-hint" id="grading-input-help">${MisraUI.escapeHTML(gradingModeHelp[state.gradingMode])}</p>
        </div>
      </details>

      <details class="workspace-card card-pad rubric-section" data-rubric-panel="policy"${expanded('policy')}>
        <summary class="rubric-section-summary"><span><strong>Scoring policy</strong><small>How evidence and mistakes affect credit</small></span>${MisraUI.badge(state.rubric.policy.grading_approach, 'slate')}</summary>
        ${draft && state.instructorProfile ? `<button class="btn btn-secondary" type="button" data-apply-instructor-profile>Use my profile v${state.instructorProfile.version_number}</button>` : ''}
        ${state.instructorProfile ? `<p class="field-hint">Your approved profile is only a starting point. Applying it changes this draft in the browser; review and save the rubric to keep it.</p>` : '<p class="field-hint">Optional marking preferences can be set in Settings. They are never applied automatically.</p>'}
        <div class="policy-grid">
          ${field('Assessment scope', `<select class="input select" id="policy-assessment-scope" data-policy="assessment_scope"><option value="paper" ${state.rubric.policy.assessment_scope === 'paper' ? 'selected' : ''}>Grade from this paper</option><option value="external" ${state.rubric.policy.assessment_scope === 'external' ? 'selected' : ''}>Assessed outside MISRA (computer / practical)</option></select><small>External work is not an AI zero. Approval excludes this question from paper totals, paper exports and evaluation. Historical runs remain available.</small>`, '', 'policy-assessment-scope')}
          ${[['language_quality_policy', 'Language quality', [['criterion_specific', 'Follow each criterion'], ['ignore_unless_assessed', 'Ignore unless assessed'], ['assess', 'Assess language quality']]], ['error_carried_forward', 'Carried-forward errors', [['criterion_specific', 'Follow each criterion'], ['single_penalty', 'Penalize the original error once'], ['penalize_each', 'Penalize each affected step']]], ['handwritten_syntax_policy', 'Handwritten syntax', [['criterion_specific', 'Follow each criterion'], ['accept_unambiguous', 'Accept unambiguous intent'], ['require_correct', 'Require correct syntax']]]].map(([key, label, options]) => `<div class="field"><label for="policy-${key}">${label}</label><select id="policy-${key}" class="input select" data-policy="${key}">${options.map(([value, text]) => `<option value="${value}" ${state.rubric.policy[key] === value ? 'selected' : ''}>${text}</option>`).join('')}</select></div>`).join('')}
          ${field('Approach', `<select class="input select" id="policy-grading-approach" data-policy="grading_approach"><option value="lenient" ${state.rubric.policy.grading_approach === 'lenient' ? 'selected' : ''}>Lenient</option><option value="balanced" ${state.rubric.policy.grading_approach === 'balanced' ? 'selected' : ''}>Balanced</option><option value="strict" ${state.rubric.policy.grading_approach === 'strict' ? 'selected' : ''}>Strict</option><option value="custom" ${state.rubric.policy.grading_approach === 'custom' ? 'selected' : ''}>Custom</option></select>`, '', 'policy-grading-approach')}
          ${field('Method credit', `<select class="input select" id="policy-method-credit" data-policy="method_credit"><option value="none" ${state.rubric.policy.method_credit === 'none' ? 'selected' : ''}>None</option><option value="partial" ${state.rubric.policy.method_credit === 'partial' ? 'selected' : ''}>Partial</option><option value="full_if_valid" ${state.rubric.policy.method_credit === 'full_if_valid' ? 'selected' : ''}>Full if valid</option></select>`, '', 'policy-method-credit')}
          ${field('Evidence required', `<select class="input select" id="policy-evidence-requirement" data-policy="evidence_requirement"><option value="final_answer_only" ${state.rubric.policy.evidence_requirement === 'final_answer_only' ? 'selected' : ''}>Final answer only</option><option value="key_steps" ${state.rubric.policy.evidence_requirement === 'key_steps' ? 'selected' : ''}>Key steps</option><option value="complete_reasoning" ${state.rubric.policy.evidence_requirement === 'complete_reasoning' ? 'selected' : ''}>Complete reasoning</option><option value="custom" ${state.rubric.policy.evidence_requirement === 'custom' ? 'selected' : ''}>Custom</option></select>`, '', 'policy-evidence-requirement')}
          ${field('Units', `<select class="input select" id="policy-units" data-policy="units_policy"><option value="required" ${state.rubric.policy.units_policy === 'required' ? 'selected' : ''}>Required</option><option value="required_when_applicable" ${state.rubric.policy.units_policy === 'required_when_applicable' ? 'selected' : ''}>Required when applicable</option><option value="do_not_penalize" ${state.rubric.policy.units_policy === 'do_not_penalize' ? 'selected' : ''}>Do not penalize</option></select>`, '', 'policy-units')}
          ${field('Custom instructions', `<textarea class="input textarea" id="policy-custom-instructions" data-policy="custom_instructions" placeholder="Only needed for a custom approach.">${MisraUI.escapeHTML(state.rubric.policy.custom_instructions || '')}</textarea>`, 'policy-note', 'policy-custom-instructions')}
        </div>
      </details>

      <details class="workspace-card card-pad rubric-section" data-rubric-panel="criteria"${expanded('criteria')}>
        <summary class="rubric-section-summary"><span><strong>Criteria</strong><small><span data-points-total>${total}</span> of ${state.rubric.max_score} points assigned · ${state.rubric.criteria.length} item${state.rubric.criteria.length === 1 ? '' : 's'}</small></span></summary>
        ${draft ? '<div class="rubric-section-actions"><button class="btn btn-secondary" type="button" data-add-criterion>Add criterion</button></div>' : ''}
        <div class="criterion-list">${state.rubric.criteria.map(renderCriterion).join('')}</div>
      </details>

      <details class="workspace-card card-pad rubric-section" data-rubric-panel="history"${expanded('history')}><summary class="rubric-section-summary"><span><strong>Version history</strong><small>${state.versions.length} version${state.versions.length === 1 ? '' : 's'} · approved versions stay immutable</small></span></summary><div class="version-list">${state.versions.map((version) => `<div class="version-row"><div><strong>Version ${version.version_number}</strong><small>${MisraUI.escapeHTML(version.change_summary || `${version.source} rubric`)}</small></div>${MisraUI.badge(version.status, version.status === 'approved' ? 'success' : 'draft')}</div>`).join('')}</div></details>`;
    bindEditor();
    window.MisraAnswerKeys.mount(document.getElementById('answer-key-panel'));
    const criteriaPanel = workspace.querySelector('[data-rubric-panel="criteria"]');
    workspace.querySelector('.rubric-shortcuts').after(criteriaPanel);
    if (!draft) workspace.querySelectorAll('[data-key], [data-policy], [data-reference], [data-remove-criterion]').forEach((control) => { control.disabled = true; });
  }

  function syncEditor() {
    workspace.querySelectorAll('[data-reference]').forEach(input => {
      state.rubric[input.dataset.reference] = input.dataset.reference === 'acceptable_answers'
        ? input.value.split('\n').map(value => value.trim()).filter(Boolean)
        : input.value.trim() || null;
    });
    workspace.querySelectorAll('[data-criterion-index]').forEach((element) => {
      const criterion = state.rubric.criteria[Number(element.dataset.criterionIndex)];
      element.querySelectorAll('[data-key]').forEach((input) => {
        if (input.dataset.key === 'points') criterion.points = Number(input.value);
        else if (input.dataset.key === 'required_evidence') criterion.required_evidence = input.value.split(',').map((item) => item.trim()).filter(Boolean);
        else criterion[input.dataset.key] = input.value;
      });
      criterion.partial_credit_allowed = criterion.scoring_type !== 'binary';
    });
    workspace.querySelectorAll('[data-policy]').forEach((input) => {
      state.rubric.policy[input.dataset.policy] = input.value || null;
    });
  }

  function validateRubric() {
    syncEditor();
    const reveal = name => { const panel = workspace.querySelector(`[data-rubric-panel="${name}"]`); if (panel) panel.open = true; };
    if (!state.rubric.criteria.length) { reveal('criteria'); throw new Error('Add at least one criterion.'); }
    if (state.rubric.criteria.some((criterion) => !criterion.title.trim() || !criterion.description.trim() || criterion.points <= 0)) { reveal('criteria'); throw new Error('Every criterion needs a title, credit description, and positive point value.'); }
    const total = state.rubric.criteria.reduce((sum, criterion) => sum + criterion.points, 0);
    if (Math.abs(total - Number(state.rubric.max_score)) > 0.01) { reveal('criteria'); throw new Error(`Criterion points total ${total}, but this question is worth ${state.rubric.max_score}.`); }
    if (state.rubric.policy.grading_approach === 'custom' && !state.rubric.policy.custom_instructions) { reveal('policy'); throw new Error('Add custom instructions for the custom grading approach.'); }
  }

  async function saveDraft(button) {
    if (savingRubric) return;
    try {
      validateRubric();
      setRubricBusy(true);
      button.disabled = true; button.textContent = 'Saving…';
      state.version = await MisraAPI.updateRubric(state.version.id, { rubric: state.rubric, change_summary: 'Edited in Rubric Studio.' });
      editorDirty = false; setRubricBusy(false);
      await loadQuestion(state.question.id);
      window.showToast('Draft saved.', 'success');
    } catch (error) { window.showToast(error.message, 'error'); button.disabled = false; button.textContent = 'Save draft'; }
    finally { setRubricBusy(false); }
  }

  function bindEditor() {
    workspace.querySelectorAll('[data-rubric-jump]').forEach(button => button.addEventListener('click', () => {
      const panel = workspace.querySelector(`[data-rubric-panel="${button.dataset.rubricJump}"]`);
      panel.open = true;
      panel.scrollIntoView({ block: 'start', behavior: 'auto' });
      panel.querySelector('summary').focus({ preventScroll: true });
    }));
    workspace.querySelector('[data-fold-rubric]')?.addEventListener('click', () => {
      workspace.querySelectorAll('[data-rubric-panel]').forEach(panel => { panel.open = false; });
    });
    workspace.querySelector('[data-apply-instructor-profile]')?.addEventListener('click', () => {
      if (savingRubric || state.version?.status !== 'draft') return;
      if (!window.confirm('Apply your approved preference profile to this rubric draft? Existing draft policy values will be replaced, but nothing is saved until you choose Save draft or Approve.')) return;
      syncEditor();
      const proposal = state.instructorProfile?.derived_proposal || {};
      ['method_credit', 'alternative_methods_allowed', 'handwritten_syntax_policy', 'notation_policy', 'error_carried_forward', 'language_quality_policy'].forEach(key => {
        if (proposal[key] !== undefined && proposal[key] !== null) state.rubric.policy[key] = proposal[key];
      });
      editorDirty = true;
      renderEditor();
      window.showToast('Profile applied to this draft. Review every rule before saving.', 'success');
    });
    workspace.querySelector('#grading-input-mode')?.addEventListener('change', async (event) => {
      const select = event.currentTarget;
      const previousMode = state.gradingMode;
      state.gradingMode = select.value;
      workspace.querySelector('#grading-input-help').textContent = gradingModeHelp[state.gradingMode];
      select.disabled = true;
      try {
        await MisraAPI.updateGradingPolicy(state.question.id, { mode: state.gradingMode });
        window.showToast('Grading input updated.', 'success');
      } catch (error) {
        state.gradingMode = previousMode;
        select.value = previousMode;
        workspace.querySelector('#grading-input-help').textContent = gradingModeHelp[previousMode];
        window.showToast(error.message, 'error');
      } finally {
        select.disabled = false;
      }
    });
    workspace.querySelector('[data-add-criterion]')?.addEventListener('click', () => { if (savingRubric) return; syncEditor(); editorDirty = true; state.rubric.criteria.push(blankCriterion()); renderEditor(); workspace.querySelector(`[data-criterion-index="${state.rubric.criteria.length - 1}"] [data-key="title"]`)?.focus(); });
    workspace.querySelectorAll('[data-remove-criterion]').forEach((button) => button.addEventListener('click', () => { if (savingRubric) return; syncEditor(); editorDirty = true; state.rubric.criteria.splice(Number(button.closest('[data-criterion-index]').dataset.criterionIndex), 1); renderEditor(); }));
    workspace.querySelector('[data-save-rubric]')?.addEventListener('click', (event) => saveDraft(event.currentTarget));
    workspace.querySelector('[data-create-draft]')?.addEventListener('click', async (event) => {
      if (savingRubric) return;
      const button = event.currentTarget;
      setRubricBusy(true); button.textContent = 'Creating…';
      try {
        await MisraAPI.createRubricVersion(state.question.id, { rubric: state.rubric, source: 'manual', change_summary: 'Instructor editing draft.' });
        setRubricBusy(false);
        await loadQuestion(state.question.id); window.showToast('Editable draft created.', 'success');
      } catch (error) { window.showToast(error.message, 'error'); button.textContent = 'Create editable draft'; }
      finally { setRubricBusy(false); }
    });
    workspace.querySelector('[data-approve-rubric]')?.addEventListener('click', async (event) => {
      if (savingRubric) return;
      const button = event.currentTarget;
      try {
        validateRubric();
        setRubricBusy(true);
        button.disabled = true; button.textContent = 'Approving…';
        await MisraAPI.updateRubric(state.version.id, { rubric: state.rubric, change_summary: 'Instructor-approved rubric.' });
        const result = await MisraAPI.approveRubric(state.version.id);
        editorDirty = false; setRubricBusy(false);
        await loadQuestion(state.question.id); window.showToast(result.message || 'Rubric approved.', 'success');
        window.dispatchEvent(new CustomEvent('misra:rubric-approved'));
      } catch (error) { window.showToast(error.message, 'error'); button.disabled = false; button.textContent = 'Approve'; }
      finally { setRubricBusy(false); }
    });
    workspace.querySelector('#suggestion-form')?.addEventListener('submit', async (event) => {
      event.preventDefault(); const button = event.currentTarget.querySelector('[type="submit"]'); const form = new FormData(event.currentTarget);
      if (savingRubric || (editorDirty && !window.confirm('Generate a new draft without saving your current rubric edits?'))) return;
      setRubricBusy(true);
      button.disabled = true; button.textContent = 'Generating…';
      try {
        const body = Object.fromEntries([...form.entries()].filter(([, value]) => String(value).trim()));
        await MisraAPI.suggestRubric(state.question.id, body);
        editorDirty = false; setRubricBusy(false);
        await loadQuestion(state.question.id); window.showToast('AI draft created for review.', 'success');
      } catch (error) { window.showToast(error.message, 'error'); button.disabled = false; button.textContent = 'Generate draft'; }
      finally { setRubricBusy(false); }
    });
  }

  async function loadQuestion(questionId) {
    if (savingQuestion || savingRubric) return;
    if (!window.MisraAnswerKeys.canLeave()) return;
    if (editorDirty && !window.confirm('Discard unsaved rubric edits and open this question?')) return;
    if (renderedQuestionId === questionId) workspace.querySelectorAll('details[data-rubric-panel]').forEach(panel => { openPanels[panel.dataset.rubricPanel] = panel.open; });
    editorDirty = false;
    hideComposer();
    const request = ++questionRequest;
    state.question = state.questions.find((item) => item.id === questionId);
    if (!state.question) return;
    window.MisraAnswerKeys.load(loadedExamId, questionId);
    questionList.querySelectorAll('.question-button').forEach((button) => button.setAttribute('aria-current', String(button.dataset.questionId === questionId)));
    history.replaceState(null, '', `?exam_id=${encodeURIComponent(examSelect.value)}&question_id=${encodeURIComponent(questionId)}`);
    workspace.innerHTML = '<div class="workspace-card card-pad"><div class="skel" style="height:180px"></div></div>';
    try {
      const [active, versions, gradingPolicy] = await Promise.all([
        MisraAPI.rubric(questionId).catch((error) => { if (error.status === 409) return { rubric: {} }; throw error; }),
        MisraAPI.rubricVersions(questionId),
        MisraAPI.gradingPolicy(questionId).catch((error) => {
          if (error.status === 404) return null;
          throw error;
        }),
      ]);
      if (request !== questionRequest) return;
      state.versions = versions;
      state.version = versions.find((version) => version.status === 'draft') || versions.find((version) => version.id === active.rubric_version_id) || versions.find((version) => version.status === 'approved') || null;
      state.rubric = normalizeRubric(state.version?.rubric_json || active.rubric, state.question.max_score);
      persistedRubric = structuredClone(state.rubric);
      state.gradingMode = simpleGradingMode(gradingPolicy?.mode);
      renderEditor();
    } catch (error) { if (request === questionRequest) workspace.innerHTML = `<div class="workspace-card card-pad">${MisraUI.errorState(error.message)}</div>`; }
  }

  async function loadExam(examId, preferredQuestionId = null) {
    window.MisraAnswerKeys.reset();
    renderedQuestionId = '';
    openPanels = {};
    editorDirty = false;
    persistedRubric = null;
    loadedExamId = examId;
    window.dispatchEvent(new CustomEvent('misra:assessment-loaded', { detail: { examId } }));
    questionRequest++;
    state.question = null;
    state.rubric = null;
    state.questions = [];
    openComposer.disabled = true;
    hideComposer();
    uploadLink.href = `upload.html?exam_id=${encodeURIComponent(examId)}`;
    questionList.innerHTML = '<div class="loading-list"><div class="skel loading-row"></div><div class="skel loading-row"></div></div>';
    workspace.innerHTML = `<div class="workspace-card">${MisraUI.emptyState('Loading questions', 'Reading the assessment from MISRA.', MisraUI.icons.rubric)}</div>`;
    try {
      const questions = await MisraAPI.questions(examId);
      if (loadedExamId !== examId) return;
      state.questions = questions;
      if (!document.getElementById('workspace-content').dataset.setupReview || document.getElementById('workspace-content').dataset.setupReview === 'false') {
        document.getElementById('setup-upload-details').open = !questions.length;
      }
      openComposer.disabled = false;
      questionCount.textContent = `${state.questions.length} question${state.questions.length === 1 ? '' : 's'}`;
      questionList.innerHTML = state.questions.length ? state.questions.map((question) => `<button class="question-button" type="button" data-question-id="${question.id}" aria-current="false"><span class="question-number">${MisraUI.escapeHTML(question.question_number)}</span><span class="question-summary">${MisraUI.escapeHTML(question.question_text || 'Question text unavailable')}</span><span class="question-points">${question.max_score} pt</span></button>`).join('') : '<p class="field-hint">Your questions will appear here as you add them.</p>';
      questionList.querySelectorAll('[data-question-id]').forEach((button) => button.addEventListener('click', async () => {
        const questionId = button.dataset.questionId;
        await loadQuestion(questionId);
        if (state.question?.id === questionId && workspace.querySelector('.rubric-toolbar')) workspace.scrollIntoView({ block: 'start' });
      }));
      if (state.questions.length) {
        const requested = preferredQuestionId || MisraUI.getParam('question_id');
        await loadQuestion(state.questions.some((item) => item.id === requested) ? requested : state.questions[0].id);
      } else { renderEditor(); showComposer(false); }
    } catch (error) { if (loadedExamId === examId) { questionList.innerHTML = MisraUI.errorState(error.message); workspace.innerHTML = ''; } }
  }

  window.addEventListener('misra:questions-imported', (event) => {
    if (event.detail.examId === examSelect.value) loadExam(event.detail.examId, event.detail.questionId);
  });

  questionForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (savingQuestion) return;
    if (!examSelect.value) { window.showToast('Choose an assessment first.', 'error'); return; }
    const values = Object.fromEntries(new FormData(questionForm));
    const maxScore = Number(values.max_score);
    const button = event.submitter || questionForm.querySelector('[value="review"]');
    const addAnother = button.value === 'another';
    const examId = loadedExamId;
    formError.hidden = true;
    if (['question_number', 'question_text', 'criterion_title', 'criterion_description'].some((key) => !values[key].trim()) || !Number.isFinite(maxScore) || maxScore <= 0) {
      formError.textContent = 'Enter a question number, full question, positive total marks, and both marking-guide fields.';
      formError.hidden = false; formError.focus(); return;
    }
    if (state.questions.some((q) => q.question_number.trim().toLowerCase() === values.question_number.trim().toLowerCase())) {
      formError.textContent = `Question ${values.question_number.trim()} already exists. Choose a different number or open the existing question.`;
      formError.hidden = false; questionForm.question_number.focus(); return;
    }
    const payload = {
      question_number: values.question_number.trim(),
      question_text: values.question_text.trim(),
      max_score: maxScore,
      language: state.exams.find((exam) => exam.id === examSelect.value)?.language || 'en',
      grading_approach: 'balanced',
      criteria: [{
        title: values.criterion_title.trim(),
        description: values.criterion_description.trim(),
        points: maxScore,
        scoring_type: 'scaled',
        partial_credit_allowed: true,
      }],
    };
    const originalLabel = button.textContent;
    savingQuestion = true;
    questionForm.setAttribute('aria-busy', 'true');
    document.getElementById('question-form-fields').disabled = true;
    questionForm.querySelectorAll('[type="submit"]').forEach((control) => { control.disabled = true; });
    examSelect.disabled = true; closeComposer.disabled = true; openComposer.disabled = true;
    button.textContent = 'Saving question…';
    try {
      const question = await MisraAPI.createQuestion(examId, payload);
      questionForm.reset();
      formDirty = false; savingQuestion = false; applyTemplate.disabled = true;
      formStatus.textContent = `Question ${question.question_number} saved. You can add the next question.`;
      await loadExam(examId, question.id);
      if (addAnother) showComposer();
      else { workspace.setAttribute('tabindex', '-1'); workspace.focus(); workspace.scrollIntoView({ block: 'start' }); }
      window.showToast(`Question ${question.question_number} and its marking guide saved.`, 'success');
    } catch (error) {
      formError.textContent = `${error.message} Your entries are still here. If the connection was interrupted, check the question list before submitting again.`;
      formError.hidden = false; formError.focus();
    } finally {
      savingQuestion = false;
      questionForm.removeAttribute('aria-busy');
      document.getElementById('question-form-fields').disabled = false;
      questionForm.querySelectorAll('[type="submit"]').forEach((control) => { control.disabled = false; });
      examSelect.disabled = false; closeComposer.disabled = false; openComposer.disabled = !loadedExamId;
      button.textContent = originalLabel;
    }
  });

  async function init() {
    try {
      const context = await MisraUI.assessmentReady;
      if (context.error) throw context.error;
      state.exams = context.exams;
      try {
        const profiles = await MisraAPI.instructorPreferenceVersions();
        state.instructorProfile = (Array.isArray(profiles) ? profiles : []).find(profile => profile.status === 'approved') || null;
      } catch (_) { state.instructorProfile = null; }
      examSelect.innerHTML = state.exams.length ? state.exams.map((exam) => `<option value="${exam.id}">${MisraUI.escapeHTML(exam.course_code ? `${exam.course_code} · ${exam.title}` : exam.title)}</option>`).join('') : '<option value="">No assessments found</option>';
      const requested = MisraUI.getParam('exam_id') || context.selectedId;
      if (state.exams.some((exam) => exam.id === requested)) examSelect.value = requested;
      if (examSelect.value) await loadExam(examSelect.value);
      else renderEditor();
      examSelect.addEventListener('change', () => {
        if (formDirty && !window.confirm('Discard this unsaved question and switch assessments?')) { examSelect.value = loadedExamId; return; }
        questionForm.reset(); formDirty = false; formError.hidden = true; formStatus.textContent = ''; applyTemplate.disabled = true;
        loadExam(examSelect.value);
      });
    } catch (error) { examSelect.innerHTML = '<option value="">Engine unavailable</option>'; workspace.innerHTML = `<div class="workspace-card card-pad">${MisraUI.errorState(error.message)}</div>`; }
  }

  init();
})();
