import { api } from "../api.js";
import { h, mount, scoreBar, statusPill, STATUS_LABELS, toast } from "../dom.js";
import { applyOverrideResponse, changed, store } from "../state.js";
import { comparisonView } from "./candidate-comparison.js";
import { mappingBlocks } from "./mapping-blocks.js";

const MAX_ROWS = 600;

export function renderMappings(container) {
  const { mappings, summary } = store.result;
  const filters = store.mappings.filters;
  const tableRegion = h("div");
  const endpoints = [...new Set(mappings.map((m) => m.target.endpoint))];
  const variants = [...new Set(mappings.filter((m) => !filters.endpoint || m.target.endpoint === filters.endpoint).map((m) => m.target.variant).filter(Boolean))];

  const refreshTable = () => mount(tableRegion, store.mappings.mode === "blocks" ? mappingBlocks(filtered(mappings, filters)) : table(filtered(mappings, filters)));
  const search = h("input", {
    type: "search",
    placeholder: "Search field, source, note…",
    value: filters.text,
    "aria-label": "Search mappings",
    oninput: () => {
      filters.text = search.value;
      refreshTable();
    },
  });

  const statusChips = Object.entries(summary).filter(([, count]) => count).map(([status, count]) =>
    h("button", {
      class: `filter-chip ${filters.statuses.has(status) ? "on" : ""}`,
      "aria-pressed": filters.statuses.has(status),
      onclick: () => {
        filters.statuses.has(status) ? filters.statuses.delete(status) : filters.statuses.add(status);
        changed();
      },
    }, `${STATUS_LABELS[status]} · ${count}`),
  );

  const toolbar = h(
    "div",
    { class: "toolbar" },
    ["blocks", "table"].map((mode) => h("button", { class: `btn small ${store.mappings.mode === mode ? "primary" : ""}`, "aria-pressed": String(store.mappings.mode === mode), onclick: () => { store.mappings.mode = mode; changed(); } }, mode === "blocks" ? "Blocks" : "Table")),
    statusChips,
    h("span", { class: "spacer" }),
    search,
    select("Endpoint", endpoints, filters.endpoint, (value) => {
      filters.endpoint = value;
      filters.variant = "";
      changed();
    }),
    variants.length > 0 && select("Variant", variants, filters.variant, (value) => {
      filters.variant = value;
      changed();
    }),
    select("Category", [...new Set(mappings.map((m) => m.category).filter(Boolean))], filters.category, (value) => { filters.category = value; changed(); }),
    h("label", { class: "row small" }, h("input", { type: "checkbox", checked: filters.requiredOnly, onchange: (e) => { filters.requiredOnly = e.target.checked; changed(); } }), "required only"),
  );

  const selected = mappings.find((m) => m.target.key === store.mappings.selected);
  refreshTable();
  mount(
    container,
    toolbar,
    store.mappings.mode === "blocks" ? tableRegion : h("div", { class: `workbench ${selected ? "" : "closed"}` }, tableRegion, selected && h("div", { class: "card detail" }, detail(selected))),
  );
}

function filtered(mappings, filters) {
  const words = filters.text.toLowerCase().split(/\s+/).filter(Boolean);
  return mappings.filter((m) => {
    if (filters.statuses.size && !filters.statuses.has(m.status)) return false;
    if (filters.endpoint && m.target.endpoint !== filters.endpoint) return false;
    if (filters.variant && m.target.variant !== filters.variant) return false;
    if (filters.category && m.category !== filters.category) return false;
    if (filters.requiredOnly && !m.target.required) return false;
    if (!words.length) return true;
    const haystack = [m.target.key, m.chosen?.source.key ?? "", m.category, ...m.notes].join(" ").toLowerCase();
    return words.every((w) => haystack.includes(w));
  });
}

function table(rows) {
  if (!rows.length) return h("div", { class: "empty card" }, "No fields match these filters.");
  const shown = rows.slice(0, MAX_ROWS);
  return h(
    "div",
    {},
    h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        {},
        h("thead", {}, h("tr", {}, h("th", {}, "Upstream field"), h("th", {}, "Status"), h("th", {}, "Confidence"), h("th", {}, "Downstream source"), h("th", {}, "Transform"))),
        h("tbody", {}, shown.map(row)),
      ),
    ),
    rows.length > MAX_ROWS && h("p", { class: "muted small" }, `Showing ${MAX_ROWS} of ${rows.length}. Narrow the filters to see the rest.`),
  );
}

