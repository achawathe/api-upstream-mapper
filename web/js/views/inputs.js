import { responseSamplesCard } from "./response-samples.js";
import { api } from "../api.js";
import { dropzone, h, mount, toast } from "../dom.js";
import { canRun, refreshWorkspace, startRun, store } from "../state.js";
import { jsonResponseInput } from "./json-response-input.js";
import { upstreamModels } from "./upstream-models.js";
import { documentationCard } from "./documentation.js";

const ROLES = [
  { role: "upstream", title: "Upstream spec", hint: "Upload the upstream spec together with its referenced model YAML/JSON files. Use Choose folder for nested references.", multiple: true },
  { role: "downstream", title: "Downstream APIs", hint: "Upload downstream specs with their referenced model files. Use Choose folder to preserve nested paths.", multiple: true },
  { role: "catalog", title: "Upstream error catalog", hint: "Optional. Upstream error codes with HTTP status and keywords.", multiple: false },
  { role: "lexicon", title: "Extra lexicon", hint: "Optional. Your own abbreviations and synonyms, merged over the selected vocabulary.", multiple: true },
  { role: "answer_key", title: "Answer key", hint: "Optional. Expected mappings; enables the accuracy report.", multiple: false },
];

export function renderInputs(container) {
  const files = store.workspace?.files ?? [];
  mount(
    container,
    h(
      "div",
      { class: "card row" },
      h("div", {}, h("strong", {}, "Try it with the bundled example"), h("p", { class: "muted" }, "FDX 6.4 (Plaid Core Exchange) as the upstream, eight Northwind Bank downstream APIs, including a decoy.")),
      h("span", { class: "spacer" }),
      h("button", { class: "btn", onclick: () => act(api.demo(), "Example loaded") }, "Load example"),
      h("button", { class: "btn danger", onclick: () => act(api.reset(), "Workspace cleared") }, "Clear workspace"),
    ),
    h("div", { class: "grid grid-2", style: { marginTop: "16px" } }, ROLES.map((role) => roleCard(role, files))),
    h("div", { class: "grid grid-2", style: { marginTop: "16px" } }, documentationCard(), responseSamplesCard(), settingsCard(), sampleCard()),
    h(
      "div",
      { class: "row", style: { marginTop: "18px" } },
      h("span", { class: "spacer" }),
      !canRun() && h("span", { class: "muted" }, "Add an upstream spec and at least one downstream API to run."),
      h("button", { class: "btn primary", onclick: startRun, disabled: !canRun() }, "Run mapping →"),
    ),
  );
}

function roleCard({ role, title, hint, multiple }, files) {
  const mine = files.filter((f) => f.role === role);
  return h(
    "div",
    { class: "card" },
    h("h2", {}, title, mine.length > 1 ? ` (${mine.length})` : ""),
    h("p", { class: "muted small" }, hint),
    dropzone(multiple ? "Drop files here or click to choose" : "Drop a file here or click to choose", (chosen) => act(api.upload(role, chosen), `${chosen.length} file(s) added`), {
      multiple,
    }),
    ["upstream", "downstream"].includes(role) && folderPicker(role),
    mine.map(fileRow),
    role === "upstream" && mine.length === 1 && upstreamModels(mine[0]),
  );
}

function folderPicker(role) {
  const input = h("input", { type: "file", webkitdirectory: true, multiple: true, hidden: true, onchange: () => {
    const files = [...input.files].filter((file) => /\.(json|ya?ml)$/i.test(file.name));
    if (files.length) act(api.upload(role, files), "Spec folder added");
    else toast("The folder contains no YAML or JSON files");
  } });
  return h("div", {}, input, h("button", { class: "btn small", style: { marginTop: "8px" }, onclick: () => input.click() }, "Choose folder"));
}

function fileRow(file) {
  const s = file.summary ?? {};
  const details = s.ok === false
    ? h("span", { class: "small", style: { color: "var(--unmapped)" } }, s.error)
    : h(
        "span",
        { class: "small muted" },
        [s.title && `${s.title} ${s.version ?? ""}`.trim(), s.kind, s.endpoints != null && plural(s.endpoints, "endpoint"), s.errors != null && plural(s.errors, "code"),
          s.expectations != null && plural(s.expectations, "expectation")].filter(Boolean).join(" · "),
      );
  return h(
    "div",
    { class: `file-row ${s.ok === false ? "bad" : ""}` },
    h("div", {}, h("div", { class: "name" }, file.name), details, fileWarnings(s.warnings ?? [])),
    h("span", { class: "spacer" }),
    h("button", { class: "btn small", "aria-label": `Remove ${file.name}`, onclick: () => act(api.removeFile(file.id), "Removed") }, "Remove"),
  );
}

