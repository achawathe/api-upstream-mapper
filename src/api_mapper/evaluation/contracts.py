"""Exact field-origin grading for a deliberately bounded public-contract answer key.

A correct origin is not proof that filtering, joins or value conversions are complete.
Labels record those additional conditions separately from field matching accuracy.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Any

from api_mapper.models import FieldMapping


@dataclass(frozen=True)
class ContractGrade:
    rows: list[dict[str, Any]]

    @property
    def summary(self) -> dict[str, int]:
        counts = Counter(row["outcome"] for row in self.rows)
        return {
            "labels": len(self.rows),
            "source_fields": sum(bool(row["expected"]) for row in self.rows),
            **{key: counts[key] for key in ("correct", "wrong", "missed", "abstained")},
            "automatic": sum(row["status"] == "auto" for row in self.rows),
            "wrong_automatic": sum(row["status"] == "auto" and row["outcome"] == "wrong" for row in self.rows),
            "conditional_automatic": sum(
                row["status"] == "auto" and row["outcome"] == "correct" and row["conditional"] for row in self.rows
            ),
        }


def grade_contract(mappings: list[FieldMapping], labels: list[dict[str, Any]], source_keys: set[str]) -> ContractGrade:
    by_target = {mapping.target.key.split("|", 1)[1]: mapping for mapping in mappings}
    seen = set()
    rows = []
    for label in labels:
        key = label["target"]
        if key in seen or key not in by_target:
            raise ValueError(f"duplicate or missing contract target: {key}")
        seen.add(key)
        expected = set(label["expected"])
        if missing := expected - source_keys:
            raise ValueError(f"contract sources missing: {sorted(missing)}")
        mapping = by_target[key]
        actual = mapping.chosen.source.key if mapping.chosen else None
        if actual:
            outcome = "correct" if actual in expected else "wrong"
        else:
            outcome = "missed" if expected else "abstained"
        rows.append(
            {
                **label,
                "actual": actual,
                "status": mapping.status.value,
                "outcome": outcome,
                "score": mapping.chosen.score if mapping.chosen else None,
                "decision_notes": list(mapping.notes),
            }
        )
    return ContractGrade(rows)