function row(mapping) {
  const { target, chosen } = mapping;
  const select = () => {
    store.mappings.selected = target.key;
    changed();
    document.querySelector(".detail")?.scrollIntoView({ block: "nearest" });
  };
  return h(
    "tr",
    {
      class: `clickable ${store.mappings.selected === target.key ? "selected" : ""}`,
      tabindex: 0,
      onclick: select,
      onkeydown: (event) => event.key === "Enter" && select(),
    },
    h(
      "td",
      {},
      h("div", { class: "mono" }, target.path, target.required && h("span", { class: "small", title: "required", style: { color: "var(--unmapped)" } }, " *")),
      h("div", { class: "small muted" }, target.endpoint, target.variant && h("span", { class: "chip" }, target.variant)),
    ),
    h("td", {}, statusPill(mapping.status), mapping.notes.length > 0 && h("div", { class: "small muted", title: mapping.notes.join("\n") }, `${mapping.notes.length} note(s)`)),
    h("td", {}, scoreBar(chosen?.score)),
    h("td", {}, chosen ? [h("span", { class: "chip api" }, chosen.source.api), " ", h("span", { class: "mono" }, chosen.source.path), h("div", { class: "small muted" }, chosen.source.endpoint)] : h("span", { class: "muted" }, "—")),
    h("td", { class: "small" }, chosen?.transforms.map((t) => h("div", { title: t.description }, t.kind)) ?? ""),
  );
}

function detail(mapping) {
  const { target, chosen } = mapping;
  const override = store.result.overrides.find((o) => o.target_key === target.key);
  const note = h("textarea", { placeholder: "Why? (saved with the decision)", "aria-label": "Decision note" });
  const decide = (action, sourceKey) =>
    api.setOverride({ target_key: target.key, action, source_key: sourceKey, note: note.value }).then(applyOverrideResponse).catch((e) => toast(e.message));

  return h(
    "div",
    {},
    h("div", { class: "row" }, h("h2", { class: "mono", style: { margin: 0 } }, target.path), h("span", { class: "spacer" }), h("button", { class: "btn small", "aria-label": "Close details", onclick: () => { store.mappings.selected = null; changed(); } }, "✕")),
    h(
      "dl",
      { class: "meta", style: { marginTop: "10px" } },
      metaRow("Endpoint", target.endpoint),
      target.variant && metaRow("Variant", target.variant),
      target.condition && metaRow("Applies when", target.condition),
      metaRow("Type", [target.type, target.format && `(${target.format})`, target.required && "· required", target.nullable && "· nullable"].filter(Boolean).join(" ")),
      target.enum.length > 0 && metaRow("Allowed", h("div", {}, target.enum.slice(0, 14).map((v) => h("span", { class: "chip" }, v)), target.enum.length > 14 && h("span", { class: "small muted" }, ` +${target.enum.length - 14} more`))),
      target.description && metaRow("Description", h("span", { class: "small" }, target.description)),
      target.sample_sources?.length > 0 && metaRow("Documentation examples", h("span", { class: "small" }, target.sample_sources.join(", "))),
    ),
    h("div", { class: "row", style: { marginTop: "10px" } }, statusPill(mapping.status), override && h("span", { class: "pill manual" }, `override: ${override.action}`)),
    mapping.notes.length > 0 && h("ul", { class: "notes small" }, mapping.notes.map((n) => h("li", {}, n))),
    comparisonView(mapping.comparison),
    chosen ? candidateBlock(chosen, "Chosen source") : h("p", { class: "muted" }, "No source chosen."),
    h("h3", {}, "Decide"),
    note,
    h(
      "div",
      { class: "row", style: { marginTop: "6px" } },
      chosen && h("button", { class: "btn", onclick: () => decide("accept", chosen.source.key) }, "Accept"),
      h("button", { class: "btn danger", onclick: () => decide("reject") }, "Reject"),
      override && h("button", { class: "btn", onclick: () => api.clearOverride(target.key).then(applyOverrideResponse).catch((e) => toast(e.message)) }, "Undo override"),
    ),
    mapping.alternatives.length > 0 && [h("h3", {}, "Alternatives"), mapping.alternatives.map((c) => alternative(c, decide))],
    searchBlock(target, decide),
  );
}

