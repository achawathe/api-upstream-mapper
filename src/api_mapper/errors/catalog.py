"""Upstream error catalogs and the downstream errors found in specs."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api_mapper.loaders.document import SpecLoadError, load_document
from api_mapper.models import ApiSpec, DownstreamError, UpstreamError
from api_mapper.normalize.tokenizer import split_identifier

CODE_WORDS = frozenset({"code", "type", "kind"})
MESSAGE_WORDS = frozenset({"message", "msg", "detail", "reason", "title", "string", "description", "text"})


@dataclass(frozen=True)
class ErrorCatalog:
    errors: tuple[UpstreamError, ...]
    code_field: str = "code"
    message_field: str = "message"


def load_error_catalog(path: Path) -> ErrorCatalog:
    raw = load_document(path) or {}
    if not isinstance(raw.get("errors"), list):
        raise SpecLoadError(str(path), "error catalog needs an 'errors' list")
    body = raw.get("body") or {}
    return ErrorCatalog(
        errors=tuple(
            UpstreamError(
                code=str(entry["code"]),
                http_status=str(entry.get("http_status", "")),
                message=str(entry.get("message", "")),
                keywords=tuple(str(k).lower() for k in entry.get("keywords") or ()),
            )
            for entry in raw["errors"]
        ),
        code_field=str(body.get("code", "code")),
        message_field=str(body.get("message", "message")),
    )


def downstream_errors(spec: ApiSpec) -> list[DownstreamError]:
    found: list[DownstreamError] = []
    for endpoint in spec.endpoints:
        for response in endpoint.error_responses:
            # A shared error schema often lists every code the API has; only examples say which code
            # goes with which status, so declared enums are used only when they are unambiguous.
            entries = [error_code_and_message(example) for example in response.examples if isinstance(example, dict)]
            if not entries:
                declared = _declared_codes(response.schema)
                entries = [(declared[0], "")] if len(declared) == 1 else [(None, response.description)]
            for code, message in entries:
                found.append(
                    DownstreamError(
                        api=spec.name,
                        endpoint=endpoint.key,
                        http_status=response.status,
                        code=code,
                        message=message or response.description,
                    )
                )
    return found


def error_code_and_message(example: dict[str, Any]) -> tuple[str | None, str]:
    """Finds the code-like and message-like values anywhere in an error body."""
    leaves = list(_leaves(example))
    code = next((str(v) for name, v in leaves if _has_word(name, CODE_WORDS) and not isinstance(v, bool)), None)
    message = next((str(v) for name, v in leaves if _has_word(name, MESSAGE_WORDS)), "")
    return code, message


def _declared_codes(schema: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for name, prop in _schema_leaves(schema):
        if _has_word(name, CODE_WORDS):
            codes.extend(str(v) for v in prop.get("enum") or ())
    return codes


def _leaves(value: Any, name: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, str(key))
    elif isinstance(value, list):
        for child in value[:1]:
            yield from _leaves(child, name)
    else:
        yield name, value


def _schema_leaves(schema: Any, name: str = ""):
    if not isinstance(schema, dict):
        return
    if "properties" in schema:
        for key, child in schema["properties"].items():
            yield from _schema_leaves(child, str(key))
    elif "items" in schema:
        yield from _schema_leaves(schema["items"], name)
    else:
        yield name, schema


def _has_word(name: str, words: frozenset[str]) -> bool:
    return bool(words & set(split_identifier(name)))
