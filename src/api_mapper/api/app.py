"""HTTP API behind the GUI. Every action the GUI offers maps to one route here."""

import asyncio
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api_mapper.api.workspace import FileRole, Workspace, parse_override
from api_mapper.errors.catalog import load_error_catalog
from api_mapper.errors.error_mapper import ErrorMapper
from api_mapper.loaders import SpecLoadError
from api_mapper.matching.assigner import Thresholds
from api_mapper.matching.semantic import NlpSettings
from api_mapper.models.explanation import ExplanationRequest
from api_mapper.reporting.excel_report import write_excel_report
from api_mapper.reporting.explanation_preview import explain_draft
from api_mapper.reporting.serialize import (
    candidate_to_dict,
    execution_to_dict,
    grade_to_dict,
    mapping_to_dict,
    plan_to_dict,
    run_to_dict,
)
from api_mapper.transforms.apply import TransformError, apply_transforms
from api_mapper.transforms.editor import parse_steps
from api_mapper.transforms.enum_normalization import validate_enum_outputs
from api_mapper.validation.checks import check_document
from api_mapper.validation.executor import PlanExecutor
from api_mapper.validation.mock_downstream import FaultPlan, MockDownstreams

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_ROOT = PROJECT_ROOT / "web"
SAMPLES = PROJECT_ROOT / "samples"
CANDIDATE_SEARCH_LIMIT = 25
EVENT_POLL_SECONDS = 0.05

workspace = Workspace(Path(os.environ.get("API_MAPPER_WORKSPACE", PROJECT_ROOT / "projects" / "default")))
app = FastAPI(title="API Mapper")


