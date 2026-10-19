import { api } from "../api.js";
import { h, mount, toast } from "../dom.js";
import { changed, store } from "../state.js";

const FAULT_CHOICES = ["", "400", "403", "404", "409", "429", "500", "502", "503"];

export function renderValidate(container) {
  const state = store.validate;
  if (!state.options) {
    mount(container, h("p", { class: "muted" }, "Loading…"));
    api.validateOptions().then((options) => {
      state.options = options;
      state.form ??= defaultForm(options);
      changed();
    }).catch((e) => toast(e.message));
    return;
  }
  mount(container, h("div", { class: "grid", style: { gridTemplateColumns: "minmax(320px, 380px) 1fr" } }, formCard(state), resultView(state.result)));
}

function defaultForm(options) {
  const endpoint = options.endpoints.find((e) => e.steps > 0) ?? options.endpoints[0];
  return { endpoint: endpoint.endpoint, params: { accountId: "ACC-1", partyId: "PTY-1" }, variant_hint: "", include_review: true, latency_ms: 40, faults: {} };
}

function formCard(state) {
  const form = state.form;
  const option = state.options.endpoints.find((e) => e.endpoint === form.endpoint);
  const paramNames = [...option.path_params, ...option.context_params, ...option.query_params.filter((q) => /start|end/i.test(q))];
  const set = (key, value) => {
    form[key] = value;
    changed();
  };
  const execute = async () => {
    state.busy = true;
    changed();
    try {
      const params = Object.fromEntries(paramNames.map((name) => [name, form.params[name] ?? ""]).filter(([, v]) => v));
      const faults = Object.fromEntries(Object.entries(form.faults).filter(([, v]) => v).map(([k, v]) => [k, Number(v)]));
      state.result = await api.validate({ ...form, params, faults, variant_hint: form.variant_hint || null });
    } catch (error) {
      toast(error.message);
    } finally {
      state.busy = false;
      changed();
    }
  };

  return h(
    "div",
    { class: "card stack" },
    h("h2", {}, "Request"),
    h(
      "label",
      { class: "field" },
      "Upstream endpoint",
      h("select", { onchange: (e) => set("endpoint", e.target.value) }, state.options.endpoints.map((e) => h("option", { value: e.endpoint, selected: e.endpoint === form.endpoint }, `${e.endpoint}${e.steps ? "" : " (no calls)"}`))),
    ),
    paramNames.map((name) =>
      h("label", { class: "field" }, option.context_params.includes(name) ? `${name} (caller context)` : name,
        h("input", { type: "text", value: form.params[name] ?? "", oninput: (e) => (form.params[name] = e.target.value) })),
    ),
    option.variants.length > 0 &&
      h("label", { class: "field" }, "Variant", h("select", { onchange: (e) => set("variant_hint", e.target.value) },
        h("option", { value: "" }, "decide from the data"),
        option.variants.map((v) => h("option", { value: v.name, selected: v.name === form.variant_hint }, `${v.name}${v.value ? ` (${v.value})` : ""}`)))),
    h("label", { class: "row small" }, h("input", { type: "checkbox", checked: form.include_review, onchange: (e) => (form.include_review = e.target.checked) }), "use mappings still awaiting review"),
    h("label", { class: "field" }, `Latency per downstream call: ${form.latency_ms} ms`,
      h("input", { type: "range", min: 0, max: 300, step: 10, value: form.latency_ms, oninput: (e) => (form.latency_ms = Number(e.target.value)), onchange: () => changed() })),
    h("h3", {}, "Inject downstream failures"),
    h("div", { class: "grid", style: { gridTemplateColumns: "1fr 90px" } }, state.options.apis.map((a) => [
      h("span", { class: "small" }, a.name, a.statuses.length > 0 && h("span", { class: "muted" }, ` (declares ${a.statuses.join(", ")})`)),
      h("select", { "aria-label": `Failure for ${a.name}`, onchange: (e) => (form.faults[a.name] = e.target.value) }, FAULT_CHOICES.map((c) => h("option", { value: c, selected: String(form.faults[a.name] ?? "") === c }, c || "ok"))),
    ])),
    h("button", { class: "btn primary", onclick: execute, disabled: state.busy }, state.busy ? "Running…" : "Execute against mocks"),
  );
}

function resultView(result) {
  if (!result) {
    return h("div", { class: "card empty" }, h("p", {}, "Mock downstreams are built from each spec's own examples, or synthesised from its schema."), h("p", { class: "small" }, "Executing shows every call, what ran in parallel, the assembled upstream response, and anything in it that breaks the upstream schema."));
  }
  const ok = result.status < 400;
  return h(
    "div",
    { class: "stack" },
    h(
      "div",
      { class: "kpis" },
      kpi(result.status, "upstream status", ok ? "var(--auto)" : "var(--unmapped)"),
      kpi(`${result.elapsed_ms} ms`, "wall time"),
      kpi(`${result.sequential_ms} ms`, "if calls ran one by one"),
      kpi(result.calls.length, "downstream calls"),
      kpi(result.issues.length, "schema issues", result.issues.length ? "var(--review)" : "var(--auto)"),
    ),
    result.variants.length > 0 && h("div", { class: "card small" }, "Variant chosen: ", [...new Set(result.variants)].map((v) => h("span", { class: "chip" }, v)), result.variants.length > 1 && h("span", { class: "muted" }, " (per item)")),
    timeline(result),
    result.skipped_steps.length > 0 && h("div", { class: "card small" }, h("strong", {}, "Not called: "), result.skipped_steps.join("; "), h("div", { class: "muted" }, "Either the data showed the record is another variant, or nothing this call supplies is in use.")),
    (result.warnings.length > 0 || result.unreviewed_fields > 0) &&
      h("div", { class: "warn" }, result.unreviewed_fields > 0 && h("div", {}, `${result.unreviewed_fields} field(s) came from mappings still awaiting review.`), result.warnings.map((w) => h("div", {}, w))),
    result.issues.length > 0 && h("div", { class: "card" }, h("h2", {}, "Schema issues"), h("ul", { class: "small" }, result.issues.map((i) => h("li", {}, h("span", { class: "mono" }, i.path || "—"), " ", i.message)))),
    h("div", { class: "card" }, h("h2", {}, ok ? "Assembled upstream response" : "Upstream error response"), h("pre", { class: "json" }, JSON.stringify(result.body, null, 2))),
  );
}

function timeline(result) {
  if (!result.calls.length) return null;
  const end = Math.max(...result.calls.map((c) => c.started_ms + c.duration_ms), 1);
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "Calls over time"),
    h(
      "div",
      { class: "timeline", role: "img", "aria-label": "Timeline of downstream calls" },
      [...result.calls].sort((a, b) => a.started_ms - b.started_ms).map((call) =>
        h(
          "div",
          { class: "timeline-row" },
          h("span", { class: "mono", title: call.url }, `${call.step}. ${call.api}${call.item != null ? ` #${call.item + 1}` : ""}`),
          h("div", { class: "timeline-track" }, h("span", { class: `timeline-bar ${call.status >= 400 ? "failed" : ""}`, style: { left: `${(call.started_ms / end) * 100}%`, width: `${Math.max((call.duration_ms / end) * 100, 0.8)}%` } })),
          h("span", { class: "mono small" }, `${call.status} · ${call.duration_ms}ms`),
        ),
      ),
    ),
  );
}

function kpi(value, label, color) {
  return h("div", { class: "kpi" }, h("div", { class: "value", style: color ? { color } : null }, value), h("div", { class: "label" }, label));
}
