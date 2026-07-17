// Thin API client. All application state lives server-side (Postgres / the
// agent graph's checkpointer / the audit log). This module holds NO state and
// deliberately uses NO localStorage / sessionStorage.

const BASE = import.meta.env.VITE_API_BASE || "";

async function req(path, options) {
  const res = await fetch(`${BASE}/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  status: () => req("/status"),
  health: () => req("/health"),
  listInvestigations: () => req("/investigations"),
  getInvestigation: (id) => req(`/investigations/${id}`),
  trigger: (body = {}) =>
    req("/investigations", { method: "POST", body: JSON.stringify(body) }),
  approve: (id, reviewer, note) =>
    req(`/investigations/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ reviewer, note }),
    }),
  reject: (id, reviewer, note) =>
    req(`/investigations/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reviewer, note }),
    }),
  audit: (limit = 50) => req(`/audit?limit=${limit}`),
};
