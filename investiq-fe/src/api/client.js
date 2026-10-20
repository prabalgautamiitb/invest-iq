// Connected identity, market, contest and portfolio flows share cookie/CSRF handling.
const API_BASE = (import.meta.env?.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message, status, details) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

let csrfToken = null;
let csrfBootstrap = null;
export function clearCsrf() { csrfToken = null; csrfBootstrap = null; }

async function csrf() {
  if (csrfToken) return csrfToken;
  if (!csrfBootstrap) {
    csrfBootstrap = request('/auth/csrf').then(result => {
      csrfToken = result.csrf_token;
      return csrfToken;
    }).finally(() => { csrfBootstrap = null; });
  }
  return csrfBootstrap;
}

export async function request(path, { method = 'GET', body, headers = {}, signal } = {}) {
  if (!path.startsWith('/')) throw new Error('API paths must start with /');
  const mutation = !['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase());
  const securityHeaders = mutation ? { 'X-CSRF-Token': await csrf() } : {};
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const response = await fetch(API_BASE + path, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : {}),
      ...securityHeaders,
      ...headers,
    },
    ...(body !== undefined ? { body: isForm ? body : JSON.stringify(body) } : {}),
    signal,
  });
  if (response.status === 204) return null;
  const text = await response.text();
  let data;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!response.ok) {
    const message = typeof data === 'object' && data !== null
      ? data.message || data.error?.message || `Request failed (${response.status})`
      : `Request failed (${response.status})`;
    if (data?.error?.code === 'csrf_failed' || response.status === 401) {
      clearCsrf();
      if (typeof window !== 'undefined') window.dispatchEvent(new Event(response.status === 401 ? 'investiq:session-expired' : 'investiq:csrf-changed'));
    }
    throw new ApiError(message, response.status, data);
  }
  return data ?? null;
}
