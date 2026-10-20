import { h, STATUS_LABELS } from "../dom.js";

export const TOP_LEVEL = "(top level)";

export function objectOf(target) {
  const cut = target.path.lastIndexOf(".");
  return cut < 0 ? TOP_LEVEL : target.path.slice(0, cut);
}

// Endpoint → variant ("" when the endpoint has none) → parent object → mappings, in first-seen order.
export function groupTree(rows) {
  const tree = new Map();
  for (const mapping of rows) {
    const variants = tree.get(mapping.target.endpoint) ?? tree.set(mapping.target.endpoint, new Map()).get(mapping.target.endpoint);
    const variant = mapping.target.variant ?? "";
    const objects = variants.get(variant) ?? variants.set(variant, new Map()).get(variant);
    const object = objectOf(mapping.target);
    (objects.get(object) ?? objects.set(object, []).get(object)).push(mapping);
  }
  return tree;
}

export function flatten(level) {
  return [...level.values()].flatMap((child) => (Array.isArray(child) ? child : flatten(child)));
}

export function statusCounts(mappings) {
  const counts = {};
  for (const m of mappings) counts[m.status] = (counts[m.status] ?? 0) + 1;
  return h("span", { class: "group-counts small muted" },
    Object.entries(counts).map(([status, count]) => h("span", { class: `count-${status}`, title: STATUS_LABELS[status] }, `${count} ${STATUS_LABELS[status]}`)));
}
