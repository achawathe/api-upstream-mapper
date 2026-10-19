from dataclasses import dataclass, field
from typing import Any

SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean", "any"})


@dataclass(frozen=True)
class FieldNode:
    """One mappable leaf of a response schema.

    `path` uses dots for nesting and `[]` for array items, e.g. `accounts[].currency.currencyCode`.
    `observed` holds distinct text values seen in samples and examples, used like an
    enum when the source declares none. `variant` names the oneOf/anyOf branch the field lives in; `condition` is the
    discriminator test that selects that branch, when the spec declares one.
    """

    api: str
    endpoint: str
    path: str
    type: str
    required: bool = False
    nullable: bool = False
    deprecated: bool = False
    format: str | None = None
    enum: tuple[str, ...] = ()
    description: str = ""
    example: Any = field(default=None, compare=False)
    observed: tuple[str, ...] = field(default=(), compare=False)
    variant: str | None = None
    condition: str | None = None
    schema_names: tuple[str, ...] = ()
    array_depth: int = 0
    sample_sources: tuple[str, ...] = ()
    sample_context: str = ""

    @property
    def key(self) -> str:
        variant = f"<{self.variant}>" if self.variant else ""
        return f"{self.api}|{self.endpoint}|{variant}{self.path}"

    @property
    def name(self) -> str:
        return self.segments[-1] if self.segments else ""

    @property
    def segments(self) -> tuple[str, ...]:
        return tuple(s.removesuffix("[]") for s in self.path.split(".") if s.removesuffix("[]"))

    @property
    def parent_segments(self) -> tuple[str, ...]:
        return self.segments[:-1]
