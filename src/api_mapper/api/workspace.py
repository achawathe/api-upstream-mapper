"""Files, settings, overrides and the latest run for the GUI, stored under one folder on disk."""

import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from api_mapper.errors.catalog import load_error_catalog
from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import GradeReport, grade
from api_mapper.loaders import SpecLoadError, load_any, load_document
from api_mapper.matching.assigner import Thresholds
from api_mapper.matching.semantic import NlpSettings
from api_mapper.models import Override, OverrideAction, ProgressEvent, StageState
from api_mapper.normalize.lexicon import DEFAULT_LEXICON, Lexicon
from api_mapper.pipeline.orchestrator import MappingPipeline, PipelineResult
from api_mapper.pipeline.overrides import load_overrides, save_overrides


class FileRole(StrEnum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    CATALOG = "catalog"
    LEXICON = "lexicon"
    ANSWER_KEY = "answer_key"


SINGLE_FILE_ROLES = frozenset({FileRole.UPSTREAM, FileRole.CATALOG, FileRole.ANSWER_KEY})


@dataclass
class StoredFile:
    id: str
    role: FileRole
    name: str
    path: str
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunState:
    id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    error: str | None = None


class Workspace:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.files: list[StoredFile] = []
        self.thresholds = Thresholds()
        self.nlp = NlpSettings()
        self.overrides: list[Override] = load_overrides(self._overrides_path)
        self.result: PipelineResult | None = None
        self.pipeline: MappingPipeline | None = None
        self.runs: dict[str, RunState] = {}
        self._load_index()

    @property
    def _overrides_path(self) -> Path:
        return self.root / "overrides.json"

    @property
    def _index_path(self) -> Path:
        return self.root / "workspace.json"

    def add_file(self, role: FileRole, name: str, content: bytes) -> StoredFile:
        return self.add_files(role, [(name, content)])[0]

    def add_files(self, role: FileRole, uploads: list[tuple[str, bytes]]) -> list[StoredFile]:
        """Files uploaded together share a folder, so a spec can `$ref` its companions.

        Only files that are specs (or the single file of a single-file role) are registered;
        the rest are kept as supporting files.
        """
        with self.lock:
            if role in SINGLE_FILE_ROLES:
                for existing in [f for f in self.files if f.role == role]:
                    self.remove_file(existing.id)
            folder = self.root / "files" / uuid.uuid4().hex[:12]
            folder.mkdir(parents=True, exist_ok=True)
            paths = []
            for name, content in uploads:
                path = folder / Path(name).name
                path.write_bytes(content)
                paths.append(path)
            registered = [p for p in paths if role not in (FileRole.UPSTREAM, FileRole.DOWNSTREAM) or _looks_like_spec(p)]
            if role in SINGLE_FILE_ROLES:
                registered = registered[:1] or paths[:1]
            stored = [StoredFile(uuid.uuid4().hex[:12], role, p.name, str(p), _summarise(role, p)) for p in registered or paths]
            self.files.extend(stored)
            self._save_index()
            return stored

    def add_sample_endpoint(self, api_name: str, method: str, path: str, payloads: list[tuple[str, bytes]]) -> StoredFile:
        """Adds captured responses as one endpoint of a spec-less API, creating its manifest on first use."""
        with self.lock:
            folder = self.root / "files" / f"samples-{_slug(api_name)}"
            folder.mkdir(parents=True, exist_ok=True)
            manifest_path = folder / "manifest.json"
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"name": api_name, "title": api_name, "endpoints": []}
            names = []
            for index, (name, content) in enumerate(payloads):
                file_name = f"{_slug(method)}-{_slug(path)}-{index}-{Path(name).name}"
                (folder / file_name).write_bytes(content)
                names.append(file_name)
            manifest["endpoints"] = [e for e in manifest["endpoints"] if (e["method"], e["path"]) != (method.upper(), path)]
            manifest["endpoints"].append({"method": method.upper(), "path": path, "samples": names})
            manifest_path.write_text(json.dumps(manifest, indent=2))
            existing = next((f for f in self.files if Path(f.path) == manifest_path), None)
            if existing:
                existing.summary = _summarise(FileRole.DOWNSTREAM, manifest_path)
                self._save_index()
                return existing
            stored = StoredFile(uuid.uuid4().hex[:12], FileRole.DOWNSTREAM, f"{api_name} (samples)", str(manifest_path),
                                _summarise(FileRole.DOWNSTREAM, manifest_path))
            self.files.append(stored)
            self._save_index()
            return stored

    def remove_file(self, file_id: str) -> None:
        with self.lock:
            stored = next((f for f in self.files if f.id == file_id), None)
            if stored is None:
                return
            self.files.remove(stored)
            folder = Path(stored.path).parent
            if folder.is_relative_to(self.root / "files") and not any(Path(f.path).parent == folder for f in self.files):
                shutil.rmtree(folder, ignore_errors=True)
            self._save_index()

    def load_demo(self, samples: Path) -> None:
        with self.lock:
            self.reset()
            self.add_file(FileRole.UPSTREAM, "core-exchange-6.4.yaml", (samples / "upstream/fdx/core-exchange-6.4.yaml").read_bytes())
            self.add_file(FileRole.CATALOG, "error-catalog.yaml", (samples / "upstream/fdx/error-catalog.yaml").read_bytes())
            self.add_file(FileRole.ANSWER_KEY, "answer_key.yaml", (samples / "answer_key.yaml").read_bytes())
            downstream_root = samples / "downstream"
            shutil.copytree(downstream_root / "common", self.root / "files" / "common", dirs_exist_ok=True)
            for api_dir in sorted(p for p in downstream_root.iterdir() if p.is_dir() and p.name != "common"):
                destination = self.root / "files" / api_dir.name
                shutil.copytree(api_dir, destination, dirs_exist_ok=True)
                spec = next(p for p in sorted(destination.iterdir()) if p.stem in ("openapi", "swagger", "manifest"))
                self.files.append(StoredFile(uuid.uuid4().hex[:12], FileRole.DOWNSTREAM, f"{api_dir.name}/{spec.name}", str(spec),
                                             _summarise(FileRole.DOWNSTREAM, spec)))
            self._save_index()

    def reset(self) -> None:
        with self.lock:
            shutil.rmtree(self.root / "files", ignore_errors=True)
            self.files = []
            self.overrides = []
            self.result = None
            save_overrides(self._overrides_path, [])
            self._save_index()

    def start_run(self) -> RunState:
        state = RunState(id=uuid.uuid4().hex[:12])
        self.runs[state.id] = state
        threading.Thread(target=self._run, args=(state,), daemon=True).start()
        return state

    def _run(self, state: RunState) -> None:
        def listen(event: ProgressEvent) -> None:
            state.events.append({"stage": event.stage, "state": event.state.value, "message": event.message,
                                 "counts": dict(event.counts), "elapsed_ms": event.elapsed_ms})

        try:
            upstream = self._single(FileRole.UPSTREAM)
            if upstream is None:
                raise SpecLoadError("workspace", "add an upstream spec first")
            downstreams = [Path(f.path) for f in self.files if f.role == FileRole.DOWNSTREAM]
            if not downstreams:
                raise SpecLoadError("workspace", "add at least one downstream spec or sample API")
            catalog = self._single(FileRole.CATALOG)
            lexicon = Lexicon.load(DEFAULT_LEXICON, *(Path(f.path) for f in self.files if f.role == FileRole.LEXICON))
            pipeline = MappingPipeline(lexicon, self.thresholds, listener=listen, nlp=self.nlp)
            inputs = pipeline.load(Path(upstream.path), downstreams, Path(catalog.path) if catalog else None, tuple(self.overrides))
            result = pipeline.run(inputs)
            with self.lock:
                self.pipeline, self.result = pipeline, result
        except SpecLoadError as error:
            state.error = str(error)
            listen(ProgressEvent("run", StageState.FAILED, str(error)))
        except Exception as error:  # surfaced in the GUI instead of killing the worker thread
            state.error = f"{type(error).__name__}: {error}"
            listen(ProgressEvent("run", StageState.FAILED, state.error))
        finally:
            state.done = True

    def set_override(self, override: Override | None, target_key: str) -> list[str]:
        with self.lock:
            self.overrides = [o for o in self.overrides if o.target_key != target_key]
            if override is not None:
                self.overrides.append(override)
            save_overrides(self._overrides_path, self.overrides)
            if self.result and self.pipeline:
                return self.pipeline.reapply_overrides(self.result, tuple(self.overrides))
            return []

    def grade(self) -> GradeReport | None:
        answer_key = self._single(FileRole.ANSWER_KEY)
        if not (answer_key and self.result):
            return None
        return grade(self.result.run.mappings, load_answer_key(Path(answer_key.path), self.result.run.upstream.name))

    def state(self) -> dict[str, Any]:
        return {
            "files": [asdict(f) for f in self.files],
            "settings": {**asdict(self.thresholds), "nlp": asdict(self.nlp)},
            "overrides": [asdict(o) for o in self.overrides],
            "has_result": self.result is not None,
        }

    def _single(self, role: FileRole) -> StoredFile | None:
        return next((f for f in self.files if f.role == role), None)

    def configure(self, thresholds: Thresholds, nlp: NlpSettings) -> None:
        with self.lock:
            self.thresholds, self.nlp = thresholds, nlp
            self._save_index()

    def _save_index(self) -> None:
        payload = {"files": [asdict(f) for f in self.files], "settings": asdict(self.thresholds), "nlp": asdict(self.nlp)}
        self._index_path.write_text(json.dumps(payload, indent=2, default=str))

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        raw = json.loads(self._index_path.read_text())
        self.files = [StoredFile(f["id"], FileRole(f["role"]), f["name"], f["path"], f.get("summary", {}))
                      for f in raw.get("files", []) if Path(f["path"]).exists()]
        self.thresholds = Thresholds(**raw.get("settings", {}))
        self.nlp = NlpSettings(**raw.get("nlp", {}))


