"""Executes transform steps on real values (used by the validation harness)."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from api_mapper.models import TransformKind, TransformStep
from api_mapper.transforms.enum_normalization import translate_value


class TransformError(ValueError):
    pass


def apply_transforms(steps: tuple[TransformStep, ...], value: Any) -> Any:
    for step in steps:
        if value is None:
            return None
        value = _apply(step, value)
    return value


def _apply(step: TransformStep, value: Any) -> Any:
    kind = step.kind
    if kind is TransformKind.MINOR_UNITS_TO_DECIMAL:
        return float(Decimal(int(value)) / (Decimal(10) ** int(step.params.get("exponent", 2))))
    if kind is TransformKind.EPOCH_MILLIS_TO_DATETIME:
        return _iso(datetime.fromtimestamp(int(value) / 1000, tz=UTC))
    if kind is TransformKind.EPOCH_SECONDS_TO_DATETIME:
        return _iso(datetime.fromtimestamp(int(value), tz=UTC))
    if kind is TransformKind.COMPACT_DATE_TO_ISO:
        text = str(value)
        if len(text) != 8 or not text.isdigit():
            raise TransformError(f"{text!r} is not yyyyMMdd")
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if kind is TransformKind.DATETIME_TO_DATE:
        return str(value)[:10]
    if kind is TransformKind.ENUM_MAP:
        try:
            return translate_value(step.params, value)
        except (ValueError, TypeError) as error:
            raise TransformError(str(error)) from error
    if kind is TransformKind.CAST:
        return _cast(value, str(step.params.get("to", "string")))
    raise TransformError(f"unknown transform {kind}")


def _cast(value: Any, to: str) -> Any:
    try:
        if to == "number":
            return float(Decimal(str(value)))
        if to == "integer":
            return int(Decimal(str(value)))
        if to == "boolean":
            return str(value).strip().lower() in ("true", "y", "yes", "1")
        if to == "date-time":
            return f"{value}T00:00:00Z" if len(str(value)) == 10 else str(value)
        return str(value)
    except (InvalidOperation, ValueError) as error:
        raise TransformError(f"cannot cast {value!r} to {to}") from error


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
