import { h, mount, scoreBar } from "../dom.js";
import { store } from "../state.js";

export function renderErrors(container) {
  const errors = store.result.errors;
  if (!errors.length) {
    mount(container, h("div", { class: "empty card" }, h("p", {}, "No downstream error responses were found, or no upstream error catalog was provided."), h("p", { class: "small" }, "Add an error catalog on the Inputs page to map error codes.")));
    return;
  }
  const region = h("div");
  const apis = [...new Set(errors.map((e) => e.api))];
  const filter = h(
    "select",
    { "aria-label": "Downstream API", onchange: () => draw() },
    h("option", { value: "" }, "All downstream APIs"),
    apis.map((api) => h("option", { value: api }, api)),
  );
  const draw = () => mount(region, table(errors.filter((e) => !filter.value || e.api === filter.value)));
  draw();

  const unmappedCodes = errors.filter((e) => !e.upstream_code).length;
  mount(
    container,
    h(
      "div",
      { class: "kpis", style: { marginBottom: "14px" } },
      kpi(errors.length, "downstream error responses"),
      kpi(errors.length - unmappedCodes, "mapped to an upstream code"),
      kpi(unmappedCodes, "passed through by HTTP status"),
    ),
    h("div", { class: "toolbar" }, filter, h("span", { class: "small muted" }, "Rules: keyword match against the catalog, else HTTP status passthrough; 502/503/504 become 503 and other 5xx become 500.")),
    region,
  );
}

function table(rows) {
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      {},
      h("thead", {}, h("tr", {}, ["Downstream", "Status", "Code", "Message", "→ Upstream status", "Upstream code", "Rule", "Confidence"].map((t) => h("th", {}, t)))),
      h(
        "tbody",
        {},
        rows.map((e) =>
          h(
            "tr",
            {},
            h("td", {}, h("span", { class: "chip api" }, e.api), h("div", { class: "small muted mono" }, e.endpoint)),
            h("td", { class: "mono" }, e.downstream_status),
            h("td", { class: "mono" }, e.downstream_code ?? "—"),
            h("td", { class: "small" }, e.downstream_message),
            h("td", { class: "mono" }, e.upstream_status),
            h("td", { class: "mono" }, e.upstream_code ?? h("span", { class: "muted" }, "none")),
            h("td", { class: "small" }, e.rule),
            h("td", {}, scoreBar(e.confidence)),
          ),
        ),
      ),
    ),
  );
}

function kpi(value, label) {
  return h("div", { class: "kpi" }, h("div", { class: "value" }, value), h("div", { class: "label" }, label));
}
