"""Attach documentation responses to declared endpoints without rewriting their schemas."""

import json
from dataclasses import replace
from typing import Any

from api_mapper.models import ApiSpec


def parse_response(name: str, content: bytes) -> Any:
    try:
        value = json.loads(content, parse_constant=_invalid_constant)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError(f"{name}: provide a valid JSON response body ({error})") from error
    if not isinstance(value, (dict, list)):
        raise ValueError(f"{name}: provide a JSON object or array response body")  # noqa: TRY004 - invalid uploaded content
    return value


def attach_responses(spec: ApiSpec, endpoint_key: str, samples: list[tuple[str, Any]]) -> ApiSpec:
    endpoint = spec.endpoint(endpoint_key)
    if endpoint.response_schema is None:
        raise ValueError(f"{endpoint_key} has no success response schema; use the API without a spec workflow")
    sources = endpoint.response_sample_sources or tuple("inline example" for _ in endpoint.response_examples)
    enriched = replace(endpoint, response_examples=(*endpoint.response_examples, *(value for _, value in samples)),
                       response_sample_sources=(*sources, *(name for name, _ in samples)))
    return replace(spec, endpoints=tuple(enriched if e.key == endpoint_key else e for e in spec.endpoints))


def _invalid_constant(value: str):
    raise ValueError(f"non-JSON constant {value}")
