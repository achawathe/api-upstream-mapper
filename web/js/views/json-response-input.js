import { h } from "../dom.js";

// Pasted responses use the same upload path, validation and provenance as JSON files.
export function jsonResponseInput({ fileLabel, pasteLabel, filename }) {
  const uploads = h("input", { type: "file", multiple: true, accept: ".json", "aria-label": fileLabel });
  const error = h("p", { class: "small", role: "alert", hidden: true, style: { color: "var(--unmapped)" } });
  const text = h("textarea", { rows: 6, class: "mono", "aria-label": pasteLabel,
    placeholder: '{"accountId": "example", "status": "OPEN"}', spellcheck: "false",
    oninput: () => { error.hidden = true; text.removeAttribute("aria-invalid"); } });
  const paste = h("details", { style: { marginTop: "10px" } },
    h("summary", {}, "Or paste JSON"),
    h("label", { class: "field" }, pasteLabel, text), error);

  function readFiles() {
    const files = [...uploads.files];
    const raw = text.value.trim();
    if (raw) {
      try {
        const value = JSON.parse(raw);
        if (value === null || typeof value !== "object") throw new Error("response body required");
      } catch {
        error.textContent = "Enter valid JSON containing an object or array response body.";
        error.hidden = false;
        paste.open = true;
        text.setAttribute("aria-invalid", "true");
        text.focus();
        throw new Error(error.textContent);
      }
      files.push(new File([raw], filename, { type: "application/json" }));
    }
    if (!files.length) throw new Error("Choose a JSON file or paste a JSON response body");
    return files;
  }

  return { element: h("div", {}, uploads, paste), readFiles };
}
