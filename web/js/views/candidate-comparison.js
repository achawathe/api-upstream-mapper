import { h } from "../dom.js";

export function comparisonView(comparison) {
  if (!comparison) return null;
  return h("div", {},
    h("h3", {}, "Why this choice?"),
    h("p", { class: "small" }, comparison.summary),
    comparison.support.length > 0 && h("ul", { class: "small" }, comparison.support.slice(0, 3).map((reason) => h("li", {}, reason))),
    comparison.concerns.length > 0 && h("p", { class: "small warn" }, comparison.concerns.join(" ")),
    comparison.alternatives.length > 0 && h("details", {},
      h("summary", {}, "Compare alternatives"),
      comparison.alternatives.map((other) => h("div", { class: "alt" },
        h("strong", { class: "small mono" }, other.source),
        h("p", { class: "small" }, other.reason),
        other.support.length > 0 && h("p", { class: "small muted" }, other.support[0])))));
}
