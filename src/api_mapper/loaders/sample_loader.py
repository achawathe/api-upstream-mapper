"""Builds an ApiSpec for a downstream that has no spec, only example payloads.

Manifest format (YAML or JSON):

    name: routing-service
    title: Routing Info Service
    endpoints:
      - method: GET
        path: /payments/routing/{acctNum}
        samples: [routing-1.json, routing-2.json]
        errors:
          "404": [routing-404.json]
"""

import re
from pathlib import Path
from typing import Any

from api_mapper.loaders.document import SpecLoadError, load_document
from api_mapper.loaders.openapi_loader import slugify
from api_mapper.loaders.sample_inference import infer_schema
from api_mapper.models import ApiSpec, Endpoint, ErrorResponse, Parameter, SpecKind

_PATH_PARAM = re.compile(r"{([^}]+)}")


def is_sample_manifest(document: Any) -> bool:
    return isinstance(document, dict) and isinstance(document.get("endpoints"), list) and "paths" not in document


def load_sample_manifest(path: Path) -> ApiSpec:
    manifest = load_document(path)
    if not is_sample_manifest(manifest):
        raise SpecLoadError(str(path), "sample manifest needs an 'endpoints' list")
    endpoints = [_manifest_endpoint(entry, path.parent, str(path)) for entry in manifest["endpoints"]]
    name = str(manifest.get("name") or path.stem)
    return ApiSpec(
        name=slugify(name),
        title=str(manifest.get("title") or name),
        version=str(manifest.get("version") or ""),
        kind=SpecKind.SAMPLES,
        source=str(path),
        description=str(manifest.get("description") or ""),
        tags=tuple(manifest.get("tags") or ()),
        endpoints=tuple(endpoints),
    )


def api_from_payloads(name: str, payloads_by_endpoint: dict[str, list[Any]], title: str = "") -> ApiSpec:
    endpoints = []
    for endpoint_key, payloads in payloads_by_endpoint.items():
        method, _, path = endpoint_key.partition(" ")
        endpoints.append(_sample_endpoint(method or "GET", path or f"/{endpoint_key}", payloads, {}))
    return ApiSpec(
        name=slugify(name),
        title=title or name,
        version="",
        kind=SpecKind.SAMPLES,
        source="uploaded samples",
        endpoints=tuple(endpoints),
    )


def _manifest_endpoint(entry: dict, base_dir: Path, source: str) -> Endpoint:
    if not isinstance(entry, dict) or "path" not in entry:
        raise SpecLoadError(source, "each endpoint needs a 'path'")
    payloads = [load_document(base_dir / sample) for sample in entry.get("samples") or []]
    if not payloads:
        raise SpecLoadError(source, f"endpoint {entry['path']} lists no samples")
    errors = {
        str(status): [load_document(base_dir / file) for file in files]
        for status, files in (entry.get("errors") or {}).items()
    }
    return _sample_endpoint(str(entry.get("method", "GET")).upper(), str(entry["path"]), payloads, errors)


def _sample_endpoint(method: str, path: str, payloads: list[Any], errors: dict[str, list[Any]]) -> Endpoint:
    return Endpoint(
        method=method.upper(),
        path=path,
        operation_id=f"{method.lower()}_{slugify(path)}",
        parameters=tuple(Parameter(name, "path", True, {"type": "string"}) for name in _PATH_PARAM.findall(path)),
        response_schema=infer_schema(payloads),
        response_examples=tuple(payloads),
        error_responses=tuple(
            ErrorResponse(status=status, description="", schema=infer_schema(bodies), examples=tuple(bodies))
            for status, bodies in errors.items()
        ),
    )
