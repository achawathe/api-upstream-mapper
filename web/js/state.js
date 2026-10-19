import { api } from "./api.js";
import { toast } from "./dom.js";

export const store = {
  workspace: null,
  result: null,
  run: { id: null, events: [], done: false, error: null },
  mappings: { filters: { statuses: new Set(), endpoint: "", variant: "", text: "", requiredOnly: false }, selected: null },
  plan: { endpoint: null },
  validate: { form: null, result: null, options: null, busy: false },
};

let renderer = () => {};

export function setRenderer(render) {
  renderer = render;
}

export function changed() {
  renderer();
}

export function navigate(viewId) {
  location.hash = viewId;
}

export function canRun() {
  const files = store.workspace?.files ?? [];
  const running = store.run.starting || (store.run.id && !store.run.done);
  return files.some((f) => f.role === "upstream") && files.some((f) => f.role === "downstream") && !running;
}

export async function refreshWorkspace() {
  store.workspace = await api.state();
  if (!store.workspace.has_result) store.result = null;
  else if (!store.result) await refreshResult();
  changed();
}

export async function refreshResult() {
  try {
    store.result = await api.result();
  } catch {
    store.result = null;
  }
}

export async function startRun() {
  navigate("run");
  store.run = { id: null, events: [], done: false, error: null, starting: true };
  changed();
  let run_id;
  try {
    ({ run_id } = await api.startRun());
  } catch (error) {
    store.run = { ...store.run, starting: false, done: true, error: error.message };
    changed();
    return;
  }
  store.run.starting = false;
  store.run.id = run_id;
  const source = api.events(run_id);
  source.onmessage = (message) => {
    store.run.events.push(JSON.parse(message.data));
    changed();
  };
  source.addEventListener("done", async (message) => {
    source.close();
    store.run.done = true;
    store.run.error = JSON.parse(message.data).error;
    if (!store.run.error) {
      await refreshResult();
      store.validate = { form: null, result: null, options: null, busy: false };
      store.mappings.selected = null;
      toast("Mapping finished");
    }
    changed();
  });
  source.onerror = () => {
    if (store.run.done) return;
    source.close();
    store.run.done = true;
    store.run.error = "lost connection to the server";
    changed();
  };
}

export function applyOverrideResponse(response) {
  const index = store.result.mappings.findIndex((m) => m.target.key === response.mapping.target.key);
  store.result.mappings[index] = response.mapping;
  store.result.summary = response.summary;
  store.result.call_plans = response.call_plans;
  store.result.overrides = response.overrides;
  response.warnings.forEach((warning) => toast(warning));
  changed();
}