@app.middleware("http")
async def revalidate_static_files(request: Request, call_next):
    """The GUI is plain files; make browsers re-check them so an upgrade never runs stale code."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
async def log_request_outcomes(request: Request, call_next):
    """Record rejected requests and report/validation actions without bodies or query values."""
    try:
        response = await call_next(request)
    except Exception as error:
        workspace.activity.record("Request failed", "failed", method=request.method, error_type=type(error).__name__)
        raise
    route = request.scope.get("route")
    if request.url.path.startswith("/api/") and (
        response.status_code >= 400 or getattr(route, "name", "") in {"validate", "excel", "json_report"}
    ):
        workspace.activity.record(
            "API request",
            "failed" if response.status_code >= 400 else "success",
            method=request.method,
            route=getattr(route, "path", "unknown"),
            status=response.status_code,
        )
    return response


class NlpBody(BaseModel):
    model_path: str = ""
    min_similarity: float = Field(default=0.80, gt=0, le=1)
    top_k: int = Field(default=10, ge=1, le=100, strict=True)


class SettingsBody(BaseModel):
    auto: float = Field(ge=0, le=1)
    review: float = Field(ge=0, le=1)
    nlp: NlpBody | None = None
    domain: Literal["finance", "general"] | None = None


class EndpointScopeBody(BaseModel):
    endpoints: list[str] = []


class ValidateBody(BaseModel):
    endpoint: str
    params: dict[str, Any] = {}
    variant_hint: str | None = None
    include_review: bool = True
    latency_ms: float = 0
    faults: dict[str, int] = {}


class CategoryBody(BaseModel):
    target_key: str
    category: str = Field(max_length=80)


class PreviewBody(BaseModel):
    target_key: str
    source_key: str
    transforms: list[dict[str, Any]] = []
    sample: Any = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/state")
def state() -> dict[str, Any]:
    return workspace.state()


@app.get("/api/activity")
def activity(limit: int = Query(default=200, ge=1, le=1000), download: bool = False) -> JSONResponse:
    headers = {"Content-Disposition": "attachment; filename=activity-log.json"} if download else {}
    return JSONResponse({"events": workspace.activity.recent(limit)}, headers=headers)


@app.post("/api/files")
async def upload(role: Annotated[FileRole, Form()], files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
    uploads = [(f.filename or "upload", await f.read()) for f in files]
    try:
        stored = workspace.add_files(role, uploads)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"files": [s.__dict__ for s in stored]}


@app.get("/api/files/{file_id}/endpoints")
def sample_endpoints(file_id: str) -> dict[str, Any]:
    try:
        return {"endpoints": workspace.spec_endpoints(file_id)}
    except (ValueError, KeyError, SpecLoadError) as error:
        raise HTTPException(400, str(error)) from error


@app.post("/api/files/{file_id}/model-files")
async def attach_model_files(file_id: str, files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
    uploads = [(f.filename or "models.yaml", await f.read()) for f in files]
    try:
        return {"file": asdict(workspace.add_model_files(file_id, uploads))}
    except (ValueError, KeyError, SpecLoadError) as error:
        raise HTTPException(400, str(error)) from error


@app.post("/api/files/{file_id}/response-samples")
async def attach_response_samples(
    file_id: str,
    endpoint: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
) -> dict[str, Any]:
    uploads = [(f.filename or "response.json", await f.read()) for f in files]
    try:
        attachment = workspace.add_response_samples(file_id, endpoint, uploads)
    except (ValueError, KeyError, SpecLoadError) as error:
        raise HTTPException(400, str(error)) from error
    return {"samples": asdict(attachment)}


@app.delete("/api/response-samples/{sample_id}")
def remove_response_samples(sample_id: str) -> dict[str, Any]:
    workspace.remove_response_samples(sample_id)
    return workspace.state()


@app.post("/api/files/{file_id}/documentation")
async def attach_documentation(
    file_id: str, files: Annotated[list[UploadFile], File()], endpoint: Annotated[str, Form()] = ""
) -> dict[str, Any]:
    uploads = [(f.filename or "pasted.txt", await f.read()) for f in files]
    try:
        return {"document": asdict(workspace.add_documentation(file_id, uploads, endpoint))}
    except (ValueError, KeyError, SpecLoadError) as error:
        raise HTTPException(400, str(error)) from error


@app.delete("/api/documentation/{document_id}")
def remove_documentation(document_id: str) -> dict[str, Any]:
    try:
        workspace.remove_documentation(document_id)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return workspace.state()


@app.post("/api/sample-endpoints")
async def add_sample_endpoint(
    api_name: Annotated[str, Form()],
    path: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    method: Annotated[str, Form()] = "GET",
) -> dict[str, Any]:
    payloads = [(f.filename or "sample.json", await f.read()) for f in files]
    stored = workspace.add_sample_endpoint(api_name, method, path, payloads)
    return {"file": stored.__dict__}


@app.delete("/api/files/{file_id}")
def remove_file(file_id: str) -> dict[str, Any]:
    workspace.remove_file(file_id)
    return workspace.state()


@app.post("/api/demo")
def demo() -> dict[str, Any]:
    workspace.load_demo(SAMPLES)
    return workspace.state()


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    workspace.reset()
    return workspace.state()


@app.put("/api/settings")
def settings(body: SettingsBody) -> dict[str, Any]:
    if body.review > body.auto:
        raise HTTPException(400, "the review threshold cannot be above the automatic threshold")
    nlp = NlpSettings(**body.nlp.model_dump()) if body.nlp else workspace.nlp
    workspace.configure(Thresholds(auto=body.auto, review=body.review), nlp, body.domain)
    return workspace.state()


@app.get("/api/upstream/endpoints")
def upstream_endpoints() -> dict[str, Any]:
    return {"endpoints": workspace.upstream_endpoints()}


@app.put("/api/endpoint-scope")
def endpoint_scope(body: EndpointScopeBody) -> dict[str, Any]:
    try:
        workspace.set_endpoints(body.endpoints)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return workspace.state()


@app.post("/api/runs")
def start_run() -> dict[str, str]:
    return {"run_id": workspace.start_run().id}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    run = workspace.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")

    async def stream():
        sent = 0
        while True:
            while sent < len(run.events):
                yield f"data: {json.dumps(run.events[sent])}\n\n"
                sent += 1
            if run.done:
                yield f"event: done\ndata: {json.dumps({'error': run.error})}\n\n"
                return
            await asyncio.sleep(EVENT_POLL_SECONDS)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/result")
def result() -> dict[str, Any]:
    run = _require_result().run
    payload = run_to_dict(run)
    report = workspace.grade()
    payload["accuracy"] = grade_to_dict(report) if report else None
    payload["overrides"] = [o.__dict__ for o in workspace.overrides]
    return payload


@app.get("/api/candidates")
def candidates(target_key: str, q: str = "") -> dict[str, Any]:
    prepared = _require_result().prepared
    words = [w for w in q.lower().split() if w]
    if words:
        matches = [key for key in prepared.sources if all(w in key.lower() for w in words)]
    elif target_key in prepared.targets:
        matches = [p.node.key for p in prepared.index.candidates_for(prepared.targets[target_key])]
    else:
        matches = []
    scored = [c for c in (prepared.score_pair(target_key, key) for key in matches) if c is not None]
    scored.sort(key=lambda c: (-c.score, c.source.key))
    return {"candidates": [candidate_to_dict(c) for c in scored[:CANDIDATE_SEARCH_LIMIT]], "total": len(matches)}


@app.post("/api/overrides")
def set_override(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        override = parse_override(payload)
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(400, f"invalid override: {error}") from error
    prepared = _require_result().prepared
    if override.target_key not in prepared.targets:
        raise HTTPException(400, "Choose a field from the current mapping run")
    if override.source_key and override.source_key not in prepared.sources:
        raise HTTPException(400, "Choose a source from the current mapping run")
    try:
        validate_enum_outputs(override.transforms, prepared.targets[override.target_key].node)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    warnings = workspace.set_override(override, override.target_key)
    return _after_override(override.target_key, warnings)


@app.put("/api/mapping-category")
def set_category(body: CategoryBody) -> dict[str, Any]:
    try:
        workspace.set_category(body.target_key, body.category)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return _after_override(body.target_key, [])


@app.post("/api/conversion-preview")
def preview_conversion(body: PreviewBody) -> dict[str, Any]:
    prepared = _require_result().prepared
    target = prepared.targets.get(body.target_key)
    source = prepared.sources.get(body.source_key)
    if target is None or source is None:
        raise HTTPException(400, "Choose a target and source from the current run")
    sample = body.sample if "sample" in body.model_fields_set else source.node.example
    if sample is None and "sample" not in body.model_fields_set:
        raise HTTPException(400, "This source has no example. Enter a JSON value to preview.")
    try:
        steps = parse_steps(body.transforms) or ()
        validate_enum_outputs(steps, target.node)
        output = apply_transforms(steps, sample)
        issues = check_document({"value": output}, [replace(target.node, path="value")])
        return {
            "input": sample,
            "output": output,
            "issues": [issue.message for issue in issues],
            "message": "Example only; confirm conversions for all expected values",
        }
    except (ValueError, TypeError, OverflowError, TransformError) as error:
        raise HTTPException(400, str(error)) from error


@app.post("/api/mapping-explanation")
def mapping_explanation(body: ExplanationRequest) -> dict[str, Any]:
    result = _require_result()
    mapping = next((m for m in result.run.mappings if m.target.key == body.target_key), None)
    candidate = result.prepared.score_pair(body.target_key, body.source_key)
    if mapping is None or candidate is None:
        raise HTTPException(400, "Choose a target and source from the current run")
    try:
        return explain_draft(mapping, candidate, body.transforms)
    except (ValueError, TypeError) as error:
        raise HTTPException(400, str(error)) from error


@app.delete("/api/overrides")
def clear_override(target_key: str) -> dict[str, Any]:
    return _after_override(target_key, workspace.set_override(None, target_key))


@app.get("/api/report.xlsx")
def excel() -> FileResponse:
    run = _require_result().run
    path = write_excel_report(run, workspace.root / "output" / "mapping-report.xlsx")
    return FileResponse(path, filename="mapping-report.xlsx")


@app.get("/api/report.json")
def json_report() -> JSONResponse:
    return JSONResponse(
        run_to_dict(_require_result().run), headers={"Content-Disposition": "attachment; filename=mapping-report.json"}
    )


@app.get("/api/validate/options")
def validate_options() -> dict[str, Any]:
    run = _require_result().run
    options = []
    plans = {plan.upstream_endpoint: plan for plan in run.call_plans}
    for endpoint in run.upstream.endpoints:
        plan = plans.get(endpoint.key)
        if plan is None:
            continue
        upstream_names = {p.name for p in endpoint.parameters}
        targets = [m.target for m in run.mappings if m.target.endpoint == endpoint.key and m.target.variant]
        variants = sorted({(t.variant, (t.condition or "").rpartition("= ")[2]) for t in targets})
        options.append(
            {
                "endpoint": endpoint.key,
                "path_params": [p.name for p in endpoint.parameters if p.location == "path"],
                "query_params": [p.name for p in endpoint.parameters if p.location == "query"],
                "context_params": sorted(
                    {
                        b.key if b.parameter in upstream_names else b.parameter
                        for s in plan.steps
                        for b in s.bindings
                        if b.source.value == "unresolved"
                    }
                ),
                "variants": [{"name": v, "value": value} for v, value in variants],
                "steps": len(plan.steps),
            }
        )
    apis = [
        {"name": s.name, "statuses": sorted({r.status for e in s.endpoints for r in e.error_responses})}
        for s in run.downstreams
    ]
    return {"endpoints": options, "apis": apis}


@app.post("/api/validate")
async def validate(body: ValidateBody) -> dict[str, Any]:
    result = _require_result()
    if not any(p.upstream_endpoint == body.endpoint for p in result.run.call_plans):
        raise HTTPException(404, f"unknown upstream endpoint {body.endpoint}")
    lexicon = workspace.pipeline.lexicon
    catalog_file = next((f for f in workspace.files if f.role == FileRole.CATALOG), None)
    resolver = ErrorMapper(load_error_catalog(Path(catalog_file.path)), lexicon).map if catalog_file else None
    mocks = MockDownstreams(
        result.run.downstreams, lexicon, FaultPlan(statuses=body.faults, latency_ms=body.latency_ms)
    )
    executor = PlanExecutor(result.run, mocks, resolver, include_review=body.include_review)
    return execution_to_dict(await executor.execute(body.endpoint, body.params, body.variant_hint))


def _after_override(target_key: str, warnings: list[str]) -> dict[str, Any]:
    run = _require_result().run
    mapping = next((m for m in run.mappings if m.target.key == target_key), None)
    return {
        "mapping": mapping_to_dict(mapping) if mapping else None,
        "summary": run.status_counts(),
        "call_plans": [plan_to_dict(p) for p in run.call_plans],
        "overrides": [o.__dict__ for o in workspace.overrides],
        "warnings": warnings,
    }


def _require_result():
    if workspace.result is None:
        raise HTTPException(409, "run the mapping first")
    return workspace.result


app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
