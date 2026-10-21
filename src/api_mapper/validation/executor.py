"""Runs a call plan against (mock) downstreams and assembles the upstream response.

Calls run in waves: every call whose inputs are known runs concurrently. Calls that
serve only some variants (the card API only for line-of-credit accounts) wait until
broader calls have shown which variant the record is, so they are skipped when not needed.
A failed call aborts the request only if it supplies a required field; otherwise the
response is returned without its fields and the failure is reported.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any

import httpx

from api_mapper.errors.catalog import error_code_and_message
from api_mapper.models import (
    BindingSource,
    CallStep,
    DownstreamError,
    EndpointCallPlan,
    ErrorMapping,
    FieldMapping,
    FieldNode,
    MappingRun,
    MappingStatus,
)
from api_mapper.transforms.apply import TransformError, apply_transforms
from api_mapper.validation.assembler import (
    AssemblyNotes,
    Broadcast,
    MapSelectionError,
    align,
    extract,
    transform_nested,
    write,
)
from api_mapper.validation.checks import Issue, check_document
from api_mapper.validation.mock_downstream import MockDownstreams
from api_mapper.validation.request_inputs import RequestInputError, request_parts

ErrorResolver = Callable[[DownstreamError], ErrorMapping]
_ACCEPTED = (MappingStatus.AUTO, MappingStatus.MANUAL)
CANDIDATE_FLOOR = 0.5


@dataclass
class CallRecord:
    step: int
    api: str
    endpoint: str
    url: str
    status: int
    started_ms: float
    duration_ms: float
    item: int | None = None


@dataclass
class ExecutionResult:
    upstream_endpoint: str
    status: int
    body: Any
    calls: list[CallRecord] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    unreviewed_fields: int = 0

    @property
    def sequential_ms(self) -> float:
        return round(sum(call.duration_ms for call in self.calls), 1)


class PlanExecutor:
    def __init__(
        self,
        run: MappingRun,
        mocks: MockDownstreams,
        resolve_error: ErrorResolver | None = None,
        include_review: bool = True,
        max_concurrency: int = 16,
    ):
        self.run = run
        self.mocks = mocks
        self.resolve_error = resolve_error
        self.include_review = include_review
        self.max_concurrency = max_concurrency
        self.endpoints = {(s.name, e.key): e for s in run.downstreams for e in s.endpoints}

    async def execute(
        self, upstream_endpoint: str, params: dict[str, Any], variant_hint: str | None = None
    ) -> ExecutionResult:
        started = perf_counter()
        plan = next(p for p in self.run.call_plans if p.upstream_endpoint == upstream_endpoint)
        mappings = [m for m in self.run.mappings if m.target.endpoint == upstream_endpoint and self._usable(m)]
        derived = [
            m for m in self.run.mappings if m.target.endpoint == upstream_endpoint and m.status is MappingStatus.DERIVED
        ]
        targets = [m.target for m in self.run.mappings if m.target.endpoint == upstream_endpoint]
        result = ExecutionResult(upstream_endpoint, 200, None)
        result.unreviewed_fields = sum(m.status is MappingStatus.REVIEW for m in mappings)

        variants = _variants_of(targets, variant_hint)
        per_item = _variants_live_in_items(targets)
        responses: dict[int, Any] = {}
        selections = _map_selections(plan, params)
        async with httpx.AsyncClient(transport=self.mocks.transport(), timeout=30) as client:
            needed = self._needed_steps(plan, mappings, variants)
            pending = [s for s in plan.steps if s.order in needed]
            while pending:
                ready = [s for s in pending if self._inputs_ready(s, responses) and _relevant(s, variants)]
                broad = [s for s in ready if not s.variants or set(s.variants) >= variants]
                wave = broad or ready
                if not wave:
                    break
                outcomes = await asyncio.gather(
                    *(self._call(client, step, params, responses, selections, started, result) for step in wave)
                )
                for step, outcome in zip(wave, outcomes, strict=True):
                    if isinstance(outcome, _Failure):
                        error = self._failure_response(plan, step, outcome, mappings, variants)
                        if error is not None:
                            result.status, result.body = error
                            result.elapsed_ms = _ms(started)
                            return result
                        result.warnings.append(
                            f"step {step.order} {step.api} failed ({outcome.status}); its fields are left out"
                        )
                        continue
                    responses[step.order] = outcome
                pending = [s for s in pending if s not in wave]
                if not per_item and len(variants) > 1:
                    variants = self._narrow(variants, plan, responses, selections)
                needed = self._needed_steps(plan, mappings, variants)
                pending = [s for s in pending if s.order in needed]
            called = {c.step for c in result.calls}
            result.skipped_steps = [f"{s.order}. {s.api} {s.endpoint}" for s in plan.steps if s.order not in called]

        result.body, result.variants, issues = self._assemble(
            plan, mappings, derived, targets, responses, variants, per_item, selections
        )
        result.issues = issues
        result.elapsed_ms = _ms(started)
        return result

    def _usable(self, mapping: FieldMapping) -> bool:
        if mapping.chosen is None:
            return False
        return mapping.status in _ACCEPTED or (self.include_review and mapping.status is MappingStatus.REVIEW)

    def _inputs_ready(self, step: CallStep, responses: dict[int, Any]) -> bool:
        return all(b.from_step is None or b.from_step in responses for b in step.bindings)

    async def _call(self, client, step: CallStep, params, responses, selections, started, result) -> Any:
        endpoint = self.endpoints[(step.api, step.endpoint)]
        fixed: dict[str, Any] = {}
        fanout_values: list[str] = []
        fanout_name = None
        for binding in step.bindings:
            if binding.source is BindingSource.UPSTREAM_REQUEST:
                if binding.reference in params:
                    fixed[binding.key] = params[binding.reference]
            elif binding.source is BindingSource.PRIOR_STEP:
                try:
                    values = _flatten(
                        _extract_all(
                            responses[binding.from_step],
                            binding.reference.split(" -> ", 1)[1],
                            selections.get(binding.from_step),
                        )
                    )
                except MapSelectionError as error:
                    result.warnings.append(f"step {step.order}: {error}")
                    return _Failure(422, {"error": str(error)})
                if binding.fanout:
                    fanout_name, fanout_values = binding.key, [str(v) for v in values if v is not None]
                elif values:
                    fixed[binding.key] = str(values[0])
            elif binding.key in params:
                fixed[binding.key] = params[binding.key]
            elif binding.parameter in params:
                fixed[binding.key] = params[binding.parameter]

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def one(values: dict[str, Any], item: int | None):
            async with semaphore:
                return await self._request(client, step, endpoint, values, item, started, result)

        if fanout_name is None:
            return await one(fixed, None)
        bodies = await asyncio.gather(*(one({**fixed, fanout_name: v}, i) for i, v in enumerate(fanout_values)))
        failure = next((b for b in bodies if isinstance(b, _Failure)), None)
        return failure or _FanOut(list(bodies))

    async def _request(self, client, step, endpoint, values, item, started, result) -> Any:
        try:
            request = request_parts(endpoint, values)
        except RequestInputError as error:
            result.warnings.append(f"step {step.order}: {error}")
            return _Failure(422, {"error": str(error)})
        url = f"{self.mocks.base_url(step.api)}{request.path}"
        call_started = perf_counter()
        response = await client.request(endpoint.method, url, params=request.query, json=request.body)
        result.calls.append(
            CallRecord(
                step.order,
                step.api,
                step.endpoint,
                str(response.url),
                response.status_code,
                round((call_started - started) * 1000, 1),
                _ms(call_started),
                item,
            )
        )
        body = response.json() if response.content else None
        if response.status_code >= 400:
            return _Failure(response.status_code, body)
        return body

    def _failure_response(
        self, plan, step: CallStep, failure: "_Failure", mappings, variants
    ) -> tuple[int, Any] | None:
        if not self._is_critical(plan, step, mappings, variants):
            return None
        code, message = error_code_and_message(failure.body) if isinstance(failure.body, dict) else (None, "")
        downstream = DownstreamError(step.api, step.endpoint, str(failure.status), code, message)
        mapping = self._lookup_error(downstream)
        body = {
            "code": mapping.upstream_code,
            "message": message or mapping.rule,
            "debugMessage": f"{step.api} returned {failure.status}",
        }
        return int(mapping.upstream_status), body

    def _is_critical(
        self, plan: EndpointCallPlan, step: CallStep, mappings: list[FieldMapping], variants: set[str]
    ) -> bool:
        """A call matters if it supplies a required field, or feeds a call that does."""
        dependants = [s for s in plan.steps if any(b.from_step == step.order for b in s.bindings)]
        if any(self._is_critical(plan, d, mappings, variants) for d in dependants):
            return True
        return any(
            m.target.required
            and m.chosen.source.api == step.api
            and m.chosen.source.endpoint == step.endpoint
            and (not m.target.variant or m.target.variant in variants)
            for m in mappings
        )

    def _lookup_error(self, error: DownstreamError) -> ErrorMapping:
        for known in self.run.error_mappings:
            d = known.downstream
            if (d.api, d.endpoint, d.http_status, d.code) == (error.api, error.endpoint, error.http_status, error.code):
                return known
        if self.resolve_error:
            return self.resolve_error(error)
        status = (
            "503"
            if error.http_status in ("502", "503", "504")
            else ("500" if error.http_status.startswith("5") else error.http_status)
        )
        return ErrorMapping(error, status, None, "status passthrough", 0.5)

    def _narrow(self, variants: set[str], plan: EndpointCallPlan, responses: dict[int, Any], selections) -> set[str]:
        """Drops variants the data already fetched contradicts.

        For each enum field of a variant, every candidate source already fetched is tried,
        not just the chosen one: the core record's type 'DDA' rules out the loan variant even
        though the loan variant takes its type from the lending API.
        """
        done = {(s.api, s.endpoint): s.order for s in plan.steps if s.order in responses}
        surviving = set()
        for variant in variants:
            enum_mappings = [
                m
                for m in self.run.mappings
                if m.target.endpoint == plan.upstream_endpoint and m.target.variant == variant and m.target.enum
            ]
            if not any(self._contradicted(m, done, responses, selections) for m in enum_mappings):
                surviving.add(variant)
        return surviving or variants

    def _contradicted(self, mapping: FieldMapping, done: dict, responses: dict[int, Any], selections) -> bool:
        tried = False
        for candidate in (mapping.chosen, *mapping.alternatives):
            if candidate is None or candidate.vetoed_by or candidate.score < CANDIDATE_FLOOR:
                continue
            order = done.get((candidate.source.api, candidate.source.endpoint))
            if order is None or isinstance(responses[order], _FanOut):
                continue
            try:
                value = extract(responses[order], candidate.source.path, selections.get(order))
            except MapSelectionError:
                continue
            values = [v for v in _flatten(value) if v is not None]
            if not values:
                continue
            tried = True
            try:
                converted = [apply_transforms(candidate.transforms, v) for v in values]
            except (TransformError, ValueError, TypeError):
                continue
            if all(str(v) in mapping.target.enum for v in converted):
                return False
        return tried

    def _needed_steps(self, plan: EndpointCallPlan, mappings: list[FieldMapping], variants: set[str]) -> set[int]:
        sources = {
            (m.chosen.source.api, m.chosen.source.endpoint)
            for m in mappings
            if not m.target.variant or m.target.variant in variants
        }
        needed = {s.order for s in plan.steps if (s.api, s.endpoint) in sources}
        changed = True
        while changed:
            suppliers = {b.from_step for s in plan.steps if s.order in needed for b in s.bindings if b.from_step}
            changed = not suppliers <= needed
            needed |= suppliers
        return needed

    def _assemble(self, plan, mappings, derived, targets, responses, variants, per_item, selections):
        if not variants:
            notes = AssemblyNotes()
            document = self._document_for(None, plan, mappings, derived, responses, notes, selections)
            return document, [], [Issue("", n) for n in notes.issues] + check_document(document, targets)

        built = {}
        for variant in sorted(variants):
            notes = AssemblyNotes()
            document = self._document_for(variant, plan, mappings, derived, responses, notes, selections)
            fields = [t for t in targets if t.variant in (None, variant)]
            built[variant] = (document, notes, fields)

        if not per_item:
            variant = min(
                built,
                key=lambda v: (
                    len(check_document(built[v][0], built[v][2])) + len(built[v][1].issues),
                    -_filled(built[v][0]),
                    v,
                ),
            )
            document, notes, fields = built[variant]
            return document, [variant], [Issue("", n) for n in notes.issues] + check_document(document, fields)

        return self._merge_items(built, targets)

    def _merge_items(self, built, targets):
        """Routes each array item to the variant it fits best: fewest schema issues, then most fields filled."""
        collection = next(t.path.split("[]")[0] for t in targets if t.variant)
        common = next(iter(built.values()))[0]
        merged = {k: v for k, v in common.items() if k != collection}
        length = max(len(doc.get(collection) or []) for doc, _, _ in built.values())
        items, chosen, issues = [], [], []
        for index in range(length):
            _, _, variant, item, item_fields = min(self._item_quality(built, v, collection, index) for v in built)
            items.append(item)
            chosen.append(variant)
            issues.extend(
                Issue(f"{collection}[{index}].{i.path}", i.message) for i in check_document(item or {}, item_fields)
            )
        merged[collection] = items
        return merged, chosen, issues

    @staticmethod
    def _item_quality(built, variant: str, collection: str, index: int):
        document, _, fields = built[variant]
        item_fields = [_relative(f, collection) for f in fields if f.path.startswith(f"{collection}[]")]
        items = document.get(collection) or []
        item = items[index] if index < len(items) else None
        return len(check_document(item or {}, item_fields)), -_filled(item), variant, item, item_fields

    def _document_for(self, variant, plan, mappings, derived, responses, notes, selections) -> dict:
        document: dict = {}
        step_by_source = {(s.api, s.endpoint): s for s in plan.steps}
        available = set(responses)
        broadcasts = []
        for mapping in (m for m in mappings if m.target.variant in (None, variant)):
            step = step_by_source.get((mapping.chosen.source.api, mapping.chosen.source.endpoint))
            if step is None or step.order not in available:
                continue
            raw = responses[step.order]
            depth = mapping.chosen.source.array_depth + (1 if isinstance(raw, _FanOut) else 0)
            try:
                value = _extract_all(raw, mapping.chosen.source.path, selections.get(step.order))
            except MapSelectionError as error:
                notes.issues.append(f"{mapping.target.path}: {error}")
                continue
            value = transform_nested(align(value, depth, mapping.target.array_depth), mapping, notes)
            if isinstance(value, Broadcast):
                broadcasts.append((mapping.target.path, value))
            else:
                write(document, mapping.target.path, value)
        for path, value in broadcasts:
            write(document, path, value)
        for mapping in derived:
            if mapping.target.variant == variant:
                write(document, mapping.target.path, _constant_shape(document, mapping.target))
        return document


class _Failure:
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body


class _FanOut:
    def __init__(self, bodies: list[Any]):
        self.bodies = bodies


def _variants_of(targets: list[FieldNode], hint: str | None) -> set[str]:
    variants = {t.variant for t in targets if t.variant}
    if not hint:
        return variants
    chosen = {
        t.variant for t in targets if t.variant and (t.variant == hint or (t.condition or "").endswith(f"= {hint}"))
    }
    return chosen or variants


def _variants_live_in_items(targets: list[FieldNode]) -> bool:
    """True when the variants describe array items (`transactions[]`), not the whole response."""
    roots = {t.path.split(".")[0] for t in targets if t.variant}
    return len(roots) == 1 and next(iter(roots)).endswith("[]")


def _relevant(step: CallStep, variants: set[str]) -> bool:
    return not step.variants or not variants or bool(set(step.variants) & variants)


def _constant_shape(document: dict, target: FieldNode) -> Any:
    value = target.enum[0]
    if target.array_depth == 0:
        return value
    collection = target.path.split("[]")[0]
    return [value] * len(document.get(collection) or [None])


def _relative(field: FieldNode, collection: str) -> FieldNode:
    return replace(field, path=field.path.removeprefix(f"{collection}[]."), array_depth=field.array_depth - 1)


def _filled(node: Any) -> int:
    if isinstance(node, dict):
        return sum(_filled(v) for v in node.values())
    if isinstance(node, list):
        return sum(_filled(v) for v in node)
    return 0 if node is None else 1


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for child in value for item in _flatten(child)]
    return [value]


def _map_selections(plan: EndpointCallPlan, params: dict[str, Any]) -> dict[int, dict[str, str]]:
    selections = {}
    for step in plan.steps:
        keys = {}
        for binding in step.bindings:
            if binding.location != "map key":
                continue
            if binding.source is BindingSource.UPSTREAM_REQUEST:
                value = params.get(binding.reference)
            else:
                value = params.get(binding.key, params.get(binding.parameter))
            if value is not None:
                keys[binding.parameter] = str(value)
        selections[step.order] = keys
    return selections


def _extract_all(raw: Any, path: str, map_keys: dict[str, str] | None = None) -> Any:
    if isinstance(raw, _FanOut):
        return [extract(body, path, map_keys) for body in raw.bodies]
    return extract(raw, path, map_keys)


def _ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 1)
