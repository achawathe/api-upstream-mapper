export function h(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value == null || value === false) continue;
    if (key === "class") element.className = value;
    else if (key.startsWith("on")) element.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "style" && typeof value === "object") Object.assign(element.style, value);
    else if (key === "value") element.value = value;
    else element.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    element.append(child instanceof Node ? child : String(child));
  }
  return element;
}

export function mount(container, ...children) {
  container.replaceChildren(...children.flat(Infinity).filter((c) => c != null && c !== false));
}

export const STATUS_LABELS = {
  auto: "auto",
  review: "needs review",
  unmapped: "unmapped",
  derived: "derived",
  manual: "manual",
  rejected: "rejected",
};

export const STATUS_COLORS = {
  auto: "var(--auto)",
  review: "var(--review)",
  unmapped: "var(--unmapped)",
  derived: "var(--derived)",
  manual: "var(--manual)",
  rejected: "var(--rejected)",
};

export function statusPill(status) {
  return h("span", { class: `pill ${status}` }, STATUS_LABELS[status] ?? status);
}

export function scoreBar(score) {
  if (score == null) return h("span", { class: "muted" }, "—");
  const tone = score >= 0.72 ? "good" : score >= 0.5 ? "mid" : "bad";
  return h(
    "div",
    { class: "row", title: score.toFixed(3) },
    h("div", { class: `bar ${tone}` }, h("span", { style: { width: `${Math.round(score * 100)}%` } })),
    h("span", { class: "small mono" }, score.toFixed(2)),
  );
}

export function stackedBar(counts, total) {
  return h(
    "div",
    { class: "stacked", role: "img", "aria-label": Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(", ") },
    Object.entries(counts)
      .filter(([, value]) => value > 0)
      .map(([status, value]) =>
        h("span", { title: `${STATUS_LABELS[status] ?? status}: ${value}`, style: { width: `${(value / total) * 100}%`, background: STATUS_COLORS[status] } }),
      ),
  );
}

export function sourceText(source) {
  if (!source) return "";
  return `${source.api} · ${source.path}`;
}

export function percent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

export function toast(message) {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (element.hidden = true), 3500);
}

export function dropzone(label, onFiles, { multiple = true, accept = ".yaml,.yml,.json" } = {}) {
  const input = h("input", { type: "file", multiple, accept, hidden: true, onchange: () => input.files.length && onFiles([...input.files]) });
  const zone = h(
    "div",
    {
      class: "dropzone",
      tabindex: 0,
      role: "button",
      onclick: () => input.click(),
      onkeydown: (event) => (event.key === "Enter" || event.key === " ") && input.click(),
      ondragover: (event) => {
        event.preventDefault();
        zone.classList.add("over");
      },
      ondragleave: () => zone.classList.remove("over"),
      ondrop: (event) => {
        event.preventDefault();
        zone.classList.remove("over");
        if (event.dataTransfer.files.length) onFiles([...event.dataTransfer.files]);
      },
    },
    label,
    input,
  );
  return zone;
}
