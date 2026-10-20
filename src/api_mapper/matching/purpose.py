"""Compare traceable field purposes; contextual discoveries are advisory, not score inflation."""

from dataclasses import dataclass

from api_mapper.models import Evidence, EvidenceEffect, FieldProfile


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
                f"{profile.node.path} has conflicting purpose descriptions; confirm the intended record or schema definition."
            )
    definition_match = bool(support) and not conflicts and not warnings
    if left.get("presentation") == {"product_label"} and not right.get("presentation"):
        values = source.node.value_profile
        if has_labels(source):
            support.append(
                f"{source.node.path} has {values.count} documented values, all word-based labels, with {values.distinct} distinct values; compatible with the target's display-name requirement. Examples do not prove product ownership."
            )
        elif values.count >= 2 and values.digit_strings == values.count:
            warnings.append(
                f"{source.node.path} has {values.count} documented values, all digit strings; these look like codes rather than the human-readable product names required upstream."
            )
    return PurposeComparison(tuple(support), tuple(conflicts), tuple(warnings), definition_match)


def comparison_evidence(comparison: PurposeComparison) -> list[Evidence]:
    return [
        *[Evidence("purpose_support", 1.0, 0.0, text) for text in comparison.support],
        *[Evidence("purpose_conflict", 0.0, 0.0, text, EvidenceEffect.VETO) for text in comparison.conflicts],
        *[Evidence("purpose_uncertain", 0.25, 0.0, text, EvidenceEffect.MULTIPLIER) for text in comparison.warnings],
    ]


def _proof(profile: FieldProfile, group: str) -> str:
    return "; ".join(
        dict.fromkeys(
            f'{fact.label} — {fact.location}: "{fact.quote}"' for fact in profile.purposes if fact.group == group
        )
    )
