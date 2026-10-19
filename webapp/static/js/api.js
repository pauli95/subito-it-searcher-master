// Client delle API: JSON in/out, errori con il messaggio del server.

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request(method, path, body, { raw = false, headers = {} } = {}) {
  const opts = { method, headers: { ...headers }, credentials: "same-origin" };
  if (body !== undefined) {
    if (raw) {
      opts.body = body;
      opts.headers["Content-Type"] = "application/octet-stream";
    } else {
      opts.body = JSON.stringify(body);
      opts.headers["Content-Type"] = "application/json";
    }
  }
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch {
    throw new ApiError("Server non raggiungibile: l'app è ancora in esecuzione?", 0);
  }
  if (resp.status === 401) {
    location.href = "/login";
    throw new ApiError("Accesso richiesto", 401);
  }
  const type = resp.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await resp.json().catch(() => null) : null;
  if (!resp.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map(d => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    throw new ApiError(msg || `Errore HTTP ${resp.status}`, resp.status, data);
  }
  return data ?? resp;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b),
  put: (p, b) => request("PUT", p, b),
  patch: (p, b) => request("PATCH", p, b),
  del: (p) => request("DELETE", p),
  upload: (p, blob) => request("POST", p, blob, { raw: true }),
  blob: async (p) => (await request("GET", p)).blob(),
};

export function qs(params) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "" && v !== false) sp.set(k, v);
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
