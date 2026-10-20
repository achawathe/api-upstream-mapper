import { api } from "../api.js";
import { h, mount, statusPill, toast } from "../dom.js";
import { applyOverrideResponse, changed, store } from "../state.js";
import { comparisonView } from "./candidate-comparison.js";
import { conversionBlocks } from "./conversion-blocks.js";
import { flatten, groupTree, statusCounts } from "./field-groups.js";
import { sourcePalette } from "./source-palette.js";

export function mappingBlocks(rows) {
  if (!rows.length) return h("div", { class: "card empty" }, "No fields match. Adjust the filters above.");
  const mapping = rows.find((m) => m.target.key === store.mappings.selected) ?? rows[0];
  store.mappings.selected = mapping.target.key;
  const drafts = store.mappings.drafts;
  const draft = drafts[mapping.target.key] ??= {
    source: mapping.chosen, transforms: structuredClone(mapping.chosen?.transforms ?? []),
    note: store.result.overrides.find((o) => o.target_key === mapping.target.key)?.note ?? "", dirty: false,
  };
  const stage = h("section", { class: "card mapping-stage", "aria-label": "Mapping connection and conversion steps" });
  const available = new Map();
  const indicator = h("span", { class: "small muted", role: "status", "aria-live": "polite" }, draft.dirty ? "Unsaved changes" : "Saved state");
  const edited = () => { draft.dirty = true; indicator.textContent = "Unsaved changes"; };
  const choose = (candidate) => {
    draft.source = candidate;
    draft.transforms = structuredClone(candidate.transforms);
    edited(); renderStage();
  };
  const palette = sourcePalette(mapping, choose, available);
  function renderStage() {
    const explanation = h("div", { "aria-live": "polite" }, comparisonView(mapping.comparison));
    let explanationVersion = 0;
    let explanationTimer;
    const refreshExplanation = () => {
      const version = ++explanationVersion;
      clearTimeout(explanationTimer);
      mount(explanation, h("p", { class: "small muted", role: "status" }, "Updating mapping explanation…"));
      explanationTimer = setTimeout(async () => {
        if (!explanation.isConnected || !draft.source) return;
        try {
          const result = await api.explainMapping({
            target_key: mapping.target.key, source_key: draft.source.source.key, transforms: draft.transforms,
          });
          if (version === explanationVersion && explanation.isConnected) mount(explanation, comparisonView(result));
        } catch (error) {
          if (version === explanationVersion && explanation.isConnected) mount(explanation, h("p", { class: "error-box" }, error.message));
        }
      }, 200);
    };
    const slot = h("div", {
      class: "source-slot", "aria-label": "Source connection slot",
      ondragover: (event) => { if (event.dataTransfer.types.includes("application/x-mapping-source")) { event.preventDefault(); slot.classList.add("drag-over"); } },
      ondragleave: () => slot.classList.remove("drag-over"),
      ondrop: (event) => {
        event.preventDefault(); slot.classList.remove("drag-over");
        const candidate = available.get(event.dataTransfer.getData("application/x-mapping-source"));
        if (candidate) choose(candidate);
      },
    }, draft.source ? h("div", { class: "mapping-block source" }, h("span", { class: "block-caption" }, "FROM · DOWNSTREAM"),
      h("strong", { class: "mono" }, draft.source.source.path), h("p", { class: "small" }, `${draft.source.source.api} · ${draft.source.source.endpoint}`),
      h("span", { class: "chip" }, draft.source.source.type)) : h("div", { class: "empty-slot" }, "Drop a source block here", h("p", { class: "small muted" }, "Or use Connect source in the source palette")));
    const note = h("textarea", { rows: 2, value: draft.note, placeholder: "Optional note about this mapping", "aria-label": "Mapping decision note", oninput: (e) => { draft.note = e.target.value; edited(); } });
    const save = async () => {
      if (!draft.source) return toast("Connect a source first");
      if (stage.querySelector('[data-invalid="true"]')) return toast("Remove duplicate source values before saving");
      try {
        const response = await api.setOverride({ target_key: mapping.target.key, source_key: draft.source.source.key, action: "choose", transforms: draft.transforms, note: draft.note });
        delete drafts[mapping.target.key];
        applyOverrideResponse(response); toast("Mapping and conversion steps saved");
      } catch (error) { toast(error.message); }
    };
    const undo = async () => {
      try { const response = await api.clearOverride(mapping.target.key); delete drafts[mapping.target.key]; applyOverrideResponse(response); toast("Automatic suggestion restored"); }
      catch (error) { toast(error.message); }
    };
    const reject = async () => {
      try { const response = await api.setOverride({ target_key: mapping.target.key, action: "reject", note: draft.note }); delete drafts[mapping.target.key]; applyOverrideResponse(response); }
      catch (error) { toast(error.message); }
    };
    mount(stage, h("div", { class: "row" }, h("h2", {}, "Build this mapping"), h("span", { class: "spacer" }), statusPill(mapping.status)),
      h("p", { class: "small muted" }, mapping.target.endpoint, mapping.target.variant ? ` · ${mapping.target.variant}` : ""),
      categoryEditor(mapping), slot, connector(), conversionBlocks(draft, () => { edited(); refreshExplanation(); }, mapping.target), connector(),
      h("div", { class: "mapping-block output" }, h("span", { class: "block-caption" }, "TO · UPSTREAM"),
        h("strong", { class: "mono" }, mapping.target.path), h("span", { class: "chip" }, mapping.target.type),
        mapping.target.description && h("p", { class: "small" }, mapping.target.description)),
      draft.source?.vetoed_by && h("p", { class: "error-box" }, "Compatibility concern: ", draft.source.vetoed_by, ". Saving records your manual choice; it does not resolve this concern."),
      preview(mapping, draft), h("details", { class: "block-evidence", open: true }, h("summary", {}, "Mapping explanation"), explanation),
      note, h("div", { class: "row editor-actions" }, h("button", { class: "btn primary", disabled: !draft.source, onclick: save }, "Save mapping"),
        h("button", { class: "btn", onclick: reject }, "Leave unmapped"),
        h("button", { class: "btn", onclick: () => { delete drafts[mapping.target.key]; changed(); } }, "Discard draft"),
        store.result.overrides.some((o) => o.target_key === mapping.target.key) && h("button", { class: "btn", onclick: undo }, "Restore suggestion"), indicator));
    if (draft.dirty && draft.source) refreshExplanation();
  }
  renderStage();
  return h("div", { class: "block-workbench" }, fieldOrganizer(rows, mapping), palette, stage);
}

