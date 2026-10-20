import { h, mount } from "../dom.js";

export function enumConversion(step, edited, target, source) {
  const contract = target.enum_contract ?? { values: target.enum ?? [], origin: "specification", definitions: {}, warnings: [], citations: [] };
  const values = contract.values;
  const known = [...new Set([...(source?.enum_contract?.values ?? source?.enum ?? []), ...(source?.observed ?? []), ...(typeof source?.example === "string" ? [source.example] : [])])];
  const pairs = step.editorPairs ?? Object.entries(step.params.mapping ?? {});
  if (!step.editorPairs) for (const value of known) if (!pairs.some(([from]) => from === value)) pairs.push([value, ""]);
  if (!pairs.length) pairs.push(["", ""]);
  step.editorPairs = pairs;
  const region = h("div");
  const coverage = h("p", { class: "small muted", role: "status", "aria-live": "polite" });
  const sync = (notify = true) => {
    const sources = pairs.filter(([from]) => from !== "");
    const duplicates = sources.length !== new Set(sources.map(([from]) => from)).size;
    step.params.mapping = Object.fromEntries(sources.filter(([, to]) => to !== ""));
    step.params.unmapped = sources.filter(([, to]) => to === "").map(([from]) => from);
    coverage.textContent = duplicates ? "Duplicate source values: remove the duplicate row before saving." : `${sources.filter(([, to]) => to !== "").length}/${sources.length} listed values have an output. Unlisted strings follow the unknown-value setting below.`;
    region.dataset.invalid = String(duplicates);
    if (notify) edited();
  };
  const output = (pair, index) => values.length ? h("select", {
    "aria-label": `Output value ${index + 1}`, onchange: (e) => { pair[1] = e.target.value; sync(); },
  }, h("option", { value: "", selected: !pair[1] }, "Choose allowed output…"),
  pair[1] && !values.includes(pair[1]) && h("option", { value: pair[1], selected: true }, `${pair[1]} (no longer allowed)`),
  values.map((value) => h("option", { value, selected: pair[1] === value }, value))) : h("input", {
    type: "text", value: pair[1], placeholder: "Output value", "aria-label": `Output value ${index + 1}`,
    oninput: (e) => { pair[1] = e.target.value; sync(); },
  });
  const render = () => mount(region, pairs.map((pair, index) => h("div", { class: "enum-pair" },
    h("input", { type: "text", value: pair[0], placeholder: "Downstream string", "aria-label": `Source value ${index + 1}`, oninput: (e) => { pair[0] = e.target.value; sync(); } }),
    h("span", { "aria-hidden": "true" }, "→"), output(pair, index),
    h("button", { class: "btn small", "aria-label": `Remove value pair ${index + 1}`, onclick: () => { pairs.splice(index, 1); sync(); render(); } }, "×"))),
    h("button", { class: "btn small", onclick: () => { pairs.push(["", ""]); render(); } }, "+ Value pair"));
  render(); sync(false);
  const modes = [["exact", "Exact strings"], ["trim-case", "Trim spaces and ignore case"], ["trim-case-separators", "Also treat spaces, hyphens and underscores alike"]];
  const unknown = h("select", { "aria-label": "Unknown string handling", onchange: (e) => {
    if (e.target.value === "") delete step.params.fallback;
    else step.params.fallback = e.target.value;
    edited();
  } }, h("option", { value: "", selected: !Object.hasOwn(step.params, "fallback") }, "Report a conversion error"),
  values.map((value) => h("option", { value, selected: value === step.params.fallback }, `Use ${value}`)));
  return h("div", { class: "enum-editor" },
    h("p", { class: "small" }, values.length ? `Allowed outputs from ${contract.origin}: ${values.join(", ")}` : "No allowed set found. The specification and documentation do not declare allowed values. Enter a translation for review."),
    (contract.warnings ?? []).map((warning) => h("p", { class: "warn" }, warning)),
    (step.params.translation_warnings ?? []).map((warning) => h("p", { class: "warn" }, warning)),
    [...(contract.citations ?? []), ...(step.params.citations ?? [])].length > 0 && h("details", {}, h("summary", {}, "Value definitions"),
      [["Source", source?.enum_contract], ["Output", contract]].flatMap(([label, definition]) =>
        Object.entries(definition?.definitions ?? {}).flatMap(([value, clues]) =>
          clues.map((clue) => h("p", { class: "small" }, `${label} ${value}: ${clue.text} (${clue.location})`)))),
      [...new Set([...(contract.citations ?? []), ...(step.params.citations ?? [])])].map((text) => h("p", { class: "small muted" }, text))),
    region, coverage,
    h("label", { class: "field" }, "Match incoming strings", h("select", { "aria-label": "String normalization", onchange: (e) => { step.params.normalization = e.target.value; edited(); } },
      modes.map(([value, label]) => h("option", { value, selected: value === (step.params.normalization ?? "exact") }, label)))),
    h("label", { class: "field" }, "When a string has no translation", unknown),
    h("p", { class: "small muted" }, "Null stays null. A fallback applies only to unknown strings; it does not infer their meaning."));
}
