from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TransformKind(StrEnum):
    CAST = "cast"
    MINOR_UNITS_TO_DECIMAL = "minor-units-to-decimal"
    EPOCH_MILLIS_TO_DATETIME = "epoch-millis-to-datetime"
    EPOCH_SECONDS_TO_DATETIME = "epoch-seconds-to-datetime"
    COMPACT_DATE_TO_ISO = "compact-date-to-iso"
    DATETIME_TO_DATE = "datetime-to-date"
    ENUM_MAP = "enum-map"


@dataclass(frozen=True)
class TransformStep:
    kind: TransformKind
    description: str
    params: dict[str, Any] = field(default_factory=dict, compare=False)
