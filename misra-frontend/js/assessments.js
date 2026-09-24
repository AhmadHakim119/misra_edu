(async function () {
  'use strict';
  const host = document.getElementById('assessment-table');
  const form = document.getElementById('assessment-form');
  const courseForm = document.getElementById('course-form');
  const courseSelect = document.getElementById('assessment-course');
  // Existing work leads; creation remains reachable through New assessment.
  document.getElementById('workspace-content').append(document.querySelector('.setup-stack'));
  let courses = [];

  function courseLabel(course) {
    const identity = course.course_code ? `${course.course_code} · ${course.title}` : course.title;
    return course.term ? `${identity} · ${course.term}` : identity;
  }

  function renderCourses(selectedCourseId) {
    const options = courses.map((course) => `<option value="${course.id}">${MisraUI.escapeHTML(courseLabel(course))}</option>`).join('');
    const empty = '<option value="">No courses found</option>';
    courseSelect.innerHTML = options || empty;
    if (selectedCourseId && courses.some((course) => course.id === selectedCourseId)) courseSelect.value = selectedCourseId;
  }

  async function loadCourses(selectedCourseId) {
    try {
      courses = await MisraAPI.courses();
      renderCourses(selectedCourseId);
    } catch (error) {
      courseSelect.innerHTML = '<option value="">Courses unavailable</option>';
      window.showToast('Courses could not be loaded. Try refreshing the page.', 'error');
    }
  }

  courseForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = courseForm.querySelector('[type="submit"]');
    const body = Object.fromEntries(new FormData(courseForm));
    body.course_code = body.course_code.trim();
    body.title = body.title.trim();
    body.term = body.term.trim() || null;
    body.instructor_name = body.instructor_name.trim() || null;
    button.disabled = true; button.textContent = 'Creating…';
    try {
      const course = await MisraAPI.createCourse(body);
      courseForm.reset();
      await loadCourses(course.id);
      document.getElementById('new-course').open = false;
      document.getElementById('new-assessment').open = true;
      document.getElementById('assessment-title').focus();
      window.showToast(`${courseLabel(course)} created.`, 'success');
    } catch (error) {
      window.showToast(error.status === 409 ? 'That course already exists. Select it below.' : error.message, 'error');
    } finally {
      button.disabled = false; button.textContent = 'Create course';
    }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault(); const button = form.querySelector('[type="submit"]'); const body = Object.fromEntries(new FormData(form));
    button.disabled = true; button.textContent = 'Creating…';
    try {
      const exam = await MisraAPI.createExam(body);
      window.showToast('Assessment created. Add its questions next.', 'success');
      window.location.href = `rubric-studio.html?exam_id=${encodeURIComponent(exam.id)}`;
    } catch (error) { window.showToast(error.message, 'error'); button.disabled = false; button.textContent = 'Create assessment'; }
  });

  const search = document.getElementById('assessment-search');
  const filter = document.getElementById('assessment-filter');
  const count = document.getElementById('assessment-count');
  const refresh = document.getElementById('assessment-refresh');
  const esc = value => MisraUI.escapeHTML(String(value ?? ''));
  let exams = [], index = null, selectedId = MisraUI.getParam('exam_id') || '', requestNumber = 0;
  const href = (page, id) => `${page}.html?exam_id=${encodeURIComponent(id)}`;
  const needsSetup = exam => !exam.question_count || (exam.approved_question_count != null && exam.approved_question_count < exam.question_count);

  function openCreation() {
    document.getElementById('new-assessment').open = true;
    document.getElementById('assessment-title').focus();
  }
  document.getElementById('create-assessment-toggle').addEventListener('click', openCreation);
  if (location.hash === '#new-assessment') openCreation();

  function nextAction(exam) {
    if (needsSetup(exam)) return ['Finish setup', 'rubric-studio'];
    if (exam.review_count) return ['Review grades', 'reviews'];
    if (exam.submission_count) return ['Open student papers', 'submissions'];
    return ['Upload student answers', 'upload'];
  }

  function render() {
    const term = search.value.trim();
    let visible = term ? (index ? index.search(term).map(match => match.item) : exams.filter(e =>
      [e.title, e.course_code, e.course_title, e.term].join(' ').toLowerCase().includes(term.toLowerCase()))) : exams;
    visible = visible.filter(e => filter.value === 'all' || (filter.value === 'setup' && needsSetup(e)) ||
      (filter.value === 'review' && e.review_count > 0) || (filter.value === 'papers' && e.submission_count > 0));
    count.textContent = `${visible.length} of ${exams.length} assessment${exams.length === 1 ? '' : 's'} · grouped by course`;
    if (!visible.length) {
      host.innerHTML = `<div class="workspace-card card-pad">${MisraUI.emptyState(exams.length ? 'No matching assessments' : 'Start with your first assessment', exams.length ? 'Try a shorter search or reset the filters.' : 'Create a course, add an assessment, then bring your exam and marking rules into Rubric Studio.')}<button type="button" class="btn btn-secondary" data-empty-action>${exams.length ? 'Reset filters' : 'Create an assessment'}</button></div>`;
      host.querySelector('[data-empty-action]').onclick = () => { if (exams.length) { search.value = ''; filter.value = 'all'; render(); search.focus(); } else openCreation(); };
      return;
    }
    const groups = new Map();
    visible.forEach(exam => {
      const key = exam.course_id || exam.course_code || 'unassigned';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(exam);
    });
    host.innerHTML = [...groups.values()].map(group => `<section class="assessment-course-group">
      <h3>${esc([group[0].course_code, group[0].course_title].filter(Boolean).join(' · ') || 'Unassigned course')}<span>${esc(group[0].term || '')}</span></h3>
      <div class="workspace-card assessment-items">${group.map(exam => {
        const [action, page] = nextAction(exam);
        return `<article class="assessment-item" data-exam="${esc(exam.id)}">
          <div class="assessment-item-header"><div class="assessment-item-name"><h4><button type="button" class="assessment-open" data-open="${esc(exam.id)}" aria-expanded="false" aria-controls="workspace-${esc(exam.id)}">${esc(exam.title)}</button></h4>
          <p class="section-copy">${Number(exam.question_count) || 0} questions · ${Number(exam.submission_count) || 0} student papers${exam.approved_question_count == null ? '' : ` · ${Number(exam.approved_question_count)} rubrics approved`}</p></div>
          ${MisraUI.badge(needsSetup(exam) ? 'Setup needed' : exam.review_count ? `${exam.review_count} to review` : 'View workflow', needsSetup(exam) || exam.review_count ? 'warning' : 'neutral')}
          <a class="btn btn-secondary" href="${href(page, exam.id)}">${action}</a></div>
          <div id="workspace-${esc(exam.id)}" class="assessment-workspace" hidden></div>
        </article>`;
      }).join('')}</div></section>`).join('');
    host.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => {
      selectedId = selectedId === button.dataset.open ? '' : button.dataset.open;
      history.replaceState(null, '', selectedId ? `?exam_id=${encodeURIComponent(selectedId)}` : location.pathname);
      expandSelected();
    }));
    expandSelected();
  }

  function expandSelected() {
    requestNumber++;
    const token = requestNumber;
    host.querySelectorAll('[data-exam]').forEach(article => {
      const selected = article.dataset.exam === selectedId;
      const panel = article.querySelector('.assessment-workspace');
      article.querySelector('[data-open]').setAttribute('aria-expanded', String(selected));
      panel.hidden = !selected;
      if (!selected) { panel.replaceChildren(); return; }
      const exam = exams.find(item => item.id === selectedId);
      panel.innerHTML = `<nav class="assessment-workflow" aria-label="${esc(exam.title)} workflow">
        ${[['rubric-studio', '1. Marking rules', 'Questions, reference answers and rubrics'], ['submissions', '2. Student papers', 'Check extraction and start grading'], ['grades', '3. Grades & export', 'Inspect scores and download results']].map(([page, title, description]) => `<a href="${href(page, exam.id)}"><strong>${title}</strong><span>${description}</span></a>`).join('')}
        </nav><div class="assessment-preflight" aria-live="polite" aria-busy="true"><p>Checking approved rubrics and question marks…</p></div>
        <div class="assessment-workspace-footer"><a class="link-button" href="${href('reviews', exam.id)}">Review queue${exam.review_count ? ` (${Number(exam.review_count)})` : ''}</a><button type="button" class="link-button" data-duplicate>Duplicate assessment</button><p class="section-copy">Duplication reuses approved rubrics, not student papers or grades.</p></div>`;
      panel.querySelector('[data-duplicate]').onclick = event => duplicate(exam, event.currentTarget);
      const preflight = panel.querySelector('.assessment-preflight');
      const loadChecks = async () => {
        preflight.setAttribute('aria-busy', 'true');
        preflight.textContent = 'Checking approved rubrics and question marks…';
        try {
          const checks = await MisraAPI.setupReadiness(exam.id);
          if (requestNumber !== token || !panel.isConnected) return;
          preflight.innerHTML = MisraAssessmentChecks.render(checks, exam.id);
        } catch (error) {
          if (requestNumber !== token || !panel.isConnected) return;
          preflight.innerHTML = `<p role="alert">Could not check setup: ${esc(error.message)}</p><button type="button" class="btn btn-secondary">Retry checks</button>`;
          preflight.querySelector('button').onclick = loadChecks;
        } finally { preflight.setAttribute('aria-busy', 'false'); }
      };
      loadChecks();
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches) panel.animate(
        [{ opacity: .7, transform: 'translateY(-4px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 180, easing: 'ease-out' });
    });
  }

  async function duplicate(exam, button) {
    const title = window.prompt('Name the copy. Student papers and grades will not be copied.', `${exam.title} — copy`);
    if (!title?.trim()) return;
    button.disabled = true; button.textContent = 'Duplicating…';
    try {
      const result = await MisraAPI.duplicateExam(exam.id, { title: title.trim(), include_rubrics: true, include_grading_policies: true });
      location.href = href('rubric-studio', result.exam.id);
    } catch (error) { button.disabled = false; button.textContent = 'Duplicate assessment'; window.showToast(error.message, 'error'); }
  }

  async function loadCatalog() {
    refresh.disabled = true; refresh.textContent = 'Refreshing…';
    host.setAttribute('aria-busy', 'true'); requestNumber++;
    try {
      exams = await MisraAPI.exams();
      index = window.Fuse ? new Fuse(exams, { keys: ['title', 'course_code', 'course_title', 'term'], threshold: .32, ignoreLocation: true }) : null;
      render();
    } catch (error) {
      count.textContent = 'Assessments unavailable';
      host.innerHTML = `<div class="workspace-card card-pad"><p role="alert">${esc(error.message)}</p><p>Use Refresh to reconnect. Existing assessments have not been changed.</p></div>`;
    } finally { refresh.disabled = false; refresh.textContent = 'Refresh'; host.setAttribute('aria-busy', 'false'); }
  }
  search.addEventListener('input', render);
  filter.addEventListener('change', render);
  refresh.addEventListener('click', loadCatalog);
  loadCourses();
  await loadCatalog();
})();
