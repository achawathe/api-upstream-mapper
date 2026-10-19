import { h, mount, stackedBar, STATUS_LABELS } from "../dom.js";
import { navigate, store } from "../state.js";

const STAGES = [
  ["load", "Load", "Parse specs and sample payloads, resolve $refs"],
  ["flatten", "Flatten", "Turn every response schema into leaf fields, splitting oneOf variants"],
  ["profile", "Profile", "Translate names to concepts; find account families and role words"],
  ["score", "Score", "Compare candidate pairs on name, type, enum, samples, context"],
  ["assign", "Assign", "Pick a source per field; flag ambiguity and shared sources"],
  ["errors", "Errors", "Map downstream error responses to upstream codes"],
  ["plan", "Plan", "Order downstream calls and bind their inputs"],
];

export function renderRun(container) {
  const { events, done, error, id } = store.run;
  if (!id && !events.length) {
    mount(container, h("div", { class: "empty card" }, h("p", {}, "No run in this session yet. Press Run mapping to start.")));
    return;
  }
  const byStage = groupByStage(events);
  const summary = events.find((e) => e.stage === "assign" && e.state === "info")?.counts;
  mount(
    container,
    h("div", { class: "grid grid-2" },
      h("div", { class: "card" }, h("h2", {}, done ? (error ? "Run failed" : "Run finished") : "Running…"), h("ol", { class: "stages" }, STAGES.map((stage) => stageRow(stage, byStage[stage[0]], done)))),
      h("div", { class: "stack" },
        error && h("div", { class: "error-box" }, error),
        summary && resultCard(summary),
        h("div", { class: "card" }, h("h2", {}, "Event log"), h("div", { class: "log", "aria-live": "polite" }, events.map(formatEvent).join("\n"))),
      ),
    ),
  );
}

function stageRow([key, title, description], stageEvents = [], runDone) {
  const last = stageEvents.at(-1);
  const state = !last ? (runDone ? "skipped" : "pending") : last.state === "info" ? "finished" : last.state === "started" ? "running" : last.state;
  const icon = { pending: "·", skipped: "–", running: "…", finished: "✓", failed: "!" }[state];
  const finished = stageEvents.find((e) => e.state === "finished" || e.state === "failed");
  return h(
    "li",
    {},
    h("span", { class: `stage-icon ${state}`, "aria-label": state }, icon),
    h("strong", {}, title),
    h("div", {}, h("div", { class: "small muted" }, description), finished && h("div", { class: "row small" }, Object.entries(finished.counts).map(([k, v]) => h("span", { class: "chip" }, `${k.replaceAll("_", " ")} ${v}`)))),
    h("span", { class: "small mono muted" }, finished?.elapsed_ms ? `${finished.elapsed_ms} ms` : ""),
  );
}

function resultCard(summary) {
  const total = Object.values(summary).reduce((a, b) => a + b, 0);
  return h(
    "div",
    { class: "card" },
    h("h2", {}, `${total} upstream fields decided`),
    stackedBar(summary, total),
    h("div", { class: "row", style: { marginTop: "10px" } }, Object.entries(summary).filter(([, v]) => v).map(([status, value]) => h("span", { class: `pill ${status}` }, `${STATUS_LABELS[status]} ${value}`))),
    store.result && h("div", { class: "row", style: { marginTop: "12px" } }, h("button", { class: "btn primary", onclick: () => navigate("mappings") }, "Review mappings"), h("a", { class: "btn", href: "/api/report.xlsx" }, "Download Excel")),
  );
}

function groupByStage(events) {
  const grouped = {};
  for (const event of events) (grouped[event.stage] ??= []).push(event);
  return grouped;
}

function formatEvent(event) {
  const counts = Object.entries(event.counts ?? {}).map(([k, v]) => `${k}=${v}`).join(" ");
  const timing = event.elapsed_ms ? ` ${event.elapsed_ms}ms` : "";
  return `[${event.stage}] ${event.state} ${event.message}${timing} ${counts}`.trim();
}
