/* Shared native session and CSRF transport for V1 operating pages. */
window.V1 = (() => {
  let csrf = null;
  async function api(path, options = {}) {
    const method = options.method || 'GET';
    const headers = {...options.headers};
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (!['GET', 'HEAD'].includes(method) && csrf) headers['X-CSRF-Token'] = csrf;
    const response = await fetch(path, {...options, headers, credentials: 'same-origin', cache: 'no-store',
      body: options.body === undefined ? undefined : JSON.stringify(options.body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = typeof data.detail === 'string' ? data.detail : 'Check the entered details and try again.';
      const error = new Error(message); error.status = response.status; throw error;
    }
    if (Object.hasOwn(data, 'csrf_token')) csrf = data.csrf_token;
    return data;
  }
  return {api, session: () => api('/api/v1/auth/session'), get csrf() { return csrf; }};
})();
