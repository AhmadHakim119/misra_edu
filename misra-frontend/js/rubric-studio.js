(function () {
  'use strict';

  const examSelect = document.getElementById('rubric-exam');
  const questionList = document.getElementById('question-list');
  const questionCount = document.getElementById('question-count');
  const workspace = document.getElementById('rubric-workspace');
  const uploadLink = document.getElementById('upload-link');
  const questionForm = document.getElementById('question-form');
  const state = { exams: [], questions: [], question: null, rubric: null, version: null, versions: [], gradingMode: 'adaptive' };

  const gradingModeHelp = {
    adaptive: 'MISRA uses the original page for diagrams, mathematical working, and other visual evidence. Plain written answers use OCR text only.',
    image_text_required: 'The grader always receives the original source page together with the extracted text.',
    text_only: 'The grader receives extracted text only. Use this for answers where layout, symbols, and markings do not affect credit.',
  };

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
      grading_approach: rubric.policy?.grading_approach || rubric.grading_approach || 'balanced',
      method_credit: rubric.policy?.method_credit || 'partial',
      arithmetic_error_policy: rubric.policy?.arithmetic_error_policy || 'single_penalty',
      rounding_tolerance_percent: rubric.policy?.rounding_tolerance_percent ?? null,
      units_policy: rubric.policy?.units_policy || 'required_when_applicable',
      notation_policy: rubric.policy?.notation_policy || 'equivalent_allowed',
      alternative_methods_allowed: rubric.policy?.alternative_methods_allowed !== false,
      evidence_requirement: rubric.policy?.evidence_requirement || 'key_steps',
      illegible_response_policy: rubric.policy?.illegible_response_policy || 'manual_review',
      custom_instructions: rubric.policy?.custom_instructions || null,
    };
    return rubric;
  }

  function field(label, control, extraClass = '') { return `<div class="field ${extraClass}"><label>${label}</label>${control}</div>`; }

  function renderCriterion(criterion, index) {
    return `<article class="criterion" data-criterion-index="${index}">
      <div class="criterion-head">
        ${field('Criterion title', `<input class="input" data-key="title" value="${MisraUI.escapeHTML(criterion.title)}">`)}
        ${field('Points', `<input class="input numeric" data-key="points" type="number" min="0.01" step="0.25" value="${criterion.points}">`)}
        <button class="icon-button" type="button" data-remove-criterion aria-label="Remove ${MisraUI.escapeHTML(criterion.title)}"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5M14 11v5"/></svg></button>
      </div>
      ${field('What earns credit', `<textarea class="input textarea" data-key="description">${MisraUI.escapeHTML(criterion.description)}</textarea>`)}
      <div class="criterion-fields">
        ${field('Scoring', `<select class="input select" data-key="scoring_type"><option value="scaled" ${criterion.scoring_type === 'scaled' ? 'selected' : ''}>Scaled with partial credit</option><option value="binary" ${criterion.scoring_type === 'binary' ? 'selected' : ''}>Binary, full or zero</option></select>`)}
        ${field('Required evidence', `<input class="input" data-key="required_evidence" value="${MisraUI.escapeHTML((criterion.required_evidence || []).join(', '))}" placeholder="e.g. substitution, final units">`)}
      </div>
    </article>`;
  }

  function renderEditor() {
    if (!state.question || !state.rubric) {
      workspace.innerHTML = `<div class="workspace-card">${MisraUI.emptyState('Select a question', 'Choose an assessment and question to inspect its active rubric.', MisraUI.icons.rubric)}</div>`;
      return;
    }
    const draft = state.version?.status === 'draft';
    const total = state.rubric.criteria.reduce((sum, item) => sum + Number(item.points || 0), 0);
    workspace.innerHTML = `
      <div class="workspace-card rubric-toolbar">
        <div><div class="rubric-toolbar-meta"><strong>Question ${MisraUI.escapeHTML(state.question.question_number)}</strong>${MisraUI.badge(state.version ? `Version ${state.version.version_number}` : 'Legacy rubric', draft ? 'draft' : 'success')}${MisraUI.badge(state.rubric.policy.grading_approach, 'slate')}</div><p class="section-copy">${MisraUI.escapeHTML(state.question.question_text || 'Question text is not available.')}</p></div>
        <div class="rubric-toolbar-actions">
          ${draft ? '<button class="btn btn-secondary" type="button" data-save-rubric>Save draft</button><button class="btn btn-primary" type="button" data-approve-rubric>Approve</button>' : '<button class="btn btn-secondary" type="button" data-create-draft>Create editable draft</button>'}
        </div>
      </div>

      <details class="workspace-card suggestion-panel">
        <summary style="cursor:pointer;font-weight:600">Ask AI for a granular draft</summary>
        <p class="section-copy" style="margin:7px 0 16px">The suggestion is saved as a new draft version. It never becomes active automatically.</p>
        <form id="suggestion-form">
          <div class="suggestion-fields">
            ${field('Grading approach', `<select class="input select" name="grading_approach"><option value="lenient">Lenient</option><option value="balanced" selected>Balanced</option><option value="strict">Strict</option></select>`)}
            ${field('Course level', '<input class="input" name="course_level" placeholder="e.g. undergraduate, year 2">')}
            ${field('Answer key or expected answer', '<textarea class="input textarea" name="answer_key" placeholder="Paste the instructor answer or key details."></textarea>', 'wide')}
            ${field('Expected method', '<input class="input" name="expected_method" placeholder="e.g. induction, bisection, adjacency matrix">')}
            ${field('Instructor notes', '<input class="input" name="instructor_notes" placeholder="What should the grader be careful about?">')}
          </div>
          <button class="btn btn-primary" type="submit">Generate draft</button>
        </form>
      </details>

      <section class="workspace-card card-pad routing-policy">
        <div class="section-head"><div><h2 class="section-title">Grading input</h2><p class="section-copy">Choose what the AI can inspect for this question.</p></div></div>
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
      </section>

      <section class="workspace-card card-pad">
        <div class="section-head"><div><h2 class="section-title">Scoring policy</h2><p class="section-copy">Controls how evidence and mistakes affect credit.</p></div></div>
        <div class="policy-grid">
          ${field('Approach', `<select class="input select" data-policy="grading_approach"><option value="lenient" ${state.rubric.policy.grading_approach === 'lenient' ? 'selected' : ''}>Lenient</option><option value="balanced" ${state.rubric.policy.grading_approach === 'balanced' ? 'selected' : ''}>Balanced</option><option value="strict" ${state.rubric.policy.grading_approach === 'strict' ? 'selected' : ''}>Strict</option><option value="custom" ${state.rubric.policy.grading_approach === 'custom' ? 'selected' : ''}>Custom</option></select>`)}
          ${field('Method credit', `<select class="input select" data-policy="method_credit"><option value="none" ${state.rubric.policy.method_credit === 'none' ? 'selected' : ''}>None</option><option value="partial" ${state.rubric.policy.method_credit === 'partial' ? 'selected' : ''}>Partial</option><option value="full_if_valid" ${state.rubric.policy.method_credit === 'full_if_valid' ? 'selected' : ''}>Full if valid</option></select>`)}
          ${field('Evidence required', `<select class="input select" data-policy="evidence_requirement"><option value="final_answer_only" ${state.rubric.policy.evidence_requirement === 'final_answer_only' ? 'selected' : ''}>Final answer only</option><option value="key_steps" ${state.rubric.policy.evidence_requirement === 'key_steps' ? 'selected' : ''}>Key steps</option><option value="complete_reasoning" ${state.rubric.policy.evidence_requirement === 'complete_reasoning' ? 'selected' : ''}>Complete reasoning</option><option value="custom" ${state.rubric.policy.evidence_requirement === 'custom' ? 'selected' : ''}>Custom</option></select>`)}
          ${field('Units', `<select class="input select" data-policy="units_policy"><option value="required" ${state.rubric.policy.units_policy === 'required' ? 'selected' : ''}>Required</option><option value="required_when_applicable" ${state.rubric.policy.units_policy === 'required_when_applicable' ? 'selected' : ''}>Required when applicable</option><option value="do_not_penalize" ${state.rubric.policy.units_policy === 'do_not_penalize' ? 'selected' : ''}>Do not penalize</option></select>`)}
          ${field('Custom instructions', `<textarea class="input textarea" data-policy="custom_instructions" placeholder="Only needed for a custom approach.">${MisraUI.escapeHTML(state.rubric.policy.custom_instructions || '')}</textarea>`, 'policy-note')}
        </div>
      </section>

      <section class="workspace-card card-pad">
        <div class="section-head"><div><h2 class="section-title">Criteria</h2><p class="section-copy"><span data-points-total>${total}</span> of ${state.rubric.max_score} points assigned</p></div>${draft ? '<button class="btn btn-secondary" type="button" data-add-criterion>Add criterion</button>' : ''}</div>
        <div class="criterion-list">${state.rubric.criteria.map(renderCriterion).join('')}</div>
      </section>

      <section class="workspace-card card-pad"><div class="section-head"><div><h2 class="section-title">Version history</h2><p class="section-copy">Approved versions remain immutable and grading runs keep their snapshots.</p></div></div><div class="version-list">${state.versions.map((version) => `<div class="version-row"><div><strong>Version ${version.version_number}</strong><small>${MisraUI.escapeHTML(version.change_summary || `${version.source} rubric`)}</small></div>${MisraUI.badge(version.status, version.status === 'approved' ? 'success' : 'draft')}</div>`).join('')}</div></section>`;
    bindEditor();
    if (!draft) workspace.querySelectorAll('[data-key], [data-policy], [data-remove-criterion]').forEach((control) => { control.disabled = true; });
  }

  function syncEditor() {
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
    if (!state.rubric.criteria.length) throw new Error('Add at least one criterion.');
    if (state.rubric.criteria.some((criterion) => !criterion.title.trim() || !criterion.description.trim() || criterion.points <= 0)) throw new Error('Every criterion needs a title, credit description, and positive point value.');
    const total = state.rubric.criteria.reduce((sum, criterion) => sum + criterion.points, 0);
    if (Math.abs(total - Number(state.rubric.max_score)) > 0.01) throw new Error(`Criterion points total ${total}, but this question is worth ${state.rubric.max_score}.`);
    if (state.rubric.policy.grading_approach === 'custom' && !state.rubric.policy.custom_instructions) throw new Error('Add custom instructions for the custom grading approach.');
  }

  async function saveDraft(button) {
    try {
      validateRubric();
      button.disabled = true; button.textContent = 'Saving…';
      state.version = await MisraAPI.updateRubric(state.version.id, { rubric: state.rubric, change_summary: 'Edited in Rubric Studio.' });
      await loadQuestion(state.question.id);
      window.showToast('Draft saved.', 'success');
    } catch (error) { window.showToast(error.message, 'error'); button.disabled = false; button.textContent = 'Save draft'; }
  }

  function bindEditor() {
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
    workspace.querySelector('[data-add-criterion]')?.addEventListener('click', () => { syncEditor(); state.rubric.criteria.push(blankCriterion()); renderEditor(); });
    workspace.querySelectorAll('[data-remove-criterion]').forEach((button) => button.addEventListener('click', () => { syncEditor(); state.rubric.criteria.splice(Number(button.closest('[data-criterion-index]').dataset.criterionIndex), 1); renderEditor(); }));
    workspace.querySelector('[data-save-rubric]')?.addEventListener('click', (event) => saveDraft(event.currentTarget));
    workspace.querySelector('[data-create-draft]')?.addEventListener('click', async (event) => {
      event.currentTarget.disabled = true; event.currentTarget.textContent = 'Creating…';
      try {
        await MisraAPI.createRubricVersion(state.question.id, { rubric: state.rubric, source: 'manual', change_summary: 'Instructor editing draft.' });
        await loadQuestion(state.question.id); window.showToast('Editable draft created.', 'success');
      } catch (error) { window.showToast(error.message, 'error'); event.currentTarget.disabled = false; event.currentTarget.textContent = 'Create editable draft'; }
    });
    workspace.querySelector('[data-approve-rubric]')?.addEventListener('click', async (event) => {
      try {
        validateRubric();
        event.currentTarget.disabled = true; event.currentTarget.textContent = 'Approving…';
        await MisraAPI.updateRubric(state.version.id, { rubric: state.rubric, change_summary: 'Instructor-approved rubric.' });
        const result = await MisraAPI.approveRubric(state.version.id);
        await loadQuestion(state.question.id); window.showToast(result.message || 'Rubric approved.', 'success');
      } catch (error) { window.showToast(error.message, 'error'); event.currentTarget.disabled = false; event.currentTarget.textContent = 'Approve'; }
    });
    workspace.querySelector('#suggestion-form')?.addEventListener('submit', async (event) => {
      event.preventDefault(); const button = event.currentTarget.querySelector('[type="submit"]'); const form = new FormData(event.currentTarget);
      button.disabled = true; button.textContent = 'Generating…';
      try {
        const body = Object.fromEntries([...form.entries()].filter(([, value]) => String(value).trim()));
        await MisraAPI.suggestRubric(state.question.id, body);
        await loadQuestion(state.question.id); window.showToast('AI draft created for review.', 'success');
      } catch (error) { window.showToast(error.message, 'error'); button.disabled = false; button.textContent = 'Generate draft'; }
    });
  }

  async function loadQuestion(questionId) {
    state.question = state.questions.find((item) => item.id === questionId);
    questionList.querySelectorAll('.question-button').forEach((button) => button.setAttribute('aria-current', String(button.dataset.questionId === questionId)));
    history.replaceState(null, '', `?exam_id=${encodeURIComponent(examSelect.value)}&question_id=${encodeURIComponent(questionId)}`);
    workspace.innerHTML = '<div class="workspace-card card-pad"><div class="skel" style="height:180px"></div></div>';
    try {
      const [active, versions, gradingPolicy] = await Promise.all([
        MisraAPI.rubric(questionId),
        MisraAPI.rubricVersions(questionId),
        MisraAPI.gradingPolicy(questionId).catch((error) => {
          if (error.status === 404) return null;
          throw error;
        }),
      ]);
      state.versions = versions;
      state.version = versions.find((version) => version.status === 'draft') || versions.find((version) => version.id === active.rubric_version_id) || null;
      state.rubric = normalizeRubric(state.version?.rubric_json || active.rubric, state.question.max_score);
      state.gradingMode = simpleGradingMode(gradingPolicy?.mode);
      renderEditor();
    } catch (error) { workspace.innerHTML = `<div class="workspace-card card-pad">${MisraUI.errorState(error.message)}</div>`; }
  }

  async function loadExam(examId) {
    uploadLink.href = `upload.html?exam_id=${encodeURIComponent(examId)}`;
    questionList.innerHTML = '<div class="loading-list"><div class="skel loading-row"></div><div class="skel loading-row"></div></div>';
    workspace.innerHTML = `<div class="workspace-card">${MisraUI.emptyState('Loading questions', 'Reading the assessment from MISRA.', MisraUI.icons.rubric)}</div>`;
    try {
      state.questions = await MisraAPI.questions(examId);
      questionCount.textContent = `${state.questions.length} question${state.questions.length === 1 ? '' : 's'}`;
      questionList.innerHTML = state.questions.length ? state.questions.map((question) => `<button class="question-button" type="button" data-question-id="${question.id}" aria-current="false"><span class="question-number">${MisraUI.escapeHTML(question.question_number)}</span><span class="question-summary">${MisraUI.escapeHTML(question.question_text || 'Question text unavailable')}</span><span class="question-points">${question.max_score} pt</span></button>`).join('') : MisraUI.emptyState('No questions', 'Add questions before creating a rubric.');
      questionList.querySelectorAll('[data-question-id]').forEach((button) => button.addEventListener('click', () => loadQuestion(button.dataset.questionId)));
      if (state.questions.length) {
        const requested = MisraUI.getParam('question_id');
        await loadQuestion(state.questions.some((item) => item.id === requested) ? requested : state.questions[0].id);
      }
    } catch (error) { questionList.innerHTML = MisraUI.errorState(error.message); workspace.innerHTML = ''; }
  }

  questionForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!examSelect.value) { window.showToast('Choose an assessment first.', 'error'); return; }
    const values = Object.fromEntries(new FormData(questionForm));
    const maxScore = Number(values.max_score);
    const button = questionForm.querySelector('[type="submit"]');
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
    button.disabled = true; button.textContent = 'Adding…';
    try {
      const question = await MisraAPI.createQuestion(examSelect.value, payload);
      questionForm.reset();
      await loadExam(examSelect.value);
      await loadQuestion(question.id);
      window.showToast('Question and initial rubric created.', 'success');
    } catch (error) { window.showToast(error.message, 'error'); }
    finally { button.disabled = false; button.textContent = 'Add question'; }
  });

  async function init() {
    try {
      state.exams = await MisraAPI.exams();
      examSelect.innerHTML = state.exams.length ? state.exams.map((exam) => `<option value="${exam.id}">${MisraUI.escapeHTML(exam.course_code ? `${exam.course_code} · ${exam.title}` : exam.title)}</option>`).join('') : '<option value="">No assessments found</option>';
      const requested = MisraUI.getParam('exam_id');
      if (state.exams.some((exam) => exam.id === requested)) examSelect.value = requested;
      if (examSelect.value) await loadExam(examSelect.value);
      else renderEditor();
      examSelect.addEventListener('change', () => loadExam(examSelect.value));
    } catch (error) { examSelect.innerHTML = '<option value="">Engine unavailable</option>'; workspace.innerHTML = `<div class="workspace-card card-pad">${MisraUI.errorState(error.message)}</div>`; }
  }

  init();
})();