function candidateBlock(candidate, title) {
  return h(
    "div",
    {},
    h("h3", {}, title),
    h("div", { class: "row" }, h("span", { class: "chip api" }, candidate.source.api), h("span", { class: "mono" }, candidate.source.path)),
    h("div", { class: "small muted" }, candidate.source.endpoint, " · ", candidate.source.type, candidate.source.format ? ` (${candidate.source.format})` : ""),
    h("div", { style: { margin: "8px 0" } }, scoreBar(candidate.score)),
    candidate.vetoed_by && h("div", { class: "error-box" }, `Vetoed: ${candidate.vetoed_by}`),
    candidate.transforms.length > 0 && h("div", {}, h("h3", {}, "Transforms"), candidate.transforms.map(transformView)),
    candidate.source.sample_sources?.length > 0 && h("p", { class: "small muted" }, "Documentation examples: ", candidate.source.sample_sources.join(", ")),
    candidate.source.sample_context && h("p", { class: "small" }, candidate.source.sample_context),
    h("h3", {}, "Evidence"),
    h(
      "table",
      { class: "evidence" },
      h("tbody", {}, candidate.evidence.map((e) =>
        h(
          "tr",
          { class: e.effect },
          h("td", {}, e.signal),
          h("td", { style: { width: "110px" } }, e.effect === "weighted" ? scoreBar(e.score) : h("span", { class: "mono" }, e.effect === "veto" ? "veto" : `× ${e.score}`)),
          h("td", { class: "small muted" }, e.effect === "weighted" ? `w ${e.weight.toFixed(2)}` : ""),
          h("td", { class: "small" }, e.detail),
        ),
      )),
    ),
  );
}

function transformView(transform) {
  if (transform.kind !== "enum-map") return h("div", { class: "small" }, h("strong", {}, transform.kind), " ", transform.description);
  const pairs = Object.entries(transform.params.mapping ?? {});
  return h(
    "div",
    { class: "small" },
    h("strong", {}, "enum-map"),
    h("div", {}, pairs.map(([from, to]) => h("span", { class: "chip" }, `${from} → ${to}`))),
    (transform.params.unmapped ?? []).length > 0 && h("div", { style: { color: "var(--unmapped)" } }, `No match: ${transform.params.unmapped.join(", ")}`),
    transform.params.from_samples && h("div", { class: "muted" }, "Built from sample values; unseen values will fail."),
  );
}

function alternative(candidate, decide) {
  return h(
    "div",
    { class: "alt" },
    h("div", { class: "row" }, h("span", { class: "chip api" }, candidate.source.api), h("span", { class: "mono small" }, candidate.source.path), h("span", { class: "spacer" }), scoreBar(candidate.score)),
    h("div", { class: "small muted" }, candidate.source.endpoint, candidate.vetoed_by && ` · vetoed: ${candidate.vetoed_by}`),
    h("div", { class: "small muted" }, penalties(candidate)),
    h("button", { class: "btn small", style: { marginTop: "6px" }, onclick: () => decide("choose", candidate.source.key) }, "Use this source"),
  );
}

function searchBlock(target, decide) {
  const results = h("div");
  const input = h("input", { type: "search", placeholder: "e.g. ledger amt", "aria-label": "Search downstream fields" });
  const run = () =>
    api.candidates(target.key, input.value).then(({ candidates, total }) =>
      mount(results, h("p", { class: "small muted" }, `${total} field(s) match; best ${candidates.length} shown with their score for this target.`), candidates.map((c) => alternative(c, decide))),
    ).catch((e) => toast(e.message));
  input.addEventListener("keydown", (event) => event.key === "Enter" && run());
  return h("div", {}, h("h3", {}, "Pick any downstream field"), h("div", { class: "row" }, input, h("button", { class: "btn small", onclick: run }, "Search")), results);
}

function penalties(candidate) {
  return candidate.evidence.filter((e) => e.effect !== "weighted").map((e) => e.detail).join("; ");
}

function metaRow(label, value) {
  return [h("dt", {}, label), h("dd", {}, value)];
}

function select(label, options, value, onChange) {
  const plural = { Endpoint: "endpoints", Variant: "variants", Category: "categories" }[label];
  return h(
    "select",
    { "aria-label": label, onchange: (event) => onChange(event.target.value) },
    h("option", { value: "" }, `All ${plural}`),
    options.map((option) => h("option", { value: option, selected: option === value }, option)),
  );
}
