import { h, mount } from "../dom.js";
import { enumConversion } from "./enum-conversion.js";

const KINDS = [
  ["cast", "Change type"], ["enum-map", "Normalize to allowed values"], ["minor-units-to-decimal", "Move decimal point"],
  ["epoch-millis-to-datetime", "Milliseconds → date and time"], ["epoch-seconds-to-datetime", "Seconds → date and time"],
  ["compact-date-to-iso", "YYYYMMDD → date"], ["datetime-to-date", "Date and time → date"],
];

export function conversionBlocks(draft, edited, target) {
  const region = h("div", { class: "conversion-stack" });
  const update = () => { edited(); render(); };
  const move = (from, to) => {
    if (from < 0 || to < 0 || from >= draft.transforms.length || to >= draft.transforms.length) return;
    const [step] = draft.transforms.splice(from, 1);
    draft.transforms.splice(to, 0, step);
    update();
  };
  function render() {
    const blocks = draft.transforms.map((step, index) => h("div", {
      class: "mapping-block conversion", draggable: "true",
      ondragstart: (event) => { event.dataTransfer.setData("application/x-mapping-step", String(index)); event.dataTransfer.effectAllowed = "copyMove"; },
      ondragenter: (event) => { if (event.dataTransfer.types.includes("application/x-mapping-step")) event.preventDefault(); },
      ondragover: (event) => { if (event.dataTransfer.types.includes("application/x-mapping-step")) { event.preventDefault(); event.currentTarget.classList.add("drag-over"); } },
      ondragleave: (event) => event.currentTarget.classList.remove("drag-over"),
      ondragend: () => region.querySelectorAll(".drag-over").forEach((block) => block.classList.remove("drag-over")),
      ondrop: (event) => {
        event.currentTarget.classList.remove("drag-over");
        event.preventDefault(); event.stopPropagation();
        const value = event.dataTransfer.getData("application/x-mapping-step");
        if (value !== "") move(Number(value), index);
      },
    }, h("div", { class: "row" }, h("span", { class: "drag-handle", "aria-hidden": "true" }, "⠿"),
      h("strong", {}, `${index + 1}. ${KINDS.find(([kind]) => kind === step.kind)?.[1] ?? step.kind}`), h("span", { class: "spacer" }),
      h("button", { class: "btn small", disabled: index === 0, "aria-label": `Move step ${index + 1} up`, onclick: () => move(index, index - 1) }, "↑"),
      h("button", { class: "btn small", disabled: index === draft.transforms.length - 1, "aria-label": `Move step ${index + 1} down`, onclick: () => move(index, index + 1) }, "↓"),
      h("button", { class: "btn small", "aria-label": `Remove step ${index + 1}`, onclick: () => { draft.transforms.splice(index, 1); update(); } }, "Remove")),
      parameters(step, edited, target, draft.source?.source)));
    const kind = h("select", { "aria-label": "Conversion to add" }, KINDS.map(([value, label]) => h("option", { value }, label)));
    mount(region, blocks.length ? blocks : h("p", { class: "small muted" }, "Direct connection · no conversion steps"),
      h("div", { class: "row conversion-add" }, kind, h("button", { class: "btn small", onclick: () => {
        const params = kind.value === "cast" ? { to: "integer" } : kind.value === "enum-map" ? { mapping: {} } : kind.value === "minor-units-to-decimal" ? { exponent: 2 } : {};
        draft.transforms.push({ kind: kind.value, params }); update();
      } }, "+ Add step")));
  }
  render();
  return region;
}

function parameters(step, edited, target, source) {
  if (step.kind === "cast") return h("label", { class: "field" }, "Convert to", h("select", {
    "aria-label": "Conversion output type", onchange: (event) => { step.params.to = event.target.value; edited(); },
  }, ["string", "integer", "number", "boolean", "date-time"].map((value) => h("option", { value, selected: value === step.params.to }, value))));
  if (step.kind === "minor-units-to-decimal") return h("label", { class: "field" }, "Decimal places", h("input", {
    type: "number", min: 0, max: 9, value: step.params.exponent ?? 2, "aria-label": "Decimal places",
    oninput: (event) => { step.params.exponent = Number(event.target.value); edited(); },
  }));
  if (step.kind !== "enum-map") return null;
  return enumConversion(step, edited, target, source);
}
