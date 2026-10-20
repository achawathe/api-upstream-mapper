"""Field-scoped allowed values and their documentary provenance."""

from dataclasses import dataclass, field

from api_mapper.models.purpose import ContextClue


@dataclass(frozen=True)
class EnumContract:
    values: tuple[str, ...] = ()
    origin: str = ''
    citations: tuple[str, ...] = ()
    definitions: dict[str, tuple[ContextClue, ...]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
