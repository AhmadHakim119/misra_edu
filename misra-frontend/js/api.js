/* MISRA EDU API client. No fake data and no stored auth tokens. */
(function () {
  'use strict';

  const sameOriginApi = window.location.pathname.startsWith('/app/') ? `${window.location.origin}/api` : 'http://127.0.0.1:8000/api';
  const API_BASE = (window.MISRA_API_BASE || sameOriginApi).replace(/\/$/, '');

  function cookie(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    const item = document.cookie.split('; ').find((value) => value.startsWith(prefix));
    return item ? decodeURIComponent(item.slice(prefix.length)) : '';
  }

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      cache: 'no-store',
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(!['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase()) ? { 'X-CSRF-Token': cookie('misra_csrf') } : {}),
        ...(options.headers || {}),
      },
    });

    const contentType = response.headers.get('content-type') || '';
    const responseText = response.status === 204 || response.status === 205
      ? ''
      : await response.text();
    let payload = null;
    if (responseText) {
      payload = contentType.includes('application/json')
        ? JSON.parse(responseText)
        : responseText;
    }

    if (!response.ok) {
      const detail = payload && typeof payload === 'object' ? payload.detail : payload;
      const message = typeof detail === 'string'
        ? detail
        : detail?.message || `Request failed (${response.status})`;
      const error = new Error(message);
      error.status = response.status;
      error.detail = detail;
      if (response.status === 401 && window.location.pathname.includes('/app/pages/') && !window.location.pathname.endsWith('/login.html')) {
        const returnTo = `${window.location.pathname}${window.location.search}`;
        window.location.replace(`login.html?next=${encodeURIComponent(returnTo)}`);
      }
      if (response.status === 403 && detail?.code === 'password_change_required' && !window.location.pathname.endsWith('/account.html')) {
        window.location.replace('account.html?required=1');
      }
      throw error;
    }
    return payload;
  }

  function queryString(values = {}) {
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (value !== undefined && value !== null && String(value) !== '') params.set(key, value);
    });
    const query = params.toString();
    return query ? `?${query}` : '';
  }

  window.MisraAPI = {
    baseUrl: API_BASE,
    health: () => request('/health'),
    currentUser: () => request('/auth/me'),
    logout: () => request('/auth/logout', { method: 'POST', body: '{}' }),
    changePassword: (body) => request('/auth/change-password', { method: 'POST', body: JSON.stringify(body) }),
    instructors: () => request('/admin/instructors'),
    createInstructor: (body) => request('/admin/instructors', { method: 'POST', body: JSON.stringify(body) }),
    updateInstructor: (userId, body) => request(`/admin/instructors/${encodeURIComponent(userId)}`, { method: 'PATCH', body: JSON.stringify(body) }),
    resetInstructorPassword: (userId, body) => request(`/admin/instructors/${encodeURIComponent(userId)}/reset-password`, { method: 'POST', body: JSON.stringify(body) }),
    adminAudit: (filters = {}) => request(`/admin/operations/audit${queryString(filters)}`),
    adminAuditCsvUrl: (filters = {}) => `${API_BASE}/admin/operations/audit.csv${queryString(filters)}`,
    adminJobs: (filters = {}) => request(`/admin/operations/jobs${queryString(filters)}`),
    adminHealth: () => request('/admin/operations/health'),
    recoverOrphanedJobs: () => request('/admin/operations/jobs/recover', { method: 'POST', body: '{}' }),
    courses: () => request('/courses'),
    createCourse: (body) => request('/courses', { method: 'POST', body: JSON.stringify(body) }),
    exams: () => request('/exams'),
    createExam: (body) => request('/exams', { method: 'POST', body: JSON.stringify(body) }),
    questions: (examId) => request(`/exams/${encodeURIComponent(examId)}/questions`),
    createQuestion: (examId, body) => request(`/exams/${encodeURIComponent(examId)}/questions`, { method: 'POST', body: JSON.stringify(body) }),
    rubric: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/rubric`),
    rubricVersions: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/rubric-versions`),
    createRubricVersion: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/rubric-versions`, { method: 'POST', body: JSON.stringify(body) }),
    suggestRubric: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/suggest-rubric-version`, { method: 'POST', body: JSON.stringify(body) }),
    updateRubric: (versionId, body) => request(`/rubric-versions/${encodeURIComponent(versionId)}`, { method: 'PUT', body: JSON.stringify(body) }),
    approveRubric: (versionId) => request(`/rubric-versions/${encodeURIComponent(versionId)}/approve`, { method: 'POST', body: '{}' }),
    gradingPolicy: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/grading-policy`),
    updateGradingPolicy: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/grading-policy`, { method: 'PUT', body: JSON.stringify(body) }),
    uploadExam: (formData) => request('/upload-exam', { method: 'POST', body: formData }),
    uploadBatch: (formData) => request('/upload-batch', { method: 'POST', body: formData }),
    batch: (batchId) => request(`/batches/${encodeURIComponent(batchId)}`),
    job: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}`),
    retryJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST', body: '{}' }),
    submissionJobs: (submissionId, jobType = '') => request(`/submissions/${encodeURIComponent(submissionId)}/jobs${jobType ? `?job_type=${encodeURIComponent(jobType)}` : ''}`),
    submissions: (examId) => request(`/submissions${examId ? `?exam_id=${encodeURIComponent(examId)}` : ''}`),
    deleteSubmission: (submissionId) => request(`/submissions/${encodeURIComponent(submissionId)}`, { method: 'DELETE' }),
    results: (submissionId) => request(`/results/${encodeURIComponent(submissionId)}`),
    extractionReview: (submissionId) => request(`/submissions/${encodeURIComponent(submissionId)}/extraction-review`),
    updateSubmissionMetadata: (submissionId, body) => request(`/submissions/${encodeURIComponent(submissionId)}/metadata`, { method: 'PATCH', body: JSON.stringify(body) }),
    resolveUnmatchedSegment: (submissionId, index, body) => request(`/submissions/${encodeURIComponent(submissionId)}/unmatched-segments/${index}`, { method: 'PUT', body: JSON.stringify(body) }),
    bulkResolveSegments: (submissionId, body) => request(`/submissions/${encodeURIComponent(submissionId)}/segments/bulk-resolve`, { method: 'PUT', body: JSON.stringify(body) }),
    submissionPageUrl: (submissionId, pageIndex) => `${API_BASE}/submissions/${encodeURIComponent(submissionId)}/pages/${pageIndex}`,
    moveAnswerSource: (sourceId, questionId) => request(`/answer-sources/${encodeURIComponent(sourceId)}/question`, { method: 'PUT', body: JSON.stringify({ question_id: questionId }) }),
    removeAnswerSource: (sourceId) => request(`/answer-sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' }),
    previewPageRecovery: (submissionId, pageIndex, questionNumbers) => request(`/submissions/${encodeURIComponent(submissionId)}/pages/${pageIndex}/reextract`, { method: 'POST', body: JSON.stringify({ question_numbers: questionNumbers }) }),
    confirmPageRecovery: (submissionId, pageIndex, preview) => request(`/submissions/${encodeURIComponent(submissionId)}/pages/${pageIndex}/confirm-reextract`, { method: 'POST', body: JSON.stringify({ question_numbers: preview.question_numbers, segments: preview.segments, preview_signature: preview.preview_signature }) }),
    gradeAnswer: (answerId, mode = 'auto') => request(`/grade/${encodeURIComponent(answerId)}`, { method: 'POST', body: JSON.stringify({ mode }) }),
    gradeSubmission: (submissionId, mode = 'auto') => request(`/submissions/${encodeURIComponent(submissionId)}/grade`, { method: 'POST', body: JSON.stringify({ mode }) }),
    reviewQueue: (examId) => request(`/review-queue${examId ? `?exam_id=${encodeURIComponent(examId)}` : ''}`),
    resolveReview: (answerId, body) => request(`/answers/${encodeURIComponent(answerId)}/resolve-review`, { method: 'POST', body: JSON.stringify(body) }),
    evaluation: (examId) => request(`/evaluation${examId ? `?exam_id=${encodeURIComponent(examId)}` : ''}`),
    gradeExportPreflight: (examId, identifier = 'student_number') => request(`/exams/${encodeURIComponent(examId)}/exports/preflight?identifier=${encodeURIComponent(identifier)}`),
    gradeExportCsvUrl: (examId, profile = 'generic', identifier = 'student_number') => `${API_BASE}/exams/${encodeURIComponent(examId)}/exports/grades.csv?profile=${encodeURIComponent(profile)}&identifier=${encodeURIComponent(identifier)}`,
    gradeExportXlsxUrl: (examId) => `${API_BASE}/exams/${encodeURIComponent(examId)}/exports/grades.xlsx`,
  };
})();
