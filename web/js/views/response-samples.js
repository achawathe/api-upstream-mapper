import { api } from "../api.js";
import { h, toast } from "../dom.js";
import { refreshWorkspace, store } from "../state.js";

export function responseSamplesCard() {
  const specs = (store.workspace?.files ?? []).filter((f) => ["upstream", "downstream"].includes(f.role) && f.summary?.ok);
  const selected = h("select", { "aria-label": "API for documentation examples" },
    h("option", { value: "" }, "Choose an uploaded API"),
    specs.map((f) => h("option", { value: f.id }, `${f.role}: ${f.name}`)));
  const endpoint = h("select", { "aria-label": "Response endpoint", disabled: true }, h("option", {}, "Choose an API first"));
  const files = h("input", { type: "file", multiple: true, accept: ".json", "aria-label": "Documentation JSON responses" });
  const attach = h("button", { class: "btn", disabled: true, onclick: async () => {
    if (!files.files.length) return toast("Choose at least one JSON response body");
    try {
      await api.attachResponseSamples(selected.value, endpoint.value, [...files.files]);
      toast("Response examples attached; run mapping to apply");
      await refreshWorkspace();
    } catch (error) { toast(error.message); }
  } }, "Attach examples");
  selected.onchange = async () => {
    const fileId = selected.value;
    endpoint.disabled = attach.disabled = true;
    endpoint.replaceChildren(h("option", {}, "Loading endpoints…"));
    if (!fileId) {
      endpoint.replaceChildren(h("option", {}, "Choose an API first"));
      return;
    }
    try {
      const result = await api.fileEndpoints(fileId);
      if (selected.value !== fileId) return;
      endpoint.replaceChildren(...result.endpoints.map((key) => h("option", { value: key }, key)));
      endpoint.disabled = attach.disabled = !result.endpoints.length;
    } catch (error) {
      endpoint.replaceChildren(h("option", {}, "Could not load endpoints"));
      toast(error.message);
    }
  };
  const attachments = (store.workspace?.response_samples ?? []).map((sample) => {
    const name = specs.find((f) => f.id === sample.file_id)?.name ?? "API";
    return h("div", { class: "file-row" },
      h("div", {}, h("strong", {}, `${name} · ${sample.endpoint}`), h("div", { class: "small muted" }, sample.names.join(", "))),
      h("button", { class: "btn small", "aria-label": `Remove examples for ${sample.endpoint}`, onclick: async () => {
        try { await api.removeResponseSamples(sample.id); await refreshWorkspace(); }
        catch (error) { toast(error.message); }
      } }, "Remove"));
  });
  return h("div", { class: "card" },
    h("h2", {}, "Documentation response examples"),
    h("p", { class: "small muted" }, "Attach JSON success-response bodies copied from documentation to an uploaded API endpoint. Examples help compare values and provide context for local NLP; the spec's fields, types and requirements remain authoritative."),
    h("label", { class: "field" }, "API", selected),
    h("label", { class: "field" }, "Endpoint", endpoint),
    h("div", { class: "row", style: { marginTop: "10px" } }, files, attach), attachments);
}
