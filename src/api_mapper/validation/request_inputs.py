"""Build requests from location-aware bindings; body values never become URL parameters."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from api_mapper.models import Endpoint
from api_mapper.normalize.flattener import merge_all_of


class RequestInputError(ValueError):
    pass


@dataclass(frozen=True)
class RequestParts:
    path: str
    query: dict[str, Any]
    body: Any


def request_parts(endpoint: Endpoint, values: dict[str, Any]) -> RequestParts:
    path, query, body = endpoint.path, {}, {}
    missing = []
    for parameter in endpoint.parameters:
        key = f"{parameter.location}:{parameter.name}"
        if key not in values or values[key] is None:
            if parameter.required and parameter.location in {"path", "query", "body"}:
                missing.append(key)
            continue
        value = values[key]
        if parameter.location == "path":
            path = path.replace("{" + parameter.name + "}", quote(str(value), safe=""))
        elif parameter.location == "query":
            query[parameter.name] = value
        elif parameter.location == "body":
            if parameter.schema.get("type") == "array" and not isinstance(value, list):
                value = [value]
            if parameter.name == "$body":
                body = value
            else:
                _write_body(body, parameter.name, value)
    has_body = endpoint.request_required or any(key.startswith("body:") for key in values)
    if has_body:
        missing.extend(_missing_children(endpoint.request_schema or {}, body))
    if missing:
        raise RequestInputError("required inputs missing: " + ", ".join(dict.fromkeys(missing)))
    return RequestParts(path, query, body if has_body else None)


def _write_body(body: dict, path: str, value: Any) -> None:
    if not isinstance(body, dict):
        raise RequestInputError(f"conflicting JSON body paths at {path}")
    parts = path.split(".")
    node = body
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise RequestInputError(f"conflicting JSON body paths at {path}")
    node[parts[-1]] = value


def _missing_children(schema: dict, value: Any, path: str = "") -> list[str]:
    schema = merge_all_of(schema)
    missing = []
    if isinstance(value, dict):
        missing.extend(f"body:{path}{name}" for name in schema.get("required", []) if name not in value)
        for name, child in (schema.get("properties") or {}).items():
            if name in value:
                missing.extend(_missing_children(child, value[name], f"{path}{name}."))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            missing.extend(_missing_children(schema.get("items") or {}, child, f"{path}[{index}]."))
    return missing
