import { h } from "../dom.js";

export function comparisonView(comparison) {
  if (!comparison) return null;
  return h("div", {},
    h("h3", {}, "Why this mapping?"),
    h("p", { class: "small" }, comparison.summary),
    comparison.support.length > 0
      ? reasonList("Supporting evidence", comparison.support)
      : h("p", { class: "small muted" }, "No positive matching evidence was recorded."),
    reasonList("What is uncertain", comparison.concerns, "warn"),
    reasonList("Conversions and conditions", comparison.requirements ?? []),
    referenceView(comparison.references),
    comparison.alternatives.length > 0 && h("details", {},
      h("summary", {}, "Compare alternatives"),
      comparison.alternatives.map((other) => h("div", { class: "alt" },
        h("strong", { class: "small mono" }, other.source),
        h("p", { class: "small" }, other.reason),
        other.support.length > 0 && h("p", { class: "small muted" }, other.support[0]),
        referenceView(other.references)))),
    h("p", { class: "small muted" }, comparison.method ?? "Explanation from recorded matching evidence."));
}

function reasonList(title, items, tone = "") {
  return items.length > 0 && h("div", { class: `small ${tone}` }, h("strong", {}, title),
    h("ul", {}, items.slice(0, 3).map((reason) => h("li", {}, reason))),
    items.length > 3 && h("details", {}, h("summary", {}, `More details (${items.length - 3})`),
      h("ul", {}, items.slice(3).map((reason) => h("li", {}, reason)))));
}

function referenceView(references = []) {
  return references.length > 0 && h("details", {}, h("summary", {}, "API definitions and references"),
    references.map((reference) => h("div", { class: "alt small" },
      h("strong", {}, `${reference.side} · ${reference.kind}`),
      h("p", { class: "muted" }, reference.location),
      h("p", {}, reference.text))));
}
