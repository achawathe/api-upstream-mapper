"""Validate documented ISO date values without promoting examples into schema guarantees."""

from datetime import date, datetime

from api_mapper.models import FieldNode


def observed_date_format(source: FieldNode) -> str | None:
    values = (*source.observed, *(() if source.example is None else (source.example,)))
    formats = {_date_format(value) for value in values}
    return next(iter(formats)) if len(formats) == 1 and None not in formats else None


def _date_format(value: object) -> str | None:
    if not isinstance(value, str) or len(value) < 10 or value[4:5] != "-" or value[7:8] != "-":
        return None
    try:
        if len(value) == 10:
            date.fromisoformat(value)
            return "date"
        if value[10:11] in {"T", " "}:
            datetime.fromisoformat(value)
            return "date-time"
    except ValueError:
        pass
    return None
