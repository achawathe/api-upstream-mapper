"""In-process fake downstream servers built from the specs themselves.

Responses come from the spec's own examples when it has them, otherwise they are
synthesised from the schema. Values are seeded by the request, so the same call
always returns the same body, and path parameters are echoed into matching fields
(asking for account ACC-1 returns an account whose id is ACC-1).
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from api_mapper.loaders.ref_resolver import CYCLE_KEY
from api_mapper.models import ApiSpec, Endpoint
from api_mapper.normalize.flattener import merge_all_of, schema_type
from api_mapper.normalize.lexicon import Lexicon

ARRAY_LENGTH = 2
MAX_DEPTH = 12


@dataclass
class FaultPlan:
    """Which downstream calls should fail, and how slow every call is."""

    statuses: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0

    def status_for(self, api: str, endpoint_key: str) -> int | None:
        return self.statuses.get(f"{api} {endpoint_key}") or self.statuses.get(api)


class MockDownstreams:
    def __init__(self, specs: tuple[ApiSpec, ...], lexicon: Lexicon, faults: FaultPlan | None = None):
        self.lexicon = lexicon
        self.faults = faults or FaultPlan()
        self._routes: dict[str, list[tuple[re.Pattern, list[str], Endpoint]]] = {}
        for spec in specs:
            for endpoint in spec.endpoints:
                pattern, names = _route_pattern(endpoint.path)
                self._routes.setdefault(spec.name, []).append((pattern, names, endpoint))

    @staticmethod
    def base_url(api: str) -> str:
        return f"http://{api}.mock"

    def transport(self) -> httpx.AsyncBaseTransport:
        return httpx.MockTransport(self._handle)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        api = request.url.host.removesuffix(".mock")
        route = self._match(api, request.method, request.url.path)
        if self.faults.latency_ms:
            await asyncio.sleep(self.faults.latency_ms / 1000)
        if route is None:
            return httpx.Response(404, json={"error": f"no mock route for {request.method} {request.url.path}"})
        endpoint, params = route
        fault = self.faults.status_for(api, endpoint.key)
        if fault:
            return httpx.Response(fault, json=_error_body(endpoint, fault))
        seed = f"{api}|{endpoint.key}|{json.dumps(params, sort_keys=True)}"
        body = self._body(endpoint, params, seed)
        return httpx.Response(200, json=body)

    def _match(self, api: str, method: str, path: str) -> tuple[Endpoint, dict[str, str]] | None:
        for pattern, names, endpoint in self._routes.get(api, []):
            match = pattern.fullmatch(path)
            if match and endpoint.method == method:
                return endpoint, dict(zip(names, match.groups(), strict=True))
        return None

    def _body(self, endpoint: Endpoint, params: dict[str, str], seed: str) -> Any:
        if endpoint.response_examples:
            body = json.loads(json.dumps(endpoint.response_examples[0]))
        else:
            body = _Synthesizer(seed).value(endpoint.response_schema or {}, "")
        return _echo_params(body, params, self.lexicon)


def _route_pattern(path: str) -> tuple[re.Pattern, list[str]]:
    names = re.findall(r"{([^}]+)}", path)
    regex = re.sub(r"{[^}]+}", "([^/]+)", re.escape(path).replace(r"\{", "{").replace(r"\}", "}"))
    return re.compile(regex), names


def _error_body(endpoint: Endpoint, status: int) -> Any:
    for response in endpoint.error_responses:
        if response.status == str(status) and response.examples:
            return response.examples[0]
    return {"error": f"injected failure {status}"}


def _echo_params(body: Any, params: dict[str, str], lexicon: Lexicon) -> Any:
    """Put requested ids back into the record so later calls and assembly see consistent data."""
    wanted = {_name_concepts(name, "", lexicon): value for name, value in params.items()}

    def visit(node: Any, parent: str, depth: int) -> None:
        if not isinstance(node, dict) or depth > 2:
            return
        for key, child in node.items():
            if isinstance(child, (dict, list)):
                visit(child, key, depth + 1)
            elif _name_concepts(key, parent, lexicon) in wanted:
                node[key] = wanted[_name_concepts(key, parent, lexicon)]

    visit(body, "", 0)
    return body


def _name_concepts(name: str, parent: str, lexicon: Lexicon) -> frozenset[str]:
    concepts = list(lexicon.concepts(name))
    if lexicon.is_generic(concepts) and parent:
        concepts = [*lexicon.concepts(parent), *concepts]
    without_families = [c for c in concepts if c not in lexicon.families]
    return frozenset(without_families or concepts)


class _Synthesizer:
    def __init__(self, seed: str):
        self.seed = seed

    def value(self, schema: dict[str, Any], path: str, depth: int = 0) -> Any:
        if depth > MAX_DEPTH or CYCLE_KEY in schema:
            return None
        schema = merge_all_of(schema)
        branches = schema.get("oneOf") or schema.get("anyOf")
        if branches:
            return self.value(branches[self._pick(path, len(branches))], path, depth + 1)
        if "example" in schema:
            return schema["example"]
        kind, _ = schema_type(schema)
        if schema.get("enum"):
            values = [v for v in schema["enum"] if v is not None]
            return values[self._pick(path, len(values))] if values else None
        if kind == "object":
            return {name: self.value(prop, f"{path}.{name}", depth + 1) for name, prop in (schema.get("properties") or {}).items()}
        if kind == "array":
            return [self.value(schema.get("items") or {}, f"{path}[{i}]", depth + 1) for i in range(ARRAY_LENGTH)]
        return self._scalar(kind, schema, path)

    def _scalar(self, kind: str, schema: dict[str, Any], path: str) -> Any:
        number = self._pick(path, 100_000)
        leaf = path.rsplit(".", 1)[-1].split("[")[0].lower()
        description = str(schema.get("description") or "").lower()
        if kind == "integer":
            return 1_760_000_000_000 + number * 1000 if ("epoch" in description or leaf.endswith("ts")) else number % 1000
        if kind == "number":
            return round(number / 100, 2)
        if kind == "boolean":
            return number % 2 == 0
        format_ = schema.get("format")
        if format_ == "date":
            return f"2026-{1 + number % 12:02d}-{1 + number % 28:02d}"
        if format_ == "date-time":
            return f"2026-{1 + number % 12:02d}-{1 + number % 28:02d}T10:30:00.000Z"
        if format_ == "email":
            return f"user{number % 100}@example.com"
        if "yyyymmdd" in description or schema.get("pattern") == r"^\d{8}$":
            return f"2026{1 + number % 12:02d}{1 + number % 28:02d}"
        return f"{leaf or 'value'}-{number:05d}"

    def _pick(self, path: str, size: int) -> int:
        digest = hashlib.sha256(f"{self.seed}|{path}".encode()).digest()
        return int.from_bytes(digest[:4], "big") % max(size, 1)