def parse_override(payload: dict[str, Any]) -> Override:
    return Override(
        target_key=str(payload["target_key"]),
        action=OverrideAction(payload["action"]),
        source_key=payload.get("source_key"),
        note=str(payload.get("note", "")),
        author=str(payload.get("author", "")),
    )


def _summarise(role: FileRole, path: Path) -> dict[str, Any]:
    try:
        if role in (FileRole.UPSTREAM, FileRole.DOWNSTREAM):
            spec = load_any(path)
            return {
                "ok": True,
                "title": spec.title,
                "version": spec.version,
                "kind": spec.kind.value,
                "endpoints": len(spec.endpoints),
                "warnings": list(spec.warnings),
            }
        if role == FileRole.CATALOG:
            return {"ok": True, "errors": len(load_error_catalog(path).errors)}
        if role == FileRole.LEXICON:
            Lexicon.load(path)
            return {"ok": True}
        if role == FileRole.ANSWER_KEY:
            return {"ok": True, "expectations": len(load_answer_key(path, "upstream").expectations)}
    except SpecLoadError as error:
        return {"ok": False, "error": error.reason}
    except Exception as error:  # a broken upload is reported, never fatal
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    return {"ok": True}


def _looks_like_spec(path: Path) -> bool:
    try:
        document = load_document(path)
    except SpecLoadError:
        return True
    if not isinstance(document, dict):
        return False
    return any(key in document for key in ("openapi", "swagger", "paths", "endpoints", "components", "definitions"))


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "x"
