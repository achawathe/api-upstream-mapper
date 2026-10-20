"""Field-scoped allowed values and their documentary provenance."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EnumContract:
    values: tuple[str, ...] = ()
    origin: str = ''
    citations: tuple[str, ...] = ()
    aliases: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    unresolved_aliases: tuple[str, ...] = ()
