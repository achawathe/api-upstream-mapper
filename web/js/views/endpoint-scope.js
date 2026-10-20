import { api } from "../api.js";
import { h, mount, toast } from "../dom.js";
import { refreshWorkspace } from "../state.js";

export function endpointScopeCard() {
  const body = h("div", {}, h("p", { class: "muted small" }, "Loading upstream endpoints…"));
  api.upstreamEndpoints().then(({ endpoints }) => mount(body, picker(endpoints)), (error) => mount(body, h("p", { class: "small warn" }, error.message)));
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "Endpoints to map"),
    h("p", { class: "muted small" }, "Choose the upstream endpoints you need. Only those are mapped; any downstream API can still supply them. With none selected, every endpoint is mapped."),
    body,
  );
}

function picker(endpoints) {
  if (!endpoints.length) return h("p", { class: "muted small" }, "The upstream spec has no endpoints with response fields.");
  const boxes = endpoints.map((endpoint) => h("input", { type: "checkbox", checked: endpoint.selected, value: endpoint.key, "aria-label": endpoint.key, onchange: () => update() }));
  const rows = endpoints.map((endpoint, i) => h("label", { class: "scope-row" }, boxes[i], h("span", { class: "mono" }, endpoint.key), h("span", { class: "spacer" }), h("span", { class: "small muted" }, `${endpoint.fields} fields`)));
  const count = h("span", { class: "small muted" });
  const search = h("input", { type: "search", placeholder: "Filter endpoints", "aria-label": "Filter endpoints", oninput: () => update() });
  const visible = (i) => !search.value.trim() || endpoints[i].key.toLowerCase().includes(search.value.trim().toLowerCase());
  const update = () => {
    rows.forEach((row, i) => { row.hidden = !visible(i); });
    const chosen = boxes.filter((box) => box.checked);
    const fields = endpoints.reduce((sum, endpoint, i) => sum + (boxes[i].checked ? endpoint.fields : 0), 0);
    count.textContent = chosen.length ? `${chosen.length} of ${endpoints.length} selected · ${fields} fields` : `All ${endpoints.length} endpoints will be mapped`;
  };
  const setVisible = (checked) => { boxes.forEach((box, i) => { if (visible(i)) box.checked = checked; }); update(); };
  const save = async () => {
    try {
      await api.setEndpointScope(boxes.filter((box) => box.checked).map((box) => box.value));
      toast("Endpoint selection saved; run again to apply");
      await refreshWorkspace();
    } catch (error) { toast(error.message); }
  };
  update();
  return h(
    "div",
    {},
    h("div", { class: "row" }, search, h("button", { class: "btn small", onclick: () => setVisible(true) }, "Select shown"), h("button", { class: "btn small", onclick: () => setVisible(false) }, "Clear shown")),
    h("div", { class: "scope-list" }, rows),
    h("div", { class: "row", style: { marginTop: "10px" } }, count, h("span", { class: "spacer" }), h("button", { class: "btn", onclick: save }, "Save selection")),
  );
}
