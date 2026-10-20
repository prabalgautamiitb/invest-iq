import { request, clearCsrf } from './client.js';

const rotate = async promise => {
  const result = await promise;
  clearCsrf();
  return result;
};

const id = value => encodeURIComponent(String(value));

export const authApi = {
  register: input => rotate(request('/auth/register', { method: 'POST', body: input })),
  login: input => rotate(request('/auth/login', { method: 'POST', body: input })),
  logout: () => rotate(request('/auth/logout', { method: 'POST' })),
  completePasswordReset: input => rotate(request('/auth/password-reset/complete', { method: 'POST', body: input })),
  requestVerification: email => request('/auth/verification/request', { method: 'POST', body: { email } }),
  completeVerification: token => request('/auth/verification/complete', { method: 'POST', body: { token } }),
  sessions: () => request('/me/sessions'),
  revokeSession: sessionId => request(`/me/sessions/${id(sessionId)}`, { method: 'DELETE' }),
  requestPasswordReset: email => request('/auth/password-reset/request', { method: 'POST', body: { email } }),
};

export const profileApi = {
  get: () => request('/me'),
  update: input => request('/me', { method: 'PATCH', body: input }),
  updatePreferences: input => request('/me/preferences', { method: 'PATCH', body: input }),
  updatePrivacy: input => request('/me/privacy', { method: 'PATCH', body: input }),
  onboardingQuestions: () => request('/onboarding/questions'),
  saveOnboarding: input => request('/me/onboarding', { method: 'PUT', body: input }),
  dashboard: () => request('/me/dashboard'),
};

export const portfolioApi = {
  instruments: (params = {}, signal) => request('/instruments?' + new URLSearchParams(params), { signal }),
  getDraft: contestId => request(`/contests/${id(contestId)}/portfolio/draft`),
  saveDraft: (contestId, input) => request(`/contests/${id(contestId)}/portfolio/draft`, { method: 'PUT', body: input }),
  preview: (contestId, revision) => request(`/contests/${id(contestId)}/portfolio/preview`, { method: 'POST', body: { draft_revision: revision } }),
  history: (contestId, params = {}) => request(`/contests/${id(contestId)}/submissions?` + new URLSearchParams(params)),
  submit: (contestId, input, key) => request(`/contests/${id(contestId)}/submissions`, { method: 'POST', body: input, headers: { 'Idempotency-Key': key } }),
};

export const contestApi = {
  list: (params = {}) => request('/contests?' + new URLSearchParams(params)),
  mine: (params = {}) => request('/me/contests?' + new URLSearchParams(params)),
  invitations: (params = {}) => request('/me/contest-invitations?' + new URLSearchParams(params)),
  template: () => request('/contest-template'),
  create: (input, key) => request('/contests', { method: 'POST', body: input, headers: { 'Idempotency-Key': key } }),
  revise: (contestId, input) => request(`/contests/${id(contestId)}`, { method: 'PUT', body: input }),
  transition: (contestId, action) => request(`/contests/${id(contestId)}/transitions`, { method: 'POST', body: { action } }),
  invite: (contestId, email) => request(`/contests/${id(contestId)}/invitations`, { method: 'POST', body: { email } }),
  hostedInvitations: (contestId, params = {}) => request(`/contests/${id(contestId)}/invitations?` + new URLSearchParams(params)),
  invitationAction: (invitationId, action) => request(`/contest-invitations/${id(invitationId)}/${id(action)}`, { method: 'POST' }),
  get: contestId => request(`/contests/${id(contestId)}`),
  join: contestId => request(`/contests/${id(contestId)}/entries`, { method: 'POST' }),
  leaderboard: contestId => request(`/contests/${id(contestId)}/leaderboard`),
};

export const academyApi = {
  courses: (params = {}) => request('/courses?' + new URLSearchParams(params)),
  enroll: courseId => request(`/courses/${id(courseId)}/enrollment`, { method: 'POST' }),
  progress: () => request('/me/learning'),
  attempts: (lessonId, params = {}) => request(`/lessons/${id(lessonId)}/attempts?` + new URLSearchParams(params)),
  lesson: lessonId => request(`/lessons/${id(lessonId)}`),
  submitAttempt: (lessonId, input, key) => request(`/lessons/${id(lessonId)}/attempts`, { method: 'POST', body: input, headers: { 'Idempotency-Key': key } }),
};

export const insightsApi = {
  createReview: input => request('/me/portfolio-reviews', { method: 'POST', body: input }),
  getReview: reviewId => request(`/me/portfolio-reviews/${id(reviewId)}`),
  saveReflection: input => request('/me/journal', { method: 'POST', body: input }),
};

export const performanceApi = {
  leaderboard: (contestId, params = {}) => request(`/contests/${id(contestId)}/leaderboard?` + new URLSearchParams(params)),
  performance: (contestId, params = {}) => request(`/contests/${id(contestId)}/performance?` + new URLSearchParams(params)),
  dashboard: () => request('/me/dashboard'),
  history: (params = {}) => request('/me/contest-history?' + new URLSearchParams(params)),
};
