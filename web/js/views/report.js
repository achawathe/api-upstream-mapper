import { h, mount, percent, stackedBar, statusPill } from "../dom.js";
import { changed, navigate, store } from "../state.js";

const MAPPED = new Set(["auto", "review", "manual", "derived"]);

export function renderReport(container) {
  const { mappings, summary, accuracy, downstreams, warnings } = store.result;
  const total = mappings.length;
  const mapped = mappings.filter((m) => MAPPED.has(m.status)).length;
  const required = mappings.filter((m) => m.target.required);
  const requiredMapped = required.filter((m) => MAPPED.has(m.status)).length;
  mount(
    container,
    h(
      "div",
      { class: "kpis" },
      kpi(percent(mapped / total), `fields mapped (${mapped}/${total})`),
      kpi(percent(required.length ? requiredMapped / required.length : 1), `required fields mapped (${requiredMapped}/${required.length})`),
      kpi(summary.auto, "decided automatically"),
      kpi(summary.review, "waiting for review"),
      kpi(downstreams.length, "downstream APIs"),
    ),
    h("div", { class: "card", style: { marginTop: "14px" } }, h("h2", {}, "Status mix"), stackedBar(summary, total)),
    h("div", { class: "row", style: { margin: "14px 0" } },
      h("a", { class: "btn primary", href: "/api/report.xlsx" }, "Download Excel report"),
      h("a", { class: "btn", href: "/api/report.json" }, "Download JSON"),
    ),
    accuracy && accuracyCard(accuracy),
    h("div", { class: "grid grid-2", style: { marginTop: "14px" } }, coverageCard(mappings), contributionCard(mappings, downstreams)),
    gapsCard(mappings),
    warnings.length > 0 && h("div", { class: "card", style: { marginTop: "14px" } }, h("h2", {}, "Warnings"), h("ul", { class: "small" }, warnings.map((w) => h("li", {}, w)))),
  );
}

function accuracyCard(accuracy) {
  const failures = Object.entries(accuracy.failures);
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "Accuracy against the answer key"),
    h(
      "div",
      { class: "kpis" },
      kpi(percent(accuracy.auto_precision), "precision of automatic decisions"),
      kpi(percent(accuracy.recall), "expected mappings surfaced"),
      kpi(percent(accuracy.auto_recall), "expected mappings needing no review"),
      kpi((accuracy.counts["wrong-auto"] ?? 0) + (accuracy.counts["spurious-auto"] ?? 0), "wrong automatic decisions"),
    ),
    h("p", { class: "small muted" }, accuracy.summary),
    failures.length > 0 && h("details", {}, h("summary", {}, `${failures.length} disagreement(s) with the key`), h("ul", { class: "small mono" }, failures.map(([key, text]) => h("li", {}, `${text} — ${key}`)))),
  );
}

function coverageCard(mappings) {
  const byEndpoint = groupBy(mappings, (m) => m.target.endpoint);
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "Coverage per upstream endpoint"),
    h(
      "table",
      {},
      h("thead", {}, h("tr", {}, h("th", {}, "Endpoint"), h("th", {}, "Mapped"), h("th", {}, "Required"))),
      h("tbody", {}, Object.entries(byEndpoint).map(([endpoint, items]) => {
        const req = items.filter((m) => m.target.required);
        return h(
          "tr",
          {},
          h("td", { class: "mono small" }, endpoint),
          h("td", {}, ratio(items.filter((m) => MAPPED.has(m.status)).length, items.length)),
          h("td", {}, ratio(req.filter((m) => MAPPED.has(m.status)).length, req.length)),
        );
      })),
    ),
  );
}

function contributionCard(mappings, downstreams) {
  const counts = groupBy(mappings.filter((m) => m.chosen && MAPPED.has(m.status)), (m) => m.chosen.source.api);
  const max = Math.max(1, ...Object.values(counts).map((items) => items.length));
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "Fields supplied per downstream API"),
    downstreams.map((api) => {
      const supplied = counts[api.name]?.length ?? 0;
      return h(
        "div",
        { class: "row", style: { marginBottom: "6px" } },
        h("span", { class: "chip api", style: { minWidth: "120px" } }, api.name),
        h("div", { class: "bar", style: { flex: 1 } }, h("span", { style: { width: `${(supplied / max) * 100}%` } })),
        h("span", { class: "mono small", style: { width: "40px", textAlign: "right" } }, supplied),
        supplied === 0 && h("span", { class: "small muted" }, "unused"),
      );
    }),
  );
}

function gapsCard(mappings) {
  const gaps = mappings.filter((m) => m.status === "unmapped" || m.status === "rejected").sort((a, b) => Number(b.target.required) - Number(a.target.required));
  const requiredGaps = gaps.filter((m) => m.target.required);
  return h(
    "div",
    { class: "card", style: { marginTop: "14px" } },
    h("h2", {}, `Gaps: ${gaps.length} field(s) without a source, ${requiredGaps.length} of them required`),
    requiredGaps.length === 0 && h("p", { class: "small muted" }, "Every required field has a source."),
    h(
      "table",
      {},
      h("thead", {}, h("tr", {}, h("th", {}, "Field"), h("th", {}, "Status"), h("th", {}, "Closest candidate"))),
      h("tbody", {}, gaps.slice(0, 200).map((m) =>
        h(
          "tr",
          {
            class: "clickable",
            onclick: () => {
              store.mappings.selected = m.target.key;
              navigate("mappings");
              changed();
            },
          },
          h("td", {}, h("span", { class: "mono" }, m.target.path), m.target.required && " *", h("div", { class: "small muted" }, m.target.endpoint, m.target.variant && ` · ${m.target.variant}`)),
          h("td", {}, statusPill(m.status)),
          h("td", { class: "small" }, m.alternatives[0] ? `${m.alternatives[0].source.api} · ${m.alternatives[0].source.path} (${m.alternatives[0].score.toFixed(2)})` : h("span", { class: "muted" }, "nothing similar")),
        ),
      )),
    ),
  );
}

function ratio(part, whole) {
  if (!whole) return h("span", { class: "muted small" }, "—");
  const value = part / whole;
  return h("div", { class: "row" }, h("div", { class: `bar ${value >= 0.9 ? "good" : value >= 0.5 ? "mid" : "bad"}` }, h("span", { style: { width: `${value * 100}%` } })), h("span", { class: "small mono" }, `${part}/${whole}`));
}

function groupBy(items, key) {
  const groups = {};
  for (const item of items) (groups[key(item)] ??= []).push(item);
  return groups;
}

function kpi(value, label) {
  return h("div", { class: "kpi" }, h("div", { class: "value" }, value), h("div", { class: "label" }, label));
}
