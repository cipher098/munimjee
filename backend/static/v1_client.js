/* Shared native session and CSRF transport for V1 operating pages. */
window.V1 = (() => {
  let csrf = null;
  function clearPrivateDrafts() {
    // Public customer checkout recovery has its own lifecycle. Clear only the
    // native seller's private draft commands when that identity ends/changes.
    try {
      const storage = window.sessionStorage;
      for (let index = storage.length - 1; index >= 0; index--) {
        const key = storage.key(index);
        if (['munimjee.v1.catalogue-draft:', 'munimjee.v1.parcel-link:', 'munimjee.v1.gateway-intent:', 'munimjee.v1.assistance-command:', 'munimjee.v1.import-command:'].some(prefix => key?.startsWith(prefix))) storage.removeItem(key);
      }
    } catch (_) { /* Restricted browser storage must never prevent logout. */ }
  }
  async function api(path, options = {}) {
    const method = options.method || 'GET';
    const headers = {...options.headers};
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (!['GET', 'HEAD'].includes(method) && csrf) headers['X-CSRF-Token'] = csrf;
    const response = await fetch(path, {...options, headers, credentials: 'same-origin', cache: 'no-store',
      body: options.body === undefined ? undefined : JSON.stringify(options.body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) { csrf = null; clearPrivateDrafts(); }
      const message = typeof data?.detail === 'string' ? data.detail
        : typeof data?.detail?.message === 'string' ? data.detail.message : 'Check the entered details and try again.';
      const error = new Error(message);
      error.status = response.status;
      error.code = typeof data?.detail?.code === 'string' ? data.detail.code : null;
      throw error;
    }
    if (method === 'POST' && ['/api/v1/auth/login', '/api/v1/auth/signup',
        '/api/v1/auth/invitations/accept', '/api/v1/auth/logout', '/api/v1/auth/logout-all'].includes(path)) {
      csrf = null;
      clearPrivateDrafts();
    }
    if (data && Object.hasOwn(data, 'csrf_token')) csrf = data.csrf_token;
    return data;
  }
  return {api, session: () => api('/api/v1/auth/session'), get csrf() { return csrf; }};
})();
