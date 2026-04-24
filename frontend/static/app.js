function appState() {
  return {
    async init() {
    },
    async logout() {
      await fetch('/auth/logout', {method: 'POST'});
      window.location.href = '/login';
    },
    async api(method, path, body) {
      const opts = {method, headers: {'Content-Type': 'application/json'}};
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch(path, opts);
      if (r.status === 401) { window.location.href = '/login'; return null; }
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Request failed'); }
      return r.json();
    }
  }
}
