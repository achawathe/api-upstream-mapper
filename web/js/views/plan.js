import { h, mount } from "../dom.js";
import { changed, store } from "../state.js";

const SOURCE_LABELS = { "upstream-request": "request", "prior-step": "step", unresolved: "caller context" };

export function renderPlan(container) {
  const plans = store.result.call_plans;
  const active = plans.find((p) => p.upstream_endpoint === store.plan.endpoint) ?? plans.find((p) => p.steps.length) ?? plans[0];
  mount(
    container,
    h(
      "div",
      { class: "plan-layout" },
      h("div", { class: "card plan-list" }, h("h2", {}, "Upstream endpoints"), plans.map((plan) => planLink(plan, plan === active))),
      h("div", {}, active ? planDetail(active) : h("p", { class: "muted" }, "No endpoints.")),
    ),
  );
}

function planLink(plan, isActive) {
  return h(
    "a",
    {
      href: "#plan",
      class: isActive ? "active" : "",
      onclick: (event) => {
        event.preventDefault();
        store.plan.endpoint = plan.upstream_endpoint;
        changed();
      },
    },
    h("div", { class: "mono small" }, plan.upstream_endpoint),
    h(
      "div",
      { class: "small muted" },
      plan.steps.length ? `${plan.steps.length} call(s)` : "no downstream source",
      plan.steps.some((s) => s.fanout) && " · fan-out",
      plan.unresolved_inputs.length > 0 && h("span", { style: { color: "var(--unmapped)" } }, ` · ${plan.unresolved_inputs.length} unresolved`),
    ),
  );
}

function planDetail(plan) {
  const allVariants = new Set(store.result.mappings.filter((m) => m.target.endpoint === plan.upstream_endpoint && m.target.variant).map((m) => m.target.variant));
  if (!plan.steps.length) return h("div", { class: "empty card" }, "No downstream field was mapped to this endpoint, so nothing is called.");
  return h(
    "div",
    {},
    plan.unresolved_inputs.length > 0 &&
      h("div", { class: "warn", style: { marginBottom: "12px" } }, "Inputs nobody supplies (they must come from the caller, e.g. the access token): ", plan.unresolved_inputs.join("; ")),
    h("div", { class: "steps" }, plan.steps.map((step, index) => [index > 0 && h("div", { class: "arrow", "aria-hidden": "true" }, "↓"), stepCard(step, allVariants)])),
    h("p", { class: "small muted", style: { marginTop: "12px" } }, "Calls whose inputs are ready run concurrently. Calls marked for a variant only run once the record is known to be that variant."),
  );
}

function stepCard(step, allVariants) {
  const conditional = step.variants.length > 0 && step.variants.length < allVariants.size;
  return h(
    "div",
    { class: `step-card ${step.supplies_only_inputs ? "inputs-only" : ""} ${step.awaits_review ? "awaiting" : ""}` },
    h(
      "div",
      { class: "row" },
      h("strong", {}, `${step.order}.`),
      h("span", { class: "chip api" }, step.api),
      h("span", { class: "mono" }, step.endpoint),
      h("span", { class: "spacer" }),
      step.fanout && h("span", { class: "pill neutral" }, "× once per item"),
      step.supplies_only_inputs && h("span", { class: "pill neutral" }, "supplies inputs only"),
      step.awaits_review && h("span", { class: "pill review" }, "all fields await review"),
    ),
    conditional && h("div", { class: "small", style: { marginTop: "6px" } }, "Only when the record is ", step.variants.map((v) => h("span", { class: "chip" }, v))),
    h(
      "div",
      { style: { marginTop: "8px" } },
      step.bindings.length ? step.bindings.map(binding) : h("div", { class: "small muted" }, "No inputs."),
    ),
    !step.supplies_only_inputs && h("div", { class: "small muted", style: { marginTop: "6px" } }, `Supplies ${step.supplies_fields} field(s)`, step.pending_review_fields ? `, ${step.pending_review_fields} awaiting review` : ""),
  );
}

function binding(b) {
  const from = b.source === "prior-step" ? `step ${b.from_step}: ${b.reference.split(" -> ")[1]}` : b.source === "upstream-request" ? `request.${b.reference}` : b.reference;
  return h(
    "div",
    { class: `binding ${b.source === "unresolved" ? "unresolved" : ""}` },
    `${b.location ?? "path"} ${b.parameter} ← `,
    h("span", { class: "from" }, from),
    h("span", { class: "muted" }, ` (${SOURCE_LABELS[b.source]}${b.fanout ? ", each item" : ""})`),
  );
}
