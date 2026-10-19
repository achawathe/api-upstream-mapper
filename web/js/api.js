async function request(method, url, body) {
  const options = { method, headers: {} };
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const payload = response.headers.get("content-type")?.includes("json") ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.detail ?? `${method} ${url} failed (${response.status})`);
  return payload;
}

export const api = {
  state: () => request("GET", "/api/state"),
  upload: (role, files) => {
    const form = new FormData();
    form.append("role", role);
    files.forEach((file) => form.append("files", file));
    return request("POST", "/api/files", form);
  },
  addSampleEndpoint: (apiName, method, path, files) => {
    const form = new FormData();
    form.append("api_name", apiName);
    form.append("method", method);
    form.append("path", path);
    files.forEach((file) => form.append("files", file));
    return request("POST", "/api/sample-endpoints", form);
  },
  removeFile: (id) => request("DELETE", `/api/files/${id}`),
  demo: () => request("POST", "/api/demo"),
  reset: () => request("POST", "/api/reset"),
  saveSettings: (settings) => request("PUT", "/api/settings", settings),
  startRun: () => request("POST", "/api/runs"),
  result: () => request("GET", "/api/result"),
  candidates: (targetKey, query) => request("GET", `/api/candidates?target_key=${encodeURIComponent(targetKey)}&q=${encodeURIComponent(query)}`),
  setOverride: (override) => request("POST", "/api/overrides", override),
  clearOverride: (targetKey) => request("DELETE", `/api/overrides?target_key=${encodeURIComponent(targetKey)}`),
  validateOptions: () => request("GET", "/api/validate/options"),
  validate: (body) => request("POST", "/api/validate", body),
  events: (runId) => new EventSource(`/api/runs/${runId}/events`),
};
