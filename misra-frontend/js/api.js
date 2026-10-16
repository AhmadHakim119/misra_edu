/* MISRA EDU API client. No fake data and no stored auth tokens. */
(function () {
  'use strict';

  const native = window.location.pathname.startsWith('/app/') && !window.location.pathname.startsWith('/app/pages/');
  const legacy = window.location.pathname.startsWith('/legacy/') || window.location.pathname.startsWith('/app/pages/');
  const authRoot = native ? '/app/' : window.location.pathname.startsWith('/legacy/') ? '/legacy/pages/' : '/app/pages/';
  const sameOriginApi = native || legacy ? `${window.location.origin}/api` : 'http://127.0.0.1:8000/api';
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
      if (response.status === 401 && (native || legacy) && !window.location.pathname.endsWith('/login.html')) {
        const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        window.location.replace(`${authRoot}login.html?next=${encodeURIComponent(returnTo)}`);
      }
      if (response.status === 403 && detail?.code === 'password_change_required' && !window.location.pathname.endsWith('/account.html')) {
        window.location.replace(`${authRoot}account.html?required=1`);
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
    instructorPreferenceVersions: () => request('/instructor-preference-versions'),
    instructorPreferenceSuggestions: () => request('/instructor-preference-suggestions'),
    createInstructorPreference: (body) => request('/instructor-preference-versions', { method: 'POST', body: JSON.stringify(body) }),
    updateInstructorPreference: (versionId, body) => request(`/instructor-preference-versions/${encodeURIComponent(versionId)}`, { method: 'PUT', body: JSON.stringify(body) }),
    approveInstructorPreference: (versionId) => request(`/instructor-preference-versions/${encodeURIComponent(versionId)}/approve`, { method: 'POST', body: '{}' }),
    accountSettings: () => request('/auth/settings'),
    saveAccountSettings: (body) => request('/auth/settings', {method:'PUT',body:JSON.stringify(body)}),
    deleteAccount: (body) => request('/auth/account', {method:'DELETE',body:JSON.stringify(body)}),
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
    courseMaterials: (courseId) => request(`/courses/${encodeURIComponent(courseId)}/materials${queryString({exam_id:native ? new URLSearchParams(window.location.search).get('exam_id') : null})}`),
    courseLibrary: (courseId, examId) => request(`/courses/${encodeURIComponent(courseId)}/library${queryString({exam_id:examId})}`),
    materialChapters: (materialId, versionId) => request(`/materials/${encodeURIComponent(materialId)}/versions/${encodeURIComponent(versionId)}/chapters`),
    saveMaterialChapters: (materialId, versionId, body) => request(`/materials/${encodeURIComponent(materialId)}/versions/${encodeURIComponent(versionId)}/chapters`, {method:'POST',body:JSON.stringify(body)}),
    readScannedMaterial: (materialId, versionId) => request(`/materials/${encodeURIComponent(materialId)}/versions/${encodeURIComponent(versionId)}/read-scanned-pages`, {method:'POST',body:'{}'}),
    uploadAssessmentMaterial: (examId, body) => request(`/exams/${encodeURIComponent(examId)}/materials`, {method:'POST',body}),
    createMaterialText: (courseId, body) => request(`/courses/${encodeURIComponent(courseId)}/materials/text`, { method: 'POST', body: JSON.stringify(body) }),
    uploadMaterial: (courseId, body) => request(`/courses/${encodeURIComponent(courseId)}/materials`, { method: 'POST', body }),
    uploadMaterialRevision: (materialId, body) => request(`/materials/${encodeURIComponent(materialId)}/versions`, { method: 'POST', body }),
    materialPages: (materialId, versionId, offset = 0, limit = 1) => request(`/materials/${encodeURIComponent(materialId)}/versions/${encodeURIComponent(versionId)}/pages${queryString({ offset, limit })}`),
    editMaterialPage: (materialId, versionId, pageIndex, body) => request(`/materials/${encodeURIComponent(materialId)}/versions/${encodeURIComponent(versionId)}/pages/${pageIndex}`, { method: 'PUT', body: JSON.stringify(body) }),
    approveMaterial: (materialId, versionId, body) => request(`/materials/${encodeURIComponent(materialId)}/versions/${encodeURIComponent(versionId)}/approve`, { method: 'POST', body: JSON.stringify(body) }),
    materialDocumentUrl: (materialId, versionId) => `${API_BASE}/materials/${encodeURIComponent(materialId)}/versions/${encodeURIComponent(versionId)}/document`,
    materialScopes: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/material-scopes`),
    createMaterialScope: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/material-scopes`, { method: 'POST', body: JSON.stringify(body) }),
    approveMaterialScope: (questionId, scopeId) => request(`/questions/${encodeURIComponent(questionId)}/material-scopes/${encodeURIComponent(scopeId)}/approve`, { method: 'POST', body: '{}' }),
    materialRetrievalPreview: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/material-retrieval-preview`),
    effectiveMaterialScope: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/effective-material-scope`),
    assessmentMaterialScopes: (examId) => request(`/exams/${encodeURIComponent(examId)}/material-scopes`),
    createAssessmentMaterialScope: (examId, body) => request(`/exams/${encodeURIComponent(examId)}/material-scopes`, { method: 'POST', body: JSON.stringify(body) }),
    approveAssessmentMaterialScope: (examId, scopeId) => request(`/exams/${encodeURIComponent(examId)}/material-scopes/${encodeURIComponent(scopeId)}/approve`, { method: 'POST', body: '{}' }),
    createCourse: (body) => request('/courses', { method: 'POST', body: JSON.stringify(body) }),
    exams: () => request('/exams'),
    createExam: (body) => request('/exams', { method: 'POST', body: JSON.stringify(body) }),
    duplicateExam: (examId, body) => request(`/exams/${encodeURIComponent(examId)}/duplicate`, { method: 'POST', body: JSON.stringify(body) }),
    questions: (examId) => request(`/exams/${encodeURIComponent(examId)}/questions`),
    deleteQuestion: (questionId) => request(`/questions/${encodeURIComponent(questionId)}`, {method:'DELETE'}),
    setupReadiness: (examId) => request(`/exams/${encodeURIComponent(examId)}/setup-readiness`),
    setupImports: (examId) => request(`/exams/${encodeURIComponent(examId)}/setup-imports`),
    learningInsights: (examId) => request(`/exams/${encodeURIComponent(examId)}/learning-insights`),
    setupImport: (examId, jobId) => request(`/exams/${encodeURIComponent(examId)}/setup-imports/${encodeURIComponent(jobId)}`),
    uploadSetup: (examId, body) => request(`/exams/${encodeURIComponent(examId)}/setup-imports`, { method: 'POST', body }),
    confirmSetup: (examId, jobId, body) => request(`/exams/${encodeURIComponent(examId)}/setup-imports/${encodeURIComponent(jobId)}/confirm`, { method: 'POST', body: JSON.stringify(body) }),
    setupDocumentUrl: (examId, jobId, index) => `${API_BASE}/exams/${encodeURIComponent(examId)}/setup-imports/${encodeURIComponent(jobId)}/documents/${index}`,
    createQuestion: (examId, body) => request(`/exams/${encodeURIComponent(examId)}/questions`, { method: 'POST', body: JSON.stringify(body) }),
    rubric: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/rubric`),
    answerKeyVersions: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/answer-key-versions`),
    createAnswerKey: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/answer-key-versions`, { method: 'POST', body: JSON.stringify(body) }),
    updateAnswerKey: (questionId, versionId, body) => request(`/questions/${encodeURIComponent(questionId)}/answer-key-versions/${encodeURIComponent(versionId)}`, { method: 'PUT', body: JSON.stringify(body) }),
    approveAnswerKey: (questionId, versionId) => request(`/questions/${encodeURIComponent(questionId)}/answer-key-versions/${encodeURIComponent(versionId)}/approve`, { method: 'POST', body: '{}' }),
    uploadAnswerKeyDocument: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/answer-key-documents`, { method: 'POST', body }),
    rubricVersions: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/rubric-versions`),
    createRubricVersion: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/rubric-versions`, { method: 'POST', body: JSON.stringify(body) }),
    suggestRubric: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/suggest-rubric-version`, { method: 'POST', body: JSON.stringify(body) }),
    updateRubric: (versionId, body) => request(`/rubric-versions/${encodeURIComponent(versionId)}`, { method: 'PUT', body: JSON.stringify(body) }),
    approveRubric: (versionId) => request(`/rubric-versions/${encodeURIComponent(versionId)}/approve`, { method: 'POST', body: '{}' }),
    assessmentGuide: (examId) => request(`/exams/${encodeURIComponent(examId)}/marking-guide`),
    approveAssessmentGuide: (examId, body) => request(`/exams/${encodeURIComponent(examId)}/marking-guide/approve`, { method: 'POST', body: JSON.stringify(body) }),
    gradingPolicy: (questionId) => request(`/questions/${encodeURIComponent(questionId)}/grading-policy`),
    updateGradingPolicy: (questionId, body) => request(`/questions/${encodeURIComponent(questionId)}/grading-policy`, { method: 'PUT', body: JSON.stringify(body) }),
    uploadExam: (formData) => request('/upload-exam', { method: 'POST', body: formData }),
    uploadBatch: (formData) => request('/upload-batch', { method: 'POST', body: formData }),
    batch: (batchId) => request(`/batches/${encodeURIComponent(batchId)}`),
    workspaceJobs: (limit = 8) => request(`/jobs?limit=${encodeURIComponent(limit)}`),
    job: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}`),
    retryJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST', body: '{}' }),
    retryBatch: (batchId) => request(`/batches/${encodeURIComponent(batchId)}/retry`, { method: 'POST', body: '{}' }),
    submissionJobs: (submissionId, jobType = '') => request(`/submissions/${encodeURIComponent(submissionId)}/jobs${jobType ? `?job_type=${encodeURIComponent(jobType)}` : ''}`),
    submissions: (examId) => request(`/submissions${examId ? `?exam_id=${encodeURIComponent(examId)}` : ''}`),
    deleteSubmission: (submissionId) => request(`/submissions/${encodeURIComponent(submissionId)}`, { method: 'DELETE' }),
    results: (submissionId) => request(`/results/${encodeURIComponent(submissionId)}`),
    gradingRuns: (answerId) => request(`/answers/${encodeURIComponent(answerId)}/grading-runs`),
    reviewHistory: (answerId) => request(`/answers/${encodeURIComponent(answerId)}/review-history`),
    extractionReview: (submissionId) => request(`/submissions/${encodeURIComponent(submissionId)}/extraction-review`),
    sourceLocations: (submissionId, pageIndex) => request(`/submissions/${encodeURIComponent(submissionId)}/source-locations${queryString({ page_index: pageIndex })}`),
    reprocessExtraction: (submissionId) => request(`/submissions/${encodeURIComponent(submissionId)}/reprocess-extraction`, { method: 'POST', body: '{}' }),
    updateSubmissionMetadata: (submissionId, body) => request(`/submissions/${encodeURIComponent(submissionId)}/metadata`, { method: 'PATCH', body: JSON.stringify(body) }),
    resolveIdentity: (submissionId, body) => request(`/submissions/${encodeURIComponent(submissionId)}/resolve-identity`,{method:'POST',body:JSON.stringify(body)}),
    resolveUnmatchedSegment: (submissionId, index, body) => request(`/submissions/${encodeURIComponent(submissionId)}/unmatched-segments/${index}`, { method: 'PUT', body: JSON.stringify(body) }),
    bulkResolveSegments: (submissionId, body) => request(`/submissions/${encodeURIComponent(submissionId)}/segments/bulk-resolve`, { method: 'PUT', body: JSON.stringify(body) }),
    submissionPageUrl: (submissionId, pageIndex) => `${API_BASE}/submissions/${encodeURIComponent(submissionId)}/pages/${pageIndex}`,
    moveAnswerSource: (sourceId, questionId) => request(`/answer-sources/${encodeURIComponent(sourceId)}/question`, { method: 'PUT', body: JSON.stringify({ question_id: questionId }) }),
    correctSourceText: (sourceId, body) => request(`/answer-sources/${encodeURIComponent(sourceId)}/text`, {method:'PATCH',body:JSON.stringify(body)}),
    removeAnswerSource: (sourceId) => request(`/answer-sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' }),
    sourceQuestionDrafts: (examId, body) => request(`/exams/${encodeURIComponent(examId)}/source-question-drafts`, { method: 'POST', body: JSON.stringify(body) }),
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