function fileWarnings(warnings) {
  const unique = [...new Set(warnings)];
  if (!unique.length) return null;
  return h("details", { class: "small warn" }, h("summary", {}, plural(unique.length, "warning")),
    unique.map((warning) => h("div", {}, warning)));
}

function sampleCard() {
  const name = h("input", { type: "text", placeholder: "routing-service", "aria-label": "API name" });
  const method = h("select", { "aria-label": "HTTP method" }, ["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => h("option", {}, m)));
  const path = h("input", { type: "text", placeholder: "/payments/routing/{acctNum}", "aria-label": "Endpoint path" });
  const responses = jsonResponseInput({ fileLabel: "Sample payloads",
    pasteLabel: "JSON response for API without a spec", filename: "pasted-sample.json" });
  const add = () => {
    if (!name.value.trim() || !path.value.trim()) return toast("API name and endpoint path are needed");
    try {
      act(api.addSampleEndpoint(name.value.trim(), method.value, path.value.trim(), responses.readFiles()), "Sample endpoint added");
    } catch (error) { toast(error.message); }
  };
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "API without a spec"),
    h("p", { class: "muted small" }, "Upload or paste JSON examples for an API that has no schema. To supplement an existing spec, use Documentation response examples above. The schema is inferred: a key is required only if every sample has it, and distinct values are used like an enum."),
    h(
      "div",
      { class: "grid", style: { gridTemplateColumns: "1fr 90px 1.4fr" } },
      h("label", { class: "field" }, "API name", name),
      h("label", { class: "field" }, "Method", method),
      h("label", { class: "field" }, "Path", path),
    ),
    h("div", { style: { marginTop: "10px" } }, responses.element),
    h("div", { class: "row", style: { marginTop: "10px" } }, h("button", { class: "btn", onclick: add }, "Add endpoint")),
  );
}

function settingsCard() {
  const settings = store.workspace?.settings ?? { auto: 0.72, review: 0.5 };
  const auto = h("input", { type: "number", min: 0, max: 1, step: 0.01, value: settings.auto, "aria-label": "Automatic threshold" });
  const review = h("input", { type: "number", min: 0, max: 1, step: 0.01, value: settings.review, "aria-label": "Review threshold" });
  const model = h("input", { type: "text", value: settings.nlp?.model_path ?? "", placeholder: "/path/to/local/model", "aria-label": "Local NLP model folder" });
  const domain = h("select", { "aria-label": "Mapping vocabulary" }, ["general", "finance"].map((value) => h("option", { value, selected: value === (settings.domain ?? "finance") }, value === "general" ? "General applications" : "Finance")));
  const save = () => act(api.saveSettings({ auto: Number(auto.value), review: Number(review.value), domain: domain.value, nlp: { ...settings.nlp, model_path: model.value.trim() } }), "Settings saved; run again to apply");
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "Decision thresholds"),
    h("label", { class: "field" }, "Mapping vocabulary", domain),
    h("p", { class: "muted small" }, "At or above the automatic threshold a mapping is accepted without review, unless a close alternative exists. Between the two it needs review. Below review it stays unmapped."),
    h("div", { class: "row" }, h("label", { class: "field" }, "Automatic", auto), h("label", { class: "field" }, "Review", review), h("span", { class: "spacer" }), h("button", { class: "btn", onclick: save }, "Save")),
    h("label", { class: "field" }, "Local NLP model folder (optional)", model),
    h("p", { class: "muted small" }, "Leave blank for rules only. A local Sentence Transformers model adds meaning-based suggestions without downloading models or sending API content to a service. NLP-only matches require review; existing compatibility checks still apply."),
  );
}

async function act(promise, message) {
  try {
    await promise;
    toast(message);
    await refreshWorkspace();
  } catch (error) {
    toast(error.message);
  }
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}