function connector() {
  return h("div", { class: "block-connector", "aria-hidden": "true" }, "↓");
}

function fieldOrganizer(rows, selected) {
  const grouping = store.mappings.grouping ?? "endpoint";
  const choose = h("select", { "aria-label": "Group output fields", onchange: (e) => { store.mappings.grouping = e.target.value; changed(); } },
    h("option", { value: "endpoint", selected: grouping === "endpoint" }, "By endpoint, variant and object"), h("option", { value: "category", selected: grouping === "category" }, "By category"));
  const field = (m) => h("button", { class: `field-choice ${m === selected ? "selected" : ""}`, "aria-pressed": String(m === selected), onclick: () => { store.mappings.selected = m.target.key; changed(); } },
    h("span", { class: "mono" }, grouping === "category" ? m.target.path : m.target.path.split(".").at(-1)), grouping === "category" && m.target.variant && h("span", { class: "small muted" }, m.target.variant), statusPill(m.status),
    store.mappings.drafts[m.target.key]?.dirty && h("span", { class: "small" }, "Unsaved"));
  const section = (level, name, mappings, children) => h("details", { class: `field-group ${level}`, open: mappings.includes(selected) },
    h("summary", {}, h("span", { class: level === "object" ? "mono" : "" }, name), ` (${mappings.length}) `, statusCounts(mappings)), children);
  const groups = grouping === "category"
    ? [...Map.groupBy(rows, (m) => m.category || "Uncategorized").entries()].map(([name, mappings]) => section("category", name, mappings, mappings.map(field)))
    : [...groupTree(rows).entries()].map(([endpoint, variants]) => section("endpoint", endpoint, flatten(variants),
      [...variants.entries()].map(([variant, objects]) => {
        const inner = [...objects.entries()].map(([object, mappings]) => section("object", object, mappings, mappings.map(field)));
        return variant ? section("variant", variant, flatten(objects), inner) : inner;
      })));
  return h("aside", { class: "card field-organizer", "aria-label": "Output field groups" }, h("h2", {}, `Output fields (${rows.length})`), choose, groups);
}

function categoryEditor(mapping) {
  const categories = [...new Set(store.result.mappings.map((m) => m.category).filter(Boolean))];
  const input = h("input", { type: "text", value: mapping.category ?? "", placeholder: "e.g. Weather readings", list: "mapping-categories", "aria-label": "Mapping category", maxLength: 80 });
  return h("div", { class: "category-editor row" }, h("label", { class: "field" }, "Category", input),
    h("datalist", { id: "mapping-categories" }, categories.map((name) => h("option", { value: name }))),
    h("button", { class: "btn small", onclick: async () => {
      try { applyOverrideResponse(await api.setCategory(mapping.target.key, input.value)); toast("Category saved"); } catch (error) { toast(error.message); }
    } }, "Set category"));
}

function preview(mapping, draft) {
  const result = h("div", { class: "small", role: "status", "aria-live": "polite" });
  const sample = h("input", { type: "text", placeholder: 'Example as JSON, e.g. "42"', "aria-label": "Conversion example as JSON" });
  return h("details", { class: "block-preview" }, h("summary", {}, "Try a value before saving"),
    h("p", { class: "small muted" }, 'Leave blank to use the source example. Quote strings, for example "42".'),
    h("div", { class: "row" }, sample, h("button", { class: "btn small", onclick: async () => {
      if (!draft.source) return toast("Connect a source first");
      try {
        const body = { target_key: mapping.target.key, source_key: draft.source.source.key, transforms: draft.transforms };
        if (sample.value.trim()) body.sample = JSON.parse(sample.value);
        const response = await api.previewConversion(body);
        mount(result, h("p", { class: "mono" }, `${JSON.stringify(response.input)} → ${JSON.stringify(response.output)}`),
          h("p", { class: response.issues.length ? "warn" : "muted" }, response.issues.length ? response.issues.join("; ") : "Example fits the output field."),
          h("p", { class: "muted" }, response.message));
      } catch (error) { mount(result, h("p", { class: "error-box" }, error.message)); }
    } }, "Preview")), result);
}
