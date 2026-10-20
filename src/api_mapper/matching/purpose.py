"""Compare traceable field purposes; contextual discoveries are advisory, not score inflation."""

from dataclasses import dataclass

from api_mapper.models import Evidence, EvidenceEffect, FieldProfile, Signal


def roles(profile: FieldProfile) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for fact in profile.purposes:
        groups.setdefault(fact.group, set()).add(fact.role)
    return groups


def has_labels(profile: FieldProfile) -> bool:
    values = profile.node.value_profile
    return values.count >= 2 and values.distinct >= 2 and values.text_labels == values.count


@dataclass(frozen=True)
class PurposeComparison:
    support: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    definition_match: bool = False


def compare_purposes(target: FieldProfile, source: FieldProfile) -> PurposeComparison:
    left, right = roles(target), roles(source)
    support, conflicts, warnings = [], [], []
    if left.get("origin") == {"upstream_generated"}:
        conflicts.append(
            "Upstream definition requires an upstream-generated value; a downstream response is not its origin. "
            + _proof(target, "origin")
        )
    for group in sorted((left.keys() & right.keys()) - {"origin"}):
        if len(left[group]) != 1 or len(right[group]) != 1:
            continue
        proof = f"Target: {_proof(target, group)} Source: {_proof(source, group)}"
        target_label = next(f.label for f in target.purposes if f.group == group)
        source_label = next(f.label for f in source.purposes if f.group == group)
        if left[group] == right[group]:
            support.append(f"Both definitions describe {target_label}. {proof}")
        else:
            conflicts.append(f"Target requires {target_label}; source describes {source_label}. {proof}")
    for profile in (target, source):
        if any(len(values) > 1 for values in roles(profile).values()):
            warnings.append(
                f"{profile.node.path} has conflicting purpose descriptions; "
                "confirm the intended record or schema definition."
            )
    definition_match = bool(support) and not conflicts and not warnings
    label_purpose = next((f for f in target.purposes if f.expects_labels), None)
    if label_purpose and not right.get(label_purpose.group):
        support_note, warning = _label_values(source, label_purpose.label)
        support.extend(support_note)
        warnings.extend(warning)
    return PurposeComparison(tuple(support), tuple(conflicts), tuple(warnings), definition_match)


def _label_values(source: FieldProfile, label: str) -> tuple[list[str], list[str]]:
    """Sample values show whether a source holds readable labels or codes; they never prove ownership."""
    values = source.node.value_profile
    path = source.node.path
    if has_labels(source):
        return [
            f"{path} has {values.count} documented values, all word-based labels ({values.distinct} distinct); "
            f"compatible with a {label}. Examples do not prove which record they belong to."
        ], []
    if values.count >= 2 and values.digit_strings == values.count:
        return [], [
            f"{path} has {values.count} documented values, all digit strings; these look like codes, not a {label}."
        ]
    return [], []


def comparison_evidence(comparison: PurposeComparison) -> list[Evidence]:
    return [
        *[Evidence(Signal.PURPOSE_SUPPORT, 1.0, 0.0, text) for text in comparison.support],
        *[Evidence(Signal.PURPOSE_CONFLICT, 0.0, 0.0, text, EvidenceEffect.VETO) for text in comparison.conflicts],
        *[
            Evidence(Signal.PURPOSE_UNCERTAIN, 0.25, 0.0, text, EvidenceEffect.MULTIPLIER)
            for text in comparison.warnings
        ],
    ]


def _proof(profile: FieldProfile, group: str) -> str:
    return "; ".join(
        dict.fromkeys(
            f'{fact.label} — {fact.location}: "{fact.quote}"' for fact in profile.purposes if fact.group == group
        )
    )
