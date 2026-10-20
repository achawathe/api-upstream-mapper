"""Files, settings, overrides and the latest run for the GUI, stored under one folder on disk."""

import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from api_mapper.api.activity import ActivityLog
from api_mapper.api.document_attachments import (
    DocumentAttachment,
    apply_documents,
    store_documents,
)
from api_mapper.api.model_attachments import attach_models
from api_mapper.api.sample_attachments import (
    SampleAttachment,
    apply_samples,
    store_samples,
)
from api_mapper.api.spec_uploads import save_bundle, spec_entrypoints
from api_mapper.errors.catalog import load_error_catalog
from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import GradeReport, grade
from api_mapper.loaders import SpecLoadError, load_any
from api_mapper.matching.assigner import Thresholds
from api_mapper.matching.semantic import NlpSettings
from api_mapper.models import Override, OverrideAction, ProgressEvent, StageState
from api_mapper.normalize.flattener import flatten_spec
from api_mapper.normalize.lexicon import DEFAULT_LEXICON, Lexicon
from api_mapper.pipeline.orchestrator import MappingPipeline, PipelineResult
from api_mapper.pipeline.overrides import load_overrides, save_overrides
from api_mapper.transforms.editor import parse_steps


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
    model_files: list[str] = field(default_factory=list)


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
        self.activity = ActivityLog(self.root)
        self.files: list[StoredFile] = []
        self.samples: list[SampleAttachment] = []
        self.documents: list[DocumentAttachment] = []
        self.categories: dict[str, str] = {}
        self.thresholds = Thresholds()
        self.nlp = NlpSettings()
        self.domain = "finance"
        self.endpoints: list[str] = []
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
        with self.activity.action("Upload files", role=role, file_count=len(uploads)), self.lock:
            folder = self.root / "files" / uuid.uuid4().hex[:12]
            try:
                paths = save_bundle(folder, uploads)
                registered = (
                    spec_entrypoints(paths, role == FileRole.UPSTREAM)
                    if role in (FileRole.UPSTREAM, FileRole.DOWNSTREAM)
                    else paths
                )
                if role in SINGLE_FILE_ROLES and len(registered) != 1:
                    raise ValueError("this input accepts one file")
                stored = [
                    StoredFile(uuid.uuid4().hex[:12], role, str(p.relative_to(folder)), str(p), _summarise(role, p))
                    for p in registered
                ]
                if role == FileRole.UPSTREAM:
                    stored[0].model_files = sorted(str(p.relative_to(folder)) for p in paths if p not in registered)
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            if role in SINGLE_FILE_ROLES:
                for existing in [f for f in self.files if f.role == role]:
                    self.remove_file(existing.id)
            self.files.extend(stored)
            if role == FileRole.UPSTREAM:
                known = {item["key"] for item in self.upstream_endpoints()}
                self.endpoints = [key for key in self.endpoints if key in known]
            self.result = None
            self._save_index()
            return stored

    def add_model_files(self, file_id: str, uploads: list[tuple[str, bytes]]) -> StoredFile:
        with self.activity.action("Attach upstream model files", file_id=file_id, file_count=len(uploads)), self.lock:
            stored = self._spec_file(file_id)
            if stored.role != FileRole.UPSTREAM:
                raise ValueError("choose the upstream spec for model attachments")
            if any(not run.done for run in self.runs.values()):
                raise ValueError("wait for the current mapping run to finish before attaching model files")
            path, names = attach_models(self.root / "files", Path(stored.path), uploads)
            stored.path, stored.model_files = str(path), names
            stored.summary = _summarise(stored.role, path)
            self.result = None
            self._save_index()
            return stored

    def spec_endpoints(self, file_id: str) -> list[str]:
        stored = self._spec_file(file_id)
        return [e.key for e in load_any(Path(stored.path)).endpoints if e.response_schema is not None]

    def upstream_endpoints(self) -> list[dict[str, Any]]:
        """Upstream endpoints that have response fields, with field counts and whether each is selected."""
        upstream = self._single(FileRole.UPSTREAM)
        if upstream is None:
            return []
        try:
            spec = load_any(Path(upstream.path))
        except SpecLoadError:
            return []
        fields: dict[str, int] = {}
        for node in flatten_spec(spec):
            fields[node.endpoint] = fields.get(node.endpoint, 0) + 1
        return [
            {"key": e.key, "fields": fields[e.key], "selected": e.key in self.endpoints}
            for e in spec.endpoints
            if e.key in fields
        ]

    def set_endpoints(self, endpoints: list[str]) -> None:
        """An empty selection maps every upstream endpoint."""
        with self.activity.action("Select upstream endpoints", endpoint_count=len(endpoints)), self.lock:
            known = {item["key"] for item in self.upstream_endpoints()}
            unknown = [key for key in endpoints if key not in known]
            if unknown:
                raise ValueError(f"not an upstream endpoint with response fields: {', '.join(unknown)}")
            self.endpoints = list(dict.fromkeys(endpoints))
            self._save_index()

    def add_response_samples(self, file_id: str, endpoint: str, uploads: list[tuple[str, bytes]]) -> SampleAttachment:
        with (
            self.activity.action(
                "Attach response examples", file_id=file_id, endpoint=endpoint, sample_count=len(uploads)
            ),
            self.lock,
        ):
            stored = self._spec_file(file_id)
            attachment = store_samples(self.root, file_id, load_any(Path(stored.path)), endpoint, uploads)
            self.samples.append(attachment)
            self.result = None
            self._save_index()
            return attachment

    def remove_response_samples(self, sample_id: str) -> None:
        with self.activity.action("Remove response examples", sample_id=sample_id), self.lock:
            attachment = next((s for s in self.samples if s.id == sample_id), None)
            if attachment is None:
                return
            self.samples.remove(attachment)
            shutil.rmtree(self.root / "response-samples" / attachment.id, ignore_errors=True)
            self.result = None
            self._save_index()

    def _spec_file(self, file_id: str) -> StoredFile:
        stored = next((f for f in self.files if f.id == file_id), None)
        if stored is None or stored.role not in (FileRole.UPSTREAM, FileRole.DOWNSTREAM):
            raise ValueError("choose an uploaded upstream or downstream API")
        return stored

    def add_documentation(
        self, file_id: str, uploads: list[tuple[str, bytes]], endpoint: str = ""
    ) -> DocumentAttachment:
        with self.activity.action("Attach documentation", file_id=file_id, file_count=len(uploads)), self.lock:
            if any(not run.done for run in self.runs.values()):
                raise ValueError("Wait for the current mapping run to finish before changing documentation")
            stored = self._spec_file(file_id)
            attachment = store_documents(self.root, file_id, load_any(Path(stored.path)), uploads, endpoint)
            self.documents.append(attachment)
            self.result = None
            self._save_index()
            return attachment

    def remove_documentation(self, document_id: str) -> None:
        with self.activity.action("Remove documentation", document_id=document_id), self.lock:
            if any(not run.done for run in self.runs.values()):
                raise ValueError("Wait for the current mapping run to finish before changing documentation")
            attachment = next((d for d in self.documents if d.id == document_id), None)
            if attachment:
                self.documents.remove(attachment)
                shutil.rmtree(self.root / "documentation" / attachment.id, ignore_errors=True)
                self.result = None
                self._save_index()

    def add_sample_endpoint(
        self, api_name: str, method: str, path: str, payloads: list[tuple[str, bytes]]
    ) -> StoredFile:
        """Adds captured responses as one endpoint of a spec-less API, creating its manifest on first use."""
        with (
            self.activity.action(
                "Add API without a spec", method=method.upper(), endpoint=path, sample_count=len(payloads)
            ),
            self.lock,
        ):
            folder = self.root / "files" / f"samples-{_slug(api_name)}"
            folder.mkdir(parents=True, exist_ok=True)
            manifest_path = folder / "manifest.json"
            manifest = (
                json.loads(manifest_path.read_text())
                if manifest_path.exists()
                else {"name": api_name, "title": api_name, "endpoints": []}
            )
            names = []
            for index, (name, content) in enumerate(payloads):
                file_name = f"{_slug(method)}-{_slug(path)}-{index}-{Path(name).name}"
                (folder / file_name).write_bytes(content)
                names.append(file_name)
            manifest["endpoints"] = [
                e for e in manifest["endpoints"] if (e["method"], e["path"]) != (method.upper(), path)
            ]
            manifest["endpoints"].append({"method": method.upper(), "path": path, "samples": names})
            manifest_path.write_text(json.dumps(manifest, indent=2))
            existing = next((f for f in self.files if Path(f.path) == manifest_path), None)
            if existing:
                existing.summary = _summarise(FileRole.DOWNSTREAM, manifest_path)
                self._save_index()
                return existing
            stored = StoredFile(
                uuid.uuid4().hex[:12],
                FileRole.DOWNSTREAM,
                f"{api_name} (samples)",
                str(manifest_path),
                _summarise(FileRole.DOWNSTREAM, manifest_path),
            )
            self.files.append(stored)
            self._save_index()
            return stored

    def remove_file(self, file_id: str) -> None:
        with self.activity.action("Remove API file", file_id=file_id), self.lock:
            stored = next((f for f in self.files if f.id == file_id), None)
            if stored is None:
                return
            for attachment in list(self.samples):
                if attachment.file_id == file_id:
                    self.remove_response_samples(attachment.id)
            for attachment in list(self.documents):
                if attachment.file_id == file_id:
                    self.remove_documentation(attachment.id)
            self.files.remove(stored)
            self.result = None
            files_root = self.root / "files"
            if Path(stored.path).is_relative_to(files_root):
                folder = files_root / Path(stored.path).relative_to(files_root).parts[0]
                if not any(Path(f.path).is_relative_to(folder) for f in self.files):
                    shutil.rmtree(folder, ignore_errors=True)
            self._save_index()

    def load_demo(self, samples: Path) -> None:
        with self.activity.action("Load example workspace"), self.lock:
            self.reset()
            self.add_file(
                FileRole.UPSTREAM,
                "core-exchange-6.4.yaml",
                (samples / "upstream/fdx/core-exchange-6.4.yaml").read_bytes(),
            )
            self.add_file(
                FileRole.CATALOG, "error-catalog.yaml", (samples / "upstream/fdx/error-catalog.yaml").read_bytes()
            )
            self.add_file(FileRole.ANSWER_KEY, "answer_key.yaml", (samples / "answer_key.yaml").read_bytes())
            downstream_root = samples / "downstream"
            shutil.copytree(downstream_root / "common", self.root / "files" / "common", dirs_exist_ok=True)
            for api_dir in sorted(p for p in downstream_root.iterdir() if p.is_dir() and p.name != "common"):
                destination = self.root / "files" / api_dir.name
                shutil.copytree(api_dir, destination, dirs_exist_ok=True)
                spec = next(p for p in sorted(destination.iterdir()) if p.stem in ("openapi", "swagger", "manifest"))
                self.files.append(
                    StoredFile(
                        uuid.uuid4().hex[:12],
                        FileRole.DOWNSTREAM,
                        f"{api_dir.name}/{spec.name}",
                        str(spec),
                        _summarise(FileRole.DOWNSTREAM, spec),
                    )
                )
            self._save_index()

    def reset(self) -> None:
        with self.activity.action("Clear workspace"), self.lock:
            shutil.rmtree(self.root / "files", ignore_errors=True)
            shutil.rmtree(self.root / "response-samples", ignore_errors=True)
            shutil.rmtree(self.root / "documentation", ignore_errors=True)
            self.documents = []
            self.samples = []
            self.files = []
            self.overrides = []
            self.categories = {}
            self.endpoints = []
            self.result = None
            save_overrides(self._overrides_path, [])
            self._save_index()

    def start_run(self) -> RunState:
        state = RunState(id=uuid.uuid4().hex[:12])
        self.runs[state.id] = state
        threading.Thread(target=self._run, args=(state,), daemon=True).start()
        return state

    def _run(self, state: RunState) -> None:
        self.activity.record("Mapping run", "started", run_id=state.id, local_nlp=bool(self.nlp.model_path))
        failure_type = None

        def listen(event: ProgressEvent) -> None:
            state.events.append(
                {
                    "stage": event.stage,
                    "state": event.state.value,
                    "message": event.message,
                    "counts": dict(event.counts),
                    "elapsed_ms": event.elapsed_ms,
                }
            )
            self.activity.record(
                "Mapping stage",
                event.state.value,
                run_id=state.id,
                stage=event.stage,
                counts=dict(event.counts),
                elapsed_ms=event.elapsed_ms,
            )

        try:
            upstream = self._single(FileRole.UPSTREAM)
            if upstream is None:
                raise SpecLoadError("workspace", "add an upstream spec first")
            downstreams = [Path(f.path) for f in self.files if f.role == FileRole.DOWNSTREAM]
            if not downstreams:
                raise SpecLoadError("workspace", "add at least one downstream spec or sample API")
            catalog = self._single(FileRole.CATALOG)
            base_lexicon = DEFAULT_LEXICON.with_name(f"{self.domain}.yaml")
            lexicon = Lexicon.load(base_lexicon, *(Path(f.path) for f in self.files if f.role == FileRole.LEXICON))
            pipeline = MappingPipeline(lexicon, self.thresholds, listener=listen, nlp=self.nlp)
            inputs = pipeline.load(
                Path(upstream.path), downstreams, Path(catalog.path) if catalog else None, tuple(self.overrides)
            )
            enriched = {
                f.id: apply_documents(apply_samples(spec, self.samples, f.id), self.documents, f.id)
                for f in self.files
                if f.role in (FileRole.UPSTREAM, FileRole.DOWNSTREAM)
                for spec in (inputs.upstream, *inputs.downstreams)
                if spec.source == f.path
            }
            inputs = replace(
                inputs,
                upstream=enriched[upstream.id],
                downstreams=tuple(
                    enriched[f.id] for f in self.files if f.role == FileRole.DOWNSTREAM and f.id in enriched
                ),
                endpoints=tuple(self.endpoints),
            )
            result = pipeline.run(inputs)
            self._apply_categories(result)
            with self.lock:
                self.pipeline, self.result = pipeline, result
        except SpecLoadError as error:
            failure_type = type(error).__name__
            state.error = str(error)
            listen(ProgressEvent("run", StageState.FAILED, str(error)))
        except Exception as error:  # noqa: BLE001 - report worker failures to the GUI
            failure_type = type(error).__name__
            state.error = f"{type(error).__name__}: {error}"
            listen(ProgressEvent("run", StageState.FAILED, state.error))
        finally:
            self.activity.record(
                "Mapping run", "failed" if state.error else "success", run_id=state.id, error_type=failure_type
            )
            state.done = True

    def set_override(self, override: Override | None, target_key: str) -> list[str]:
        with (
            self.activity.action(
                "Change mapping decision",
                target=target_key,
                source=override.source_key if override else None,
                decision=override.action.value if override else "clear",
            ),
            self.lock,
        ):
            self.overrides = [o for o in self.overrides if o.target_key != target_key]
            if override is not None:
                self.overrides.append(override)
            save_overrides(self._overrides_path, self.overrides)
            if self.result and self.pipeline:
                warnings = self.pipeline.reapply_overrides(self.result, tuple(self.overrides))
                self._apply_categories(self.result)
                return warnings
            return []

    def set_category(self, target_key: str, category: str) -> None:
        with self.activity.action("Categorize mapping", target=target_key), self.lock:
            category = category.strip()
            if len(category) > 80:
                raise ValueError("Category names can contain at most 80 characters")
            if not self.result or target_key not in self.result.prepared.targets:
                raise ValueError("Choose a field from the current mapping run")
            if category:
                self.categories[target_key] = category
            else:
                self.categories.pop(target_key, None)
            self._apply_categories(self.result)
            self._save_index()

    def _apply_categories(self, result: PipelineResult) -> None:
        for mapping in result.run.mappings:
            mapping.category = self.categories.get(mapping.target.key, "")

    def grade(self) -> GradeReport | None:
        answer_key = self._single(FileRole.ANSWER_KEY)
        if not (answer_key and self.result):
            return None
        return grade(self.result.run.mappings, load_answer_key(Path(answer_key.path), self.result.run.upstream.name))

    def state(self) -> dict[str, Any]:
        return {
            "files": [asdict(f) for f in self.files],
            "settings": {
                **asdict(self.thresholds),
                "nlp": asdict(self.nlp),
                "domain": self.domain,
                "endpoints": list(self.endpoints),
            },
            "overrides": [asdict(o) for o in self.overrides],
            "has_result": self.result is not None,
            "response_samples": [asdict(s) for s in self.samples],
            "documentation": [asdict(d) for d in self.documents],
        }

    def _single(self, role: FileRole) -> StoredFile | None:
        return next((f for f in self.files if f.role == role), None)

    def configure(self, thresholds: Thresholds, nlp: NlpSettings, domain: str | None = None) -> None:
        if domain is not None and domain not in {"finance", "general"}:
            raise ValueError("Choose general or finance vocabulary")
        with (
            self.activity.action(
                "Change settings", automatic=thresholds.auto, review=thresholds.review, local_nlp=bool(nlp.model_path)
            ),
            self.lock,
        ):
            self.thresholds, self.nlp = thresholds, nlp
            self.domain = domain or self.domain
            self._save_index()

    def _save_index(self) -> None:
        payload = {
            "files": [asdict(f) for f in self.files],
            "settings": asdict(self.thresholds),
            "nlp": asdict(self.nlp),
            "response_samples": [asdict(s) for s in self.samples],
        }
        payload["documentation"] = [asdict(d) for d in self.documents]
        payload["domain"] = self.domain
        payload["categories"] = self.categories
        payload["endpoints"] = self.endpoints
        self._index_path.write_text(json.dumps(payload, indent=2, default=str))

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        raw = json.loads(self._index_path.read_text())
        self.files = [
            StoredFile(
                f["id"], FileRole(f["role"]), f["name"], f["path"], f.get("summary", {}), f.get("model_files", [])
            )
            for f in raw.get("files", [])
            if Path(f["path"]).exists()
        ]
        self.samples = [
            SampleAttachment(**s)
            for s in raw.get("response_samples", [])
            if any(f.id == s["file_id"] for f in self.files)
        ]
        self.documents = [
            DocumentAttachment(**d)
            for d in raw.get("documentation", [])
            if any(f.id == d["file_id"] for f in self.files) and Path(d["path"]).exists()
        ]
        self.thresholds = Thresholds(**raw.get("settings", {}))
        self.nlp = NlpSettings(**raw.get("nlp", {}))
        self.domain = (
            raw.get("domain", "finance") if raw.get("domain", "finance") in {"finance", "general"} else "finance"
        )
        self.categories = raw.get("categories", {})
        self.endpoints = [str(key) for key in raw.get("endpoints", [])]


def parse_override(payload: dict[str, Any]) -> Override:
    return Override(
        target_key=str(payload["target_key"]),
        action=OverrideAction(payload["action"]),
        source_key=payload.get("source_key"),
        note=str(payload.get("note", "")),
        author=str(payload.get("author", "")),
        transforms=parse_steps(payload.get("transforms")),
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
    except Exception as error:  # noqa: BLE001 - report broken uploads without aborting the batch
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    return {"ok": True}


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "x"
