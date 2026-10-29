export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, body, opts = {}) {
  const headers = { "X-Requested-With": "fetch", Accept: "application/json" };
  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload, credentials: "same-origin", cache: "no-store" });
  if (res.status === 204) return null;
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
  if (!res.ok) {
    if (res.status === 401 && !opts.silent401) {
      const here = location.pathname + location.search;
      if (!here.startsWith("/login") && !here.startsWith("/register")) {
        location.href = `/login?next=${encodeURIComponent(here)}`;
      }
    }
    throw new ApiError(res.status, data && data.detail !== undefined ? data.detail : data);
  }
  return data;
}

export const api = {
  get: (path, opts) => request("GET", path, undefined, opts),
  post: (path, body, opts) => request("POST", path, body, opts),
  patch: (path, body, opts) => request("PATCH", path, body, opts),
  put: (path, body, opts) => request("PUT", path, body, opts),
  del: (path, body, opts) => request("DELETE", path, body, opts),
  upload: (path, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("POST", path, fd);
  },
};

let _me;
export async function getMe() {
  if (_me !== undefined) return _me;
  try {
    _me = await api.get("/api/auth/me", { silent401: true });
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) _me = null;
    else throw err;
  }
  return _me;
}

let _config;
export async function getConfig() {
  if (!_config) _config = await api.get("/api/config");
  return _config;
}
