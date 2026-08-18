(async function () {
  'use strict';
  const host = document.getElementById('assessment-table');
  const form = document.getElementById('assessment-form');
  const courseForm = document.getElementById('course-form');
  const courseSelect = document.getElementById('assessment-course');
  const ownerSelect = document.getElementById('course-owner');
  let courses = [];

  function courseLabel(course) {
    const identity = course.course_code ? `${course.course_code} · ${course.title}` : course.title;
    return course.term ? `${identity} · ${course.term}` : identity;
  }

  function renderCourses(selectedCourseId) {
    const options = courses.map((course) => `<option value="${course.id}">${MisraUI.escapeHTML(courseLabel(course))}</option>`).join('');
    const empty = '<option value="">No courses found</option>';
    courseSelect.innerHTML = options || empty;
    ownerSelect.innerHTML = options || '<option value="">Create the first course through authenticated setup</option>';
    if (selectedCourseId && courses.some((course) => course.id === selectedCourseId)) courseSelect.value = selectedCourseId;
  }

  async function loadCourses(selectedCourseId) {
    try {
      courses = await MisraAPI.courses();
      renderCourses(selectedCourseId);
    } catch (error) {
      courseSelect.innerHTML = '<option value="">Courses unavailable</option>';
      ownerSelect.innerHTML = '<option value="">Ownership profiles unavailable</option>';
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

  loadCourses();
  try {
    const exams = await MisraAPI.exams();
    if (!exams.length) {
      host.innerHTML = MisraUI.emptyState('No assessments found', 'The catalog will populate as soon as an assessment exists in the database.');
      return;
    }
    host.innerHTML = `<table class="assessment-table"><thead><tr><th>Assessment</th><th>Course</th><th>Questions</th><th>Submissions</th><th>Review</th><th></th></tr></thead><tbody>${exams.map((exam) => `<tr>
      <td data-label="Assessment"><strong>${MisraUI.escapeHTML(exam.title)}</strong><div class="data-row-meta">${MisraUI.formatDate(exam.created_at)}</div></td>
      <td data-label="Course">${MisraUI.escapeHTML(exam.course_code || exam.course_title || 'Not labeled')}</td>
      <td data-label="Questions" class="numeric">${exam.question_count}</td>
      <td data-label="Submissions" class="numeric">${exam.submission_count}</td>
      <td data-label="Review">${exam.review_count ? MisraUI.badge(`${exam.review_count} pending`, 'warning') : MisraUI.badge('Clear', 'success')}</td>
      <td><div class="data-row-actions"><a class="link-button" href="rubric-studio.html?exam_id=${encodeURIComponent(exam.id)}">Rubrics</a><a class="link-button" href="upload.html?exam_id=${encodeURIComponent(exam.id)}">Upload</a></div></td>
    </tr>`).join('')}</tbody></table>`;
  } catch (error) {
    host.innerHTML = `<div class="card-pad">${MisraUI.errorState(error.message)}</div>`;
  }
})();
