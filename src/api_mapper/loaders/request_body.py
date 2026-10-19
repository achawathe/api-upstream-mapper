"""Extract addressable JSON body inputs without inventing a choice between schema branches."""

from api_mapper.models import Parameter
from api_mapper.normalize.flattener import merge_all_of

MAX_BODY_DEPTH = 12
_CONTEXT_NAMES = frozenset({"clientid", "clientsecret", "accesstoken", "refreshtoken", "apikey",
                            "secret", "password", "authorization"})


def json_body(operation: dict, shared: list) -> tuple[dict | None, bool]:
    body = operation.get("requestBody") or {}
    content = body.get("content") or {}
    media = content.get("application/json") or next(
        (value for key, value in content.items() if key.endswith("+json")), {}
    )
    if isinstance(media.get("schema"), dict):
        return media["schema"], bool(body.get("required"))
    raw = next((p for p in operation.get("parameters", []) if p.get("in") == "body"), None)
    raw = raw or next((p for p in shared if p.get("in") == "body"), None)
    return (raw.get("schema") or {}, bool(raw.get("required"))) if raw else (None, False)


def body_parameters(schema: dict | None, required: bool) -> tuple[Parameter, ...]:
    return tuple(_leaves(schema, "", required)) if schema is not None else ()


def _leaves(schema: dict, path: str, required: bool, depth: int = 0):
    schema = merge_all_of(schema)
    properties = schema.get("properties") or {}
    if depth >= MAX_BODY_DEPTH or schema.get("oneOf") or schema.get("anyOf") or not properties:
        name = path.rsplit(".", 1)[-1].replace("_", "").replace("-", "").lower()
        context_only = name in _CONTEXT_NAMES or bool(schema.get("writeOnly")) or schema.get("format") == "password"
        yield Parameter(path or "$body", "body", required, schema, context_only=context_only)
        return
    if any("." in name for name in properties):
        yield Parameter(path or "$body", "body", required, schema)
        return
    for name, child in properties.items():
        child_path = f"{path}.{name}" if path else name
        yield from _leaves(child, child_path, required and name in (schema.get("required") or []), depth + 1)
