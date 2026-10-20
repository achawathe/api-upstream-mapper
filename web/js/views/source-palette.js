import { api } from "../api.js";
import { h, mount, toast } from "../dom.js";

export function sourcePalette(mapping, choose, available) {
  const region = h("div", { class: "source-results" });
  const draw = (candidates) => {
    candidates.forEach((c) => available.set(c.source.key, c));
    mount(region, candidates.length ? candidates.map((candidate) => h("div", {
      class: "source-tile", draggable: "true",
      ondragstart: (event) => { event.dataTransfer.setData("application/x-mapping-source", candidate.source.key); event.dataTransfer.effectAllowed = "copy"; },
    }, h("div", { class: "row" }, h("span", { class: "drag-handle", "aria-hidden": "true" }, "⠿"), h("strong", { class: "mono" }, candidate.source.path)),
    h("p", { class: "small muted" }, candidate.source.api, " · ", candidate.source.type),
    h("p", { class: "small muted" }, candidate.source.endpoint),
    candidate.vetoed_by && h("p", { class: "small warn" }, candidate.vetoed_by),
    h("button", { class: "btn small", onclick: () => choose(candidate) }, "Connect source"))) : h("p", { class: "small muted" }, "No candidates found. Search another field or endpoint."));
  };
  const search = h("input", { type: "search", placeholder: "Field or endpoint…", "aria-label": "Find source blocks" });
  let sequence = 0;
  const find = async () => {
    const request = ++sequence;
    try {
      const response = await api.candidates(mapping.target.key, search.value);
      if (request === sequence && region.isConnected) draw(response.candidates);
    } catch (error) { toast(error.message); }
  };
  search.addEventListener("keydown", (event) => event.key === "Enter" && find());
  draw([...(mapping.chosen ? [mapping.chosen] : []), ...mapping.alternatives]);
  return h("aside", { class: "card palette", "aria-label": "Source blocks" }, h("h2", {}, "Source blocks"),
    h("p", { class: "small muted" }, "Drag into the connection slot, or choose Connect source."),
    h("div", { class: "row palette-search" }, search, h("button", { class: "btn small", onclick: find }, "Find")), region);
}
