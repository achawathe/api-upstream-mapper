import { api } from "../api.js";
import { h, mount, statusPill, toast } from "../dom.js";
import { applyOverrideResponse, changed, store } from "../state.js";
import { comparisonView } from "./candidate-comparison.js";
import { conversionBlocks } from "./conversion-blocks.js";
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
      categoryEditor(mapping), slot, connector(), conversionBlocks(draft, edited, mapping.target), connector(),
      h("div", { class: "mapping-block output" }, h("span", { class: "block-caption" }, "TO · UPSTREAM"),
        h("strong", { class: "mono" }, mapping.target.path), h("span", { class: "chip" }, mapping.target.type),
        mapping.target.description && h("p", { class: "small" }, mapping.target.description)),
      draft.source?.vetoed_by && h("p", { class: "error-box" }, "Compatibility concern: ", draft.source.vetoed_by, ". Saving records your manual choice; it does not resolve this concern."),
      preview(mapping, draft), h("details", { class: "block-evidence" }, h("summary", {}, "Why this suggestion? Evidence and alternatives"), comparisonView(mapping.comparison)),
      note, h("div", { class: "row editor-actions" }, h("button", { class: "btn primary", disabled: !draft.source, onclick: save }, "Save mapping"),
        h("button", { class: "btn", onclick: reject }, "Leave unmapped"),
        h("button", { class: "btn", onclick: () => { delete drafts[mapping.target.key]; changed(); } }, "Discard draft"),
        store.result.overrides.some((o) => o.target_key === mapping.target.key) && h("button", { class: "btn", onclick: undo }, "Restore suggestion"), indicator));
  }
  renderStage();
  return h("div", { class: "block-workbench" }, fieldOrganizer(rows, mapping), palette, stage);
}

function connector() {
  return h("div", { class: "block-connector", "aria-hidden": "true" }, "↓");
}

function fieldOrganizer(rows, selected) {
  const grouping = store.mappings.grouping ?? "endpoint";
  const groups = Map.groupBy(rows, (m) => grouping === "category" ? m.category || "Uncategorized" : m.target.endpoint);
  const choose = h("select", { "aria-label": "Group output fields", onchange: (e) => { store.mappings.grouping = e.target.value; changed(); } },
    h("option", { value: "endpoint", selected: grouping === "endpoint" }, "By endpoint"), h("option", { value: "category", selected: grouping === "category" }, "By category"));
  return h("aside", { class: "card field-organizer", "aria-label": "Output field groups" }, h("h2", {}, `Output fields (${rows.length})`), choose,
    [...groups.entries()].map(([name, mappings]) => h("details", { open: mappings.includes(selected) }, h("summary", {}, `${name} (${mappings.length})`),
      mappings.map((m) => h("button", { class: `field-choice ${m === selected ? "selected" : ""}`, "aria-pressed": String(m === selected), onclick: () => { store.mappings.selected = m.target.key; changed(); } },
        h("span", { class: "mono" }, m.target.path), m.target.variant && h("span", { class: "small muted" }, m.target.variant), statusPill(m.status),
        store.mappings.drafts[m.target.key]?.dirty && h("span", { class: "small" }, "Unsaved"))))));
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
