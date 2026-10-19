"""Scores a mapping run against an answer key."""

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from api_mapper.evaluation.answer_key import AnswerKey, Expectation
from api_mapper.models import FieldMapping, MappingStatus


class Outcome(StrEnum):
    CORRECT_AUTO = "correct-auto"
    CORRECT_REVIEW = "correct-review"
    CORRECT_DERIVED = "correct-derived"
    CORRECT_UNMAPPED = "correct-unmapped"
    OPTIONAL_AUTO = "optional-auto"
    OPTIONAL_REVIEW = "optional-review"
    WRONG_AUTO = "wrong-auto"
    WRONG_REVIEW = "wrong-review"
    MISSED = "missed"
    SPURIOUS_AUTO = "spurious-auto"
    SPURIOUS_REVIEW = "spurious-review"


@dataclass
class GradeReport:
    outcomes: dict[str, Outcome]
    details: dict[str, str] = field(default_factory=dict)

    @property
    def counts(self) -> Counter:
        return Counter(self.outcomes.values())

    @property
    def auto_precision(self) -> float:
        c = self.counts
        right = c[Outcome.CORRECT_AUTO] + c[Outcome.OPTIONAL_AUTO]
        decided = right + c[Outcome.WRONG_AUTO] + c[Outcome.SPURIOUS_AUTO]
        return right / decided if decided else 1.0

    @property
    def expected_total(self) -> int:
        c = self.counts
        return sum(c[o] for o in (Outcome.CORRECT_AUTO, Outcome.CORRECT_REVIEW, Outcome.WRONG_AUTO, Outcome.WRONG_REVIEW, Outcome.MISSED))

    @property
    def recall(self) -> float:
        c = self.counts
        found = c[Outcome.CORRECT_AUTO] + c[Outcome.CORRECT_REVIEW]
        return found / self.expected_total if self.expected_total else 1.0

    @property
    def auto_recall(self) -> float:
        return self.counts[Outcome.CORRECT_AUTO] / self.expected_total if self.expected_total else 1.0

    def failures(self) -> dict[str, str]:
        bad = {Outcome.WRONG_AUTO, Outcome.WRONG_REVIEW, Outcome.MISSED, Outcome.SPURIOUS_AUTO, Outcome.SPURIOUS_REVIEW}
        return {key: f"{self.outcomes[key]}: {self.details.get(key, '')}" for key in self.outcomes if self.outcomes[key] in bad}

    def summary(self) -> str:
        counts = ", ".join(f"{outcome.value}={self.counts[outcome]}" for outcome in Outcome)
        return (
            f"auto precision {self.auto_precision:.1%} | recall {self.recall:.1%} | "
            f"auto recall {self.auto_recall:.1%} | {counts}"
        )


def grade(mappings: list[FieldMapping], key: AnswerKey) -> GradeReport:
    report = GradeReport(outcomes={})
    for mapping in mappings:
        target_key = mapping.target.key
        expectation = key.for_target(target_key)
        chosen = mapping.chosen.source.key if mapping.chosen else None
        report.details[target_key] = f"chose {chosen} ({mapping.status})"
        report.outcomes[target_key] = _outcome(mapping, expectation, chosen)
    return report


def _outcome(mapping: FieldMapping, expectation: Expectation | None, chosen: str | None) -> Outcome:
    status = mapping.status
    if expectation is None:
        if status is MappingStatus.AUTO:
            return Outcome.SPURIOUS_AUTO
        if status is MappingStatus.REVIEW:
            return Outcome.SPURIOUS_REVIEW
        return Outcome.CORRECT_UNMAPPED

    if expectation.derived:
        return Outcome.CORRECT_DERIVED if status is MappingStatus.DERIVED else Outcome.MISSED

    is_correct = chosen in expectation.sources
    if status is MappingStatus.AUTO:
        if is_correct:
            return Outcome.OPTIONAL_AUTO if expectation.optional else Outcome.CORRECT_AUTO
        return Outcome.SPURIOUS_AUTO if expectation.optional else Outcome.WRONG_AUTO
    if status is MappingStatus.REVIEW:
        if is_correct:
            return Outcome.OPTIONAL_REVIEW if expectation.optional else Outcome.CORRECT_REVIEW
        return Outcome.SPURIOUS_REVIEW if expectation.optional else Outcome.WRONG_REVIEW
    return Outcome.CORRECT_UNMAPPED if expectation.optional else Outcome.MISSED
