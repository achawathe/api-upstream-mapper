"""Loaded API descriptions. Schemas here are already dereferenced plain dicts."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from api_mapper.models.documentation import DocumentationPassage


class SpecKind(StrEnum):
    SWAGGER_2 = "swagger-2.0"
    OPENAPI_3 = "openapi-3"
    FRAGMENT = "schema-fragment"
    SAMPLES = "sample-payloads"


@dataclass(frozen=True)
class Parameter:
    name: str
    location: str
    required: bool
    schema: dict[str, Any] = field(default_factory=dict, compare=False)
    context_only: bool = False


@dataclass(frozen=True)
class ErrorResponse:
    status: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict, compare=False)
    examples: tuple[Any, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    operation_id: str
    summary: str = ""
    tags: tuple[str, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    response_schema: dict[str, Any] | None = field(default=None, compare=False)
    response_examples: tuple[Any, ...] = field(default=(), compare=False)
    error_responses: tuple[ErrorResponse, ...] = field(default=(), compare=False)
    request_schema: dict[str, Any] | None = field(default=None, compare=False)
    request_required: bool = False
    response_sample_sources: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def path_parameters(self) -> tuple[Parameter, ...]:
        return tuple(p for p in self.parameters if p.location == "path")


@dataclass(frozen=True)
class ApiSpec:
    name: str
    title: str
    version: str
    kind: SpecKind
    source: str
    description: str = ""
    tags: tuple[str, ...] = ()
    endpoints: tuple[Endpoint, ...] = ()
    warnings: tuple[str, ...] = ()
    documentation: tuple[DocumentationPassage, ...] = ()

    def endpoint(self, key: str) -> Endpoint:
        for endpoint in self.endpoints:
            if endpoint.key == key:
                return endpoint
        raise KeyError(f"{self.name} has no endpoint {key!r}")
