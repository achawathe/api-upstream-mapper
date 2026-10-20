"""Decides how a source value must be converted to fit a target field, and how compatible the types are."""

import re
from dataclasses import dataclass

from api_mapper.models import FieldNode, TransformKind, TransformStep
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.transforms.enum_inference import enum_transform
from api_mapper.transforms.enum_mapping import EnumMapper, EnumMapping
from api_mapper.transforms.numeric_evidence import has_numeric_text
from api_mapper.transforms.temporal_evidence import observed_date_format

_COMPACT_DATE = re.compile(r"^\d{8}$")
_EPOCH_MILLIS_FLOOR = 100_000_000_000
_TEMPORAL_FORMATS = frozenset({"date", "date-time"})
_NUMERIC_TYPES = frozenset({"number", "integer"})
_NON_QUANTITY_FORMATS = frozenset({"uri", "uri-reference", "url", "uuid", "email", "hostname", "ipv4", "ipv6"})


@dataclass(frozen=True)
class TypeFit:
    score: float
    steps: tuple[TransformStep, ...] = ()
    veto: str | None = None
    detail: str = ""
    enum_mapping: EnumMapping | None = None


class TypeFitter:
    def __init__(self, lexicon: Lexicon):
        self.lexicon = lexicon
        self.enum_mapper = EnumMapper(lexicon)

    def fit(self, target: FieldNode, source: FieldNode, source_is_temporal: bool) -> TypeFit:
        fit = _type_fit(target, source, self.lexicon, source_is_temporal)
        if fit.veto:
            return fit
        step, mapping = enum_transform(target, source, self.enum_mapper)
        return TypeFit(fit.score, (*fit.steps, step) if step else fit.steps, None, fit.detail, mapping)


def _type_fit(target: FieldNode, source: FieldNode, lexicon: Lexicon, source_is_temporal: bool) -> TypeFit:
    t, s = target.type, source.type
    target_temporal = target.format in _TEMPORAL_FORMATS
    if "any" in (t, s):
        return TypeFit(0.7, detail="one side has no declared type")

    if target_temporal:
        return _temporal_fit(target, source, lexicon, source_is_temporal)
    if source.format in _TEMPORAL_FORMATS and t != "string":
        return TypeFit(0.0, veto=f"date value cannot fill a {t}")

    if t == s:
        return TypeFit(1.0, detail=f"both {t}")
    if t == "number" and s == "integer":
        if _mentions(source, lexicon.minor_unit_markers, lexicon):
            return TypeFit(
                1.0,
                (_step(TransformKind.MINOR_UNITS_TO_DECIMAL, "divide by 100 (minor units)", exponent=2),),
                detail="integer minor units to decimal",
            )
        return TypeFit(0.9, (_cast("number"),), detail="integer widens to number")
    if t == "integer" and s == "number":
        return TypeFit(0.6, (_cast("integer"),), detail="number narrows to integer")
    if t in _NUMERIC_TYPES and s == "string":
        if source.format in _NON_QUANTITY_FORMATS:
            return TypeFit(0.0, veto=f"{source.format} text cannot supply a numeric value")
        numeric_example = has_numeric_text(source, integer=t == "integer")
        return TypeFit(0.85 if numeric_example else 0.55, (_cast(t),), detail="numeric text parsed to number")
    if t == "string" and s in _NUMERIC_TYPES:
        return TypeFit(0.7, (_cast("string"),), detail=f"{s} rendered as text")
    if "boolean" in (t, s):
        other = s if t == "boolean" else t
        if other == "string":
            return TypeFit(0.4, (_cast(t),), detail="boolean/text flag conversion")
        return TypeFit(0.0, veto=f"boolean is not compatible with {other}")
    if t in ("object", "array") or s in ("object", "array"):
        return TypeFit(0.0, veto=f"{s} cannot fill {t}")
    return TypeFit(0.3, (_cast(t),), detail=f"{s} cast to {t}")


def _temporal_fit(target: FieldNode, source: FieldNode, lexicon: Lexicon, source_is_temporal: bool) -> TypeFit:
    if source.format in _NON_QUANTITY_FORMATS:
        return TypeFit(0.0, veto=f"{source.format} text cannot supply a date")
    if source.type in ("boolean", "number"):
        return TypeFit(0.0, veto=f"{source.type} cannot be a date")
    if source.type == "integer":
        if not (source_is_temporal or _mentions(source, lexicon.epoch_markers, lexicon)):
            return TypeFit(0.0, veto="integer without date meaning cannot be a date")
        millis = not isinstance(source.example, int) or source.example >= _EPOCH_MILLIS_FLOOR
        kind = TransformKind.EPOCH_MILLIS_TO_DATETIME if millis else TransformKind.EPOCH_SECONDS_TO_DATETIME
        steps = [_step(kind, f"epoch {'milliseconds' if millis else 'seconds'} to ISO-8601 UTC")]
        if target.format == "date":
            steps.append(_step(TransformKind.DATETIME_TO_DATE, "keep the date part"))
        return TypeFit(0.9, tuple(steps), detail="epoch integer to date")

    if source.format == target.format:
        return TypeFit(1.0, detail=f"both {target.format}")
    if source.format == "date-time" and target.format == "date":
        return TypeFit(0.9, (_step(TransformKind.DATETIME_TO_DATE, "keep the date part"),), detail="timestamp to date")
    if source.format == "date" and target.format == "date-time":
        return TypeFit(0.75, (_cast("date-time"),), detail="date widened to midnight UTC timestamp")
    if _looks_compact_date(source):
        steps = [_step(TransformKind.COMPACT_DATE_TO_ISO, "yyyyMMdd to yyyy-MM-dd")]
        return TypeFit(0.95, tuple(steps), detail="compact date to ISO date")
    if not source.format and (observed_format := observed_date_format(source)):
        steps = ()
        if observed_format == "date-time" and target.format == "date":
            steps = (_step(TransformKind.DATETIME_TO_DATE, "keep the date part"),)
        elif observed_format == "date" and target.format == "date-time":
            steps = (_cast("date-time"),)
        return TypeFit(
            0.6, steps, detail="documented values parse as ISO dates; schema format and event meaning need confirmation"
        )
    if source_is_temporal:
        return TypeFit(0.6, detail="text date with undeclared format")
    return TypeFit(0.0, veto="source has no date format or temporal meaning")


def _looks_compact_date(source: FieldNode) -> bool:
    if isinstance(source.example, str) and _COMPACT_DATE.match(source.example):
        return True
    return "yyyymmdd" in source.description.lower()


def _mentions(node: FieldNode, markers: tuple[str, ...], lexicon: Lexicon) -> bool:
    return lexicon.mentions_any(f"{node.description} {node.name}", markers)


def _cast(to_type: str) -> TransformStep:
    return _step(TransformKind.CAST, f"cast to {to_type}", to=to_type)


def _step(kind: TransformKind, description: str, **params) -> TransformStep:
    return TransformStep(kind=kind, description=description, params=params)
