/* MISRA EDU API client. No fake data and no stored auth tokens. */
(function () {
  'use strict';

  const sameOriginApi = window.location.pathname.startsWith('/app/') ? `${window.location.origin}/api` : 'http://127.0.0.1:8000/api';
  const API_BASE = (window.MISRA_API_BASE || sameOriginApi).replace(/\/$/, '');

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      cache: 'no-store',
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(options.headers || {}),
      },
    });

    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json')
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const detail = payload && typeof payload === 'object' ? payload.detail : payload;
      const message = typeof detail === 'string'
        ? detail
        : detail?.message || `Request failed (${response.status})`;
      const error = new Error(message);
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    return payload;
  }

  window.MisraAPI = {
    baseUrl: API_BASE,
    health: () => request('/health'),
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
    submissions: (examId) => request(`/submissions${examId ? `?exam_id=${encodeURIComponent(examId)}` : ''}`),
    results: (submissionId) => request(`/results/${encodeURIComponent(submissionId)}`),
    extractionReview: (submissionId) => request(`/submissions/${encodeURIComponent(submissionId)}/extraction-review`),
    updateSubmissionMetadata: (submissionId, body) => request(`/submissions/${encodeURIComponent(submissionId)}/metadata`, { method: 'PATCH', body: JSON.stringify(body) }),
    resolveUnmatchedSegment: (submissionId, index, body) => request(`/submissions/${encodeURIComponent(submissionId)}/unmatched-segments/${index}`, { method: 'PUT', body: JSON.stringify(body) }),
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
  };
})();
