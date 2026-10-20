import { api } from "../api.js";
import { dropzone, h, toast } from "../dom.js";
import { refreshWorkspace } from "../state.js";

export function upstreamModels(file) {
  const attach = async (files) => {
    try {
      const result = await api.attachModelFiles(file.id, files);
      const warnings = result.file.summary?.warnings?.length ?? 0;
      toast(warnings ? `Models attached; ${warnings} warning(s) still need attention` : "Models attached; upstream references checked");
      await refreshWorkspace();
    } catch (error) { toast(error.message); }
  };
  const folder = h("input", { type: "file", webkitdirectory: true, multiple: true, hidden: true, onchange: () => {
    const files = [...folder.files].filter((f) => /\.(json|ya?ml)$/i.test(f.name));
    if (files.length) attach(files);
    else toast("The folder contains no YAML or JSON files");
  } });
  return h("div", { style: { marginTop: "14px" } },
    h("h3", {}, "Upstream model files (optional)"),
    h("p", { class: "small muted" }, "Add the model YAML or JSON files referenced by this spec. Matching filenames are placed at their referenced paths, and the warnings are checked again. Use a folder when filenames repeat."),
    dropzone("Add upstream model files", attach), folder,
    h("button", { class: "btn small", style: { marginTop: "8px" }, onclick: () => folder.click() }, "Choose models folder"),
    file.model_files?.length > 0 && h("details", { style: { marginTop: "8px" } },
      h("summary", {}, `Attached model files (${file.model_files.length})`),
      h("ul", { class: "small muted" }, file.model_files.map((name) => h("li", {}, name)))),
  );
}
