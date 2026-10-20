import { api } from "../api.js";
import { h, toast } from "../dom.js";
import { refreshWorkspace, store } from "../state.js";

export function documentationCard() {
  const specs = (store.workspace?.files ?? []).filter((f) => ["upstream", "downstream"].includes(f.role) && f.summary?.ok);
  const selected = h("select", { "aria-label": "API for supporting documentation" }, h("option", { value: "" }, "Choose an API"),
    specs.map((f) => h("option", { value: f.id }, `${f.role}: ${f.name}`)));
  const scope = h("select", { "aria-label": "Documentation scope" }, h("option", { value: "" }, "Multiple endpoints / whole API"));
  selected.onchange = async () => {
    const id = selected.value;
    scope.replaceChildren(h("option", { value: "" }, "Multiple endpoints / whole API"));
    if (!id) return;
    try {
      const { endpoints } = await api.fileEndpoints(id);
      if (selected.value === id) scope.append(...endpoints.map((key) => h("option", { value: key }, key)));
    } catch (error) { toast(error.message); }
  };
  const files = h("input", { type: "file", multiple: true, accept: ".pdf,.docx,.txt,.md,.markdown", "aria-label": "Supporting documentation files" });
  const text = h("textarea", { rows: 5, placeholder: "GET /weather\nreading: Current air temperature in degrees Celsius.", "aria-label": "Paste supporting documentation" });
  const attach = h("button", { class: "btn", onclick: async () => {
    if (!selected.value) return toast("Choose the API this documentation describes");
    const uploads = [...files.files];
    if (text.value.trim()) uploads.push(new File([text.value], "pasted-documentation.txt", { type: "text/plain" }));
    if (!uploads.length) return toast("Choose a document or paste text");
    attach.disabled = true;
    try {
      await api.attachDocumentation(selected.value, scope.value, uploads);
      toast("Documentation attached; run mapping to use it");
      await refreshWorkspace();
    } catch (error) { toast(error.message); attach.disabled = false; }
  } }, "Attach documentation");
  const attachments = (store.workspace?.documentation ?? []).map((document) => h("div", { class: "file-row" },
    h("div", {}, h("strong", {}, specs.find((f) => f.id === document.file_id)?.name ?? "API"),
      h("div", { class: "small muted" }, document.names.join(", "), document.endpoint ? ` · ${document.endpoint}` : " · multiple endpoints")),
    h("button", { class: "btn small", "aria-label": `Remove documentation ${document.names.join(", ")}`, onclick: async () => {
      try { await api.removeDocumentation(document.id); await refreshWorkspace(); } catch (error) { toast(error.message); }
    } }, "Remove")));
  return h("div", { class: "card" }, h("h2", {}, "Supporting documentation (optional)"),
    h("p", { class: "small muted" }, "Add details about what this API returns: field meanings, units, formats and allowed values. Include field names and endpoint headings for documents covering several endpoints. The mapper compares these definitions with the other API. You do not need to describe how to map them."),
    h("label", { class: "field" }, "API", selected), h("label", { class: "field" }, "Applies to", scope),
    h("label", { class: "field" }, "PDF, DOCX, TXT or Markdown", files),
    h("details", {}, h("summary", {}, "Or paste documentation"), text),
    h("details", {}, h("summary", {}, "Example API details"),
      h("p", { class: "small muted" }, 'Describe values in this API’s own terms. Specification enums take precedence over documented lists.'),
      h("pre", { class: "small" }, 'GET /orders\nstatus: Allowed values: PROCESSING, COMPLETED, UNKNOWN.\nstatus: PROCESSING means the order is being prepared.\nstatus: COMPLETED means the order has been fulfilled.')),
    h("p", { class: "small muted" }, "Text-based PDFs only. Documents stay on this machine; attaching them does not retrain the model."), attach,
    attachments.length > 0 && h("details", { style: { marginTop: "12px" } }, h("summary", {}, `Attached documentation (${attachments.length})`), attachments));
}
