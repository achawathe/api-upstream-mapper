from dataclasses import dataclass, field
from typing import Any

from api_mapper.models.purpose import ContextClue, ValueProfile

SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean", "any"})
# Path segments of a map whose keys are data: `rates.{key}` is each entry's value, `rates.@key` the key itself.
MAP_VALUE_SEGMENT = "{key}"
MAP_KEY_SEGMENT = "@key"
_MAP_SEGMENTS = (MAP_VALUE_SEGMENT, MAP_KEY_SEGMENT)


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
    context_clues: tuple[ContextClue, ...] = ()
    value_profile: ValueProfile = field(default_factory=ValueProfile)
    documentation: tuple[ContextClue, ...] = ()

    @property
    def key(self) -> str:
        variant = f"<{self.variant}>" if self.variant else ""
        return f"{self.api}|{self.endpoint}|{variant}{self.path}"

    @property
    def name(self) -> str:
        return self.segments[-1] if self.segments else ""

    @property
    def segments(self) -> tuple[str, ...]:
        """Named path segments; map segments stand for data, so `rates.{key}` is named by `rates`."""
        return tuple(
            s.removesuffix("[]") for s in self.path.split(".") if s.removesuffix("[]") and s not in _MAP_SEGMENTS
        )

    @property
    def map_path(self) -> str | None:
        """The innermost map this field belongs to, as `balances` for `balances.{key}.current`."""
        parts = self.path.split(".")
        found = [i for i, segment in enumerate(parts) if segment in _MAP_SEGMENTS]
        return ".".join(parts[: found[-1]]) if found else None

    @property
    def is_map_key(self) -> bool:
        return self.path.endswith(f".{MAP_KEY_SEGMENT}")

    @property
    def parent_segments(self) -> tuple[str, ...]:
        return self.segments[:-1]
