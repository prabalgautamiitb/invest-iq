import { request, clearCsrf, apiUrl } from './client.js';

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
  startSubscription: plan => request('/me/subscription', { method: 'POST', body: { plan } }),
  photoUrl: version => apiUrl('/me/photo?v=' + encodeURIComponent(version)),
  photo: () => request('/me/photo', { responseType: 'blob' }),
  savePhoto: blob => request('/me/photo', { method: 'PUT', body: blob }),
  removePhoto: () => request('/me/photo', { method: 'DELETE' }),
  get: () => request('/me'),
  update: input => request('/me', { method: 'PATCH', body: input }),
  updatePreferences: input => request('/me/preferences', { method: 'PATCH', body: input }),
  updatePrivacy: input => request('/me/privacy', { method: 'PATCH', body: input }),
  onboardingQuestions: () => request('/onboarding/questions'),
  saveOnboarding: input => request('/me/onboarding', { method: 'PUT', body: input }),
  dashboard: () => request('/me/dashboard'),
};

export const walletApi = { get: () => request('/me/wallet') };

export const portfolioApi = {
  instruments: (params = {}, signal) => request('/instruments?' + new URLSearchParams(params), { signal }),
  getDraft: contestId => request(`/contests/${id(contestId)}/portfolio/draft`),
  saveDraft: (contestId, input) => request(`/contests/${id(contestId)}/portfolio/draft`, { method: 'PUT', body: input }),
  preview: (contestId, revision) => request(`/contests/${id(contestId)}/portfolio/preview`, { method: 'POST', body: { draft_revision: revision } }),
  history: (contestId, params = {}) => request(`/contests/${id(contestId)}/submissions?` + new URLSearchParams(params)),
  submit: (contestId, input, key) => request(`/contests/${id(contestId)}/submissions`, { method: 'POST', body: input, headers: { 'Idempotency-Key': key } }),
};

export const contestApi = {
  createPlatform: (input, key) => request('/admin/contests', { method: 'POST', body: input, headers: { 'Idempotency-Key': key } }),
  list: (params = {}) => request('/contests?' + new URLSearchParams(params)),
  mine: (params = {}) => request('/me/contests?' + new URLSearchParams(params)),
  invitations: (params = {}) => request('/me/contest-invitations?' + new URLSearchParams(params)),
  template: () => request('/contest-template'),
  simulationSessions: () => request('/contest-simulation-sessions'),
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
  adminCourses: (params = {}) => request('/admin/courses?' + new URLSearchParams(params)),
  publishCourse: input => request('/admin/courses', { method:'POST', body:input }),
  publishLesson: (courseId,input) => request(`/admin/courses/${id(courseId)}/lessons`, { method:'POST', body:input }),
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
  portfolio: () => request('/me/portfolio'),
  leaderboard: (contestId, params = {}) => request(`/contests/${id(contestId)}/leaderboard?` + new URLSearchParams(params)),
  performance: (contestId, params = {}) => request(`/contests/${id(contestId)}/performance?` + new URLSearchParams(params)),
  dashboard: () => request('/me/dashboard'),
  history: (params = {}) => request('/me/contest-history?' + new URLSearchParams(params)),
};


export const rewardsApi = {
  catalogue: (params = {}) => request('/rewards?' + new URLSearchParams(params)),
  get: itemId => request(`/rewards/${id(itemId)}`),
  wallet: () => request('/me/coins'),
  ledger: (params = {}) => request('/me/coins/ledger?' + new URLSearchParams(params)),
  history: (params = {}) => request('/me/redemptions?' + new URLSearchParams(params)),
  redeem: (input, key) => request('/me/redemptions', { method: 'POST', body: input, headers: { 'Idempotency-Key': key } }),
};

export const communityApi = {
  feed: (params={}) => request('/community/posts?'+new URLSearchParams(params)),
  get: postId => request(`/community/posts/${id(postId)}`),
  comments: (postId,params={}) => request(`/community/posts/${id(postId)}/comments?`+new URLSearchParams(params)),
  create: (input,key) => request('/community/posts',{method:'POST',body:input,headers:{'Idempotency-Key':key}}),
  comment: (postId,input,key) => request(`/community/posts/${id(postId)}/comments`,{method:'POST',body:input,headers:{'Idempotency-Key':key}}),
  flag: (postId,action,enabled) => request(`/community/posts/${id(postId)}/${id(action)}`,{method:'PUT',body:{enabled}}),
  vote: (postId,option) => request(`/community/posts/${id(postId)}/vote`,{method:'PUT',body:{option}}),
  remove: postId => request(`/community/posts/${id(postId)}`,{method:'DELETE'}),
  report: (postId,reason) => request(`/community/posts/${id(postId)}/reports`,{method:'POST',body:{reason}}),
  groups: (params={}) => request('/community/groups?'+new URLSearchParams(params)),
  group: groupId => request(`/community/groups/${id(groupId)}`),
  createGroup: input => request('/community/groups',{method:'POST',body:input}),
  membership: (groupId,enabled) => request(`/community/groups/${id(groupId)}/membership`,{method:'PUT',body:{enabled}}),
  reports: (params={}) => request('/community/reports?'+new URLSearchParams(params)),
  moderate: (postId,input) => request(`/community/posts/${id(postId)}/moderation`,{method:'POST',body:input}),
};

export const coachApi = {
  overview: () => request('/me/coach/overview'),
  settings: () => request('/me/coach/settings'),
  evidence: contestId => request('/me/coach/evidence?'+new URLSearchParams({contest_id:contestId})),
  jobs: (params={}) => request('/me/coach/jobs?'+new URLSearchParams(params)),
  job: jobId => request(`/me/coach/jobs/${id(jobId)}`),
  create: (contestId,key) => request('/me/coach/jobs',{method:'POST',body:{contest_id:contestId},headers:{'Idempotency-Key':key}}),
  reflections: (contestId,params={}) => request('/me/coach/reflections?'+new URLSearchParams({contest_id:contestId,...params})),
  reflect: (input,key) => request('/me/coach/reflections',{method:'POST',body:input,headers:{'Idempotency-Key':key}}),
};

export const martinApi = {
  settings: () => request('/me/martin/settings'),
  conversations: (params={}) => request('/me/martin/conversations?'+new URLSearchParams(params)),
  turns: (conversationId,params={}) => request(`/me/martin/conversations/${id(conversationId)}?`+new URLSearchParams(params)),
  ask: (input,key) => request('/me/martin/turns',{method:'POST',body:input,headers:{'Idempotency-Key':key}}),
  control: (turnId,action) => request(`/me/martin/turns/${id(turnId)}/${id(action)}`,{method:'POST'}),
  remove: conversationId => request(`/me/martin/conversations/${id(conversationId)}`,{method:'DELETE'}),
};
