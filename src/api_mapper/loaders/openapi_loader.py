"""Builds an ApiSpec from Swagger 2.0, OpenAPI 3.x, or a schema-only fragment."""

import re
from pathlib import Path
from typing import Any

from api_mapper.loaders.document import SpecLoadError, load_document
from api_mapper.loaders.ref_resolver import SCHEMA_NAME_KEY, RefResolver
from api_mapper.loaders.request_body import body_parameters, json_body
from api_mapper.models import ApiSpec, Endpoint, ErrorResponse, Parameter, SpecKind

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
FRAGMENT_METHOD = "SCHEMA"


def load_api_spec(path: Path, name: str | None = None) -> ApiSpec:
    document = load_document(path)
    return build_api_spec(document, source=str(path), base_dir=path.parent, name=name or path.stem)


def build_api_spec(document: Any, source: str, base_dir: Path, name: str | None = None) -> ApiSpec:
    """`name` keys every field of this API; without one the spec title is used."""
    if not isinstance(document, dict):
        raise SpecLoadError(source, "top level must be an object")

    kind = detect_kind(document)
    if kind is None:
        raise SpecLoadError(source, "not a Swagger/OpenAPI document and contains no schemas")

    resolver = RefResolver(document, base_dir)
    info = document.get("info") or {}
    name = name or str(info.get("title") or Path(source).stem)
    if kind is SpecKind.FRAGMENT:
        endpoints = _fragment_endpoints(document, resolver)
    else:
        endpoints = _path_endpoints(document, kind, resolver)

    return ApiSpec(
        name=slugify(name),
        title=str(info.get("title") or name),
        version=str(info.get("version") or ""),
        kind=kind,
        source=source,
        description=str(info.get("description") or ""),
        tags=tuple(str(t.get("name")) for t in document.get("tags") or [] if isinstance(t, dict)),
        endpoints=tuple(endpoints),
        warnings=tuple(resolver.warnings),
    )


def detect_kind(document: dict[str, Any]) -> SpecKind | None:
    if str(document.get("swagger", "")).startswith("2"):
        return SpecKind.SWAGGER_2
    if str(document.get("openapi", "")).startswith("3"):
        return SpecKind.OPENAPI_3
    if _fragment_schemas(document):
        return SpecKind.FRAGMENT
    return None


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "api"


def _path_endpoints(document: dict, kind: SpecKind, resolver: RefResolver) -> list[Endpoint]:
    endpoints = []
    for path, path_item in (document.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        path_item = resolver.resolve(path_item)
        shared_parameters = path_item.get("parameters") or []
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if isinstance(operation, dict):
                endpoints.append(_endpoint(method, str(path), operation, shared_parameters, kind))
    return endpoints


def _endpoint(method: str, path: str, operation: dict, shared_parameters: list, kind: SpecKind) -> Endpoint:
    responses = {str(status): body for status, body in (operation.get("responses") or {}).items()}
    success_status = _success_status(responses)
    schema, examples = _response_content(responses.get(success_status or "") or {}, kind)

    request_schema, request_required = json_body(operation, shared_parameters)
    return Endpoint(
        method=method.upper(),
        path=path,
        operation_id=str(operation.get("operationId") or f"{method}_{path}"),
        summary=str(operation.get("summary") or ""),
        tags=tuple(str(tag) for tag in operation.get("tags") or []),
        parameters=(*_parameters(shared_parameters, operation.get("parameters") or []),
                    *body_parameters(request_schema, request_required)),
        response_schema=schema,
        response_examples=examples,
        request_schema=request_schema,
        request_required=request_required,
        error_responses=tuple(
            _error_response(status, body, kind)
            for status, body in responses.items()
            if _is_error_status(status) and isinstance(body, dict)
        ),
    )


def _success_status(responses: dict[str, Any]) -> str | None:
    for status in sorted(responses):
        if status.startswith("2"):
            return status
    return "default" if "default" in responses else None


def _is_error_status(status: str) -> bool:
    return status[:1] in ("4", "5")


def _response_content(response: dict, kind: SpecKind) -> tuple[dict | None, tuple[Any, ...]]:
    if not isinstance(response, dict):
        return None, ()
    if kind is SpecKind.SWAGGER_2:
        examples = tuple((response.get("examples") or {}).values())
        return response.get("schema"), examples

    content = response.get("content") or {}
    media = _preferred_media(content)
    if media is None:
        return None, ()
    examples = []
    if "example" in media:
        examples.append(media["example"])
    for named in (media.get("examples") or {}).values():
        if isinstance(named, dict) and "value" in named:
            examples.append(named["value"])
    return media.get("schema"), tuple(examples)


def _preferred_media(content: dict) -> dict | None:
    if not content:
        return None
    if "application/json" in content:
        return content["application/json"]
    for media_type in sorted(content):
        if "json" in media_type:
            return content[media_type]
    return content[sorted(content)[0]]


def _error_response(status: str, body: dict, kind: SpecKind) -> ErrorResponse:
    schema, examples = _response_content(body, kind)
    return ErrorResponse(
        status=status,
        description=str(body.get("description") or ""),
        schema=schema or {},
        examples=examples,
    )


def _parameters(shared: list, own: list) -> tuple[Parameter, ...]:
    by_identity: dict[tuple[str, str], Parameter] = {}
    for raw in [*shared, *own]:
        if not isinstance(raw, dict) or "name" not in raw:
            continue
        location = str(raw.get("in", "query"))
        if location == "body":
            continue
        schema = raw.get("schema") or {k: raw[k] for k in ("type", "format", "enum") if k in raw}
        by_identity[(location, raw["name"])] = Parameter(
            name=str(raw["name"]),
            location=location,
            required=bool(raw.get("required", location == "path")),
            schema=schema,
        )
    return tuple(by_identity.values())


def _fragment_schemas(document: dict) -> dict[str, Any]:
    if isinstance(document.get("components"), dict) and isinstance(document["components"].get("schemas"), dict):
        return document["components"]["schemas"]
    if isinstance(document.get("definitions"), dict):
        return document["definitions"]
    if "properties" in document or document.get("type") in ("object", "array"):
        return {str(document.get("title") or "Root"): document}
    return {}


def _fragment_endpoints(document: dict, resolver: RefResolver) -> list[Endpoint]:
    endpoints = []
    for schema_name, schema in _fragment_schemas(document).items():
        if not isinstance(schema, dict):
            continue
        resolved = {SCHEMA_NAME_KEY: schema_name, **resolver.resolve(schema)}
        endpoints.append(
            Endpoint(
                method=FRAGMENT_METHOD,
                path=f"/{schema_name}",
                operation_id=schema_name,
                response_schema=resolved,
            )
        )
    return endpoints
