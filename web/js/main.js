import { h, mount, toast } from "./dom.js";
import { canRun, refreshWorkspace, setRenderer, startRun, store } from "./state.js";
import { renderErrors } from "./views/errors.js";
import { renderInputs } from "./views/inputs.js";
import { renderMappings } from "./views/mappings.js";
import { renderPlan } from "./views/plan.js";
import { renderReport } from "./views/report.js";
import { renderRun } from "./views/run.js";
import { renderValidate } from "./views/validate.js";

const VIEWS = [
  { id: "inputs", title: "Inputs", subtitle: "Upstream requirement, downstream APIs, samples and settings", render: renderInputs },
  { id: "run", title: "Run", subtitle: "Each stage of the mapping process, live", render: renderRun },
  { id: "mappings", title: "Mappings", subtitle: "Every upstream field, its source and the evidence behind it", render: renderMappings, needsResult: true },
  { id: "plan", title: "Call plan", subtitle: "Which downstream calls each upstream endpoint needs, in order", render: renderPlan, needsResult: true },
  { id: "errors", title: "Error codes", subtitle: "How downstream failures surface upstream", render: renderErrors, needsResult: true },
  { id: "validate", title: "Validate", subtitle: "Execute the plan against mock downstreams and check the response", render: renderValidate, needsResult: true },
  { id: "report", title: "Report", subtitle: "Coverage, gaps, accuracy and downloads", render: renderReport, needsResult: true },
];

function currentView() {
  const id = location.hash.slice(1) || "inputs";
  return VIEWS.find((v) => v.id === id) ?? VIEWS[0];
}

function render() {
  const view = currentView();
  renderNav(view);
  document.getElementById("view-title").textContent = view.title;
  document.getElementById("view-subtitle").textContent = view.subtitle;
  mount(
    document.getElementById("topbar-actions"),
    store.result && h("a", { class: "btn", href: "/api/report.xlsx" }, "Download Excel"),
    h("button", { class: "btn primary", onclick: startRun, disabled: !canRun() }, "Run mapping"),
  );
  const container = document.getElementById("view");
  if (view.needsResult && !store.result) {
    mount(
      container,
      h("div", { class: "empty card" }, h("p", {}, "Run the mapping first."), h("button", { class: "btn primary", onclick: startRun, disabled: !canRun() }, "Run mapping")),
    );
    return;
  }
  view.render(container);
}

function renderNav(active) {
  const summary = store.result?.summary;
  const badges = {
    mappings: summary ? `${summary.review} to review` : null,
    plan: store.result ? store.result.call_plans.reduce((n, p) => n + p.steps.length, 0) : null,
    errors: store.result ? store.result.errors.length : null,
  };
  mount(
    document.getElementById("nav"),
    VIEWS.map((view, index) =>
      h(
        "a",
        {
          href: `#${view.id}`,
          class: view.id === active.id ? "active" : "",
          "aria-current": view.id === active.id ? "page" : null,
          "aria-disabled": view.needsResult && !store.result ? "true" : null,
        },
        h("span", { class: "step" }, index + 1),
        view.title,
        badges[view.id] != null && h("span", { class: "badge" }, badges[view.id]),
      ),
    ),
  );
}

setRenderer(render);
window.addEventListener("hashchange", () => {
  render();
  document.getElementById("view").focus();
});
refreshWorkspace().catch((error) => toast(error.message));
