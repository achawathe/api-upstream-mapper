"""Plain-dict view of a run, shared by the JSON export, the web API and tests."""

from typing import Any

from api_mapper.evaluation.grader import GradeReport
from api_mapper.models import (
    Candidate,
    EndpointCallPlan,
    ErrorMapping,
    FieldMapping,
    FieldNode,
    MappingRun,
    ProgressEvent,
)
from api_mapper.validation.executor import ExecutionResult


def run_to_dict(run: MappingRun, include_timings: bool = True) -> dict[str, Any]:
    return {
        "upstream": {"name": run.upstream.name, "title": run.upstream.title, "version": run.upstream.version},
        "downstreams": [
            {"name": s.name, "title": s.title, "kind": s.kind.value, "endpoints": [e.key for e in s.endpoints]}
            for s in run.downstreams
        ],
        "summary": run.status_counts(),
        "mappings": [mapping_to_dict(m) for m in run.mappings],
        "errors": [error_to_dict(e) for e in run.error_mappings],
        "call_plans": [plan_to_dict(p) for p in run.call_plans],
        "events": [event_to_dict(e, include_timings) for e in run.events],
        "warnings": list(run.warnings),
    }


def mapping_to_dict(mapping: FieldMapping) -> dict[str, Any]:
    return {
        "target": node_to_dict(mapping.target),
        "status": mapping.status.value,
        "chosen": candidate_to_dict(mapping.chosen) if mapping.chosen else None,
        "alternatives": [candidate_to_dict(c) for c in mapping.alternatives],
        "notes": list(mapping.notes),
    }


def node_to_dict(node: FieldNode) -> dict[str, Any]:
    return {
        "key": node.key,
        "api": node.api,
        "endpoint": node.endpoint,
        "path": node.path,
        "variant": node.variant,
        "condition": node.condition,
        "type": node.type,
        "format": node.format,
        "required": node.required,
        "nullable": node.nullable,
        "enum": list(node.enum),
        "description": node.description,
        "sample_sources": list(node.sample_sources),
        "sample_context": node.sample_context,
        "example": node.example if isinstance(node.example, (str, int, float, bool)) else None,
    }


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "source": node_to_dict(candidate.source),
        "score": candidate.score,
        "vetoed_by": candidate.vetoed_by,
        "transforms": [{"kind": s.kind.value, "description": s.description, "params": s.params} for s in candidate.transforms],
        "evidence": [
            {"signal": e.signal, "score": round(e.score, 4), "weight": e.weight, "effect": e.effect.value, "detail": e.detail}
            for e in candidate.evidence
        ],
    }


def error_to_dict(mapping: ErrorMapping) -> dict[str, Any]:
    d = mapping.downstream
    return {
        "api": d.api,
        "endpoint": d.endpoint,
        "downstream_status": d.http_status,
        "downstream_code": d.code,
        "downstream_message": d.message,
        "upstream_status": mapping.upstream_status,
        "upstream_code": mapping.upstream_code,
        "rule": mapping.rule,
        "confidence": mapping.confidence,
    }


def plan_to_dict(plan: EndpointCallPlan) -> dict[str, Any]:
    return {
        "upstream_endpoint": plan.upstream_endpoint,
        "unresolved_inputs": list(plan.unresolved_inputs),
        "steps": [
            {
                "order": step.order,
                "api": step.api,
                "endpoint": step.endpoint,
                "variants": list(step.variants),
                "supplies_fields": step.supplies_fields,
                "pending_review_fields": step.pending_review_fields,
                "supplies_only_inputs": step.supplies_only_inputs,
                "awaits_review": step.awaits_review,
                "fanout": step.is_fanout,
                "bindings": [
                    {"parameter": b.parameter, "location": b.location, "source": b.source.value, "reference": b.reference, "fanout": b.fanout, "from_step": b.from_step}
                    for b in step.bindings
                ],
            }
            for step in plan.steps
        ],
    }


def event_to_dict(event: ProgressEvent, include_timings: bool = True) -> dict[str, Any]:
    result = {"stage": event.stage, "state": event.state.value, "message": event.message, "counts": dict(event.counts)}
    if include_timings:
        result["elapsed_ms"] = event.elapsed_ms
    return result


def grade_to_dict(report: GradeReport) -> dict[str, Any]:
    return {
        "summary": report.summary(),
        "auto_precision": report.auto_precision,
        "recall": report.recall,
        "auto_recall": report.auto_recall,
        "counts": {outcome.value: count for outcome, count in report.counts.items()},
        "failures": report.failures(),
    }


def execution_to_dict(result: ExecutionResult) -> dict[str, Any]:
    return {
        "upstream_endpoint": result.upstream_endpoint,
        "status": result.status,
        "body": result.body,
        "variants": result.variants,
        "elapsed_ms": result.elapsed_ms,
        "sequential_ms": result.sequential_ms,
        "unreviewed_fields": result.unreviewed_fields,
        "skipped_steps": result.skipped_steps,
        "warnings": result.warnings,
        "issues": [{"path": i.path, "message": i.message} for i in result.issues],
        "calls": [
            {"step": c.step, "api": c.api, "endpoint": c.endpoint, "url": c.url, "status": c.status,
             "started_ms": c.started_ms, "duration_ms": c.duration_ms, "item": c.item}
            for c in result.calls
        ],
    }
