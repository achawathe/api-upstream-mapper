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

let detailsOpen = false;

function logDetails(events) {
  return h("details", { class: "card", open: detailsOpen, ontoggle: (event) => { detailsOpen = event.target.open; } },
    h("summary", {}, "Run details and activity log"),
    h("p", { class: "small muted" }, "Actions and run stages are saved locally. Payload bodies and sample values are excluded from the activity log."),
    h("a", { class: "btn small", href: "/api/activity?download=true&limit=1000" }, "Download recent activity"),
    events.length > 0 && h("div", { class: "log", style: { marginTop: "10px" } }, events.map(formatEvent).join("\n")));
}

function currentStatus(events, done, error) {
  if (done) return error ? "Mapping stopped. See the error below." : "Mapping complete. Results are ready to review.";
  const latest = events.at(-1);
  if (!latest) return "Starting the mapping…";
  if (latest.stage === "score" && latest.state === "info") return "Preparing local NLP and comparing candidate meanings…";
  const messages = { load: "Reading API definitions and resolving model files…", flatten: "Reading fields and response examples…",
    profile: "Understanding field names and context…", score: "Comparing mapping candidates…",
    assign: "Choosing candidates and flagging uncertain matches…", errors: "Comparing API error codes…", plan: "Preparing the mapping results…" };
  return messages[latest.stage] ?? "Processing the mapping…";
}

export function renderRun(container) {
  const { events, done, error, id } = store.run;
  if (!id && !events.length && !store.run.starting && !error) {
    mount(container, h("div", { class: "empty card" }, h("p", {}, "No run in this session yet. Press Run mapping to start.")), logDetails(events));
    return;
  }
  const byStage = groupByStage(events);
  const summary = events.find((e) => e.stage === "assign" && e.state === "info")?.counts;
  mount(
    container,
    h("div", { class: "grid grid-2" },
      h("div", { class: "card" }, h("h2", {}, done ? (error ? "Run failed" : "Run finished") : "Running…"),
        h("p", { role: "status", "aria-live": "polite" }, currentStatus(events, done, error)),
        h("ol", { class: "stages" }, STAGES.map((stage) => stageRow(stage, byStage[stage[0]], done)))),
      h("div", { class: "stack" },
        error && h("div", { class: "error-box" }, error),
        summary && resultCard(summary),
        logDetails(events),
      ),
    ),
  );
}

function stageRow([key, title, description], stageEvents = [], runDone) {
  const last = stageEvents.filter((event) => event.state !== "info").at(-1);
  const state = !last ? (runDone ? "skipped" : "pending") : last.state === "started" ? (runDone ? "failed" : "running") : last.state;
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
