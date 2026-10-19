"""Applies and persists manual decisions. Overrides are replayed on every run, so a
re-run with updated specs keeps what people decided, and reports decisions that no
longer apply instead of silently dropping them."""

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

from api_mapper.models import Candidate, FieldMapping, MappingStatus, Override, OverrideAction

PairScorer = Callable[[str, str], Candidate | None]


def apply_overrides(mappings: list[FieldMapping], overrides: Iterable[Override], score_pair: PairScorer) -> list[str]:
    by_target = {m.target.key: m for m in mappings}
    warnings = []
    for override in overrides:
        mapping = by_target.get(override.target_key)
        if mapping is None:
            warnings.append(f"override for {override.target_key} ignored: field no longer exists upstream")
            continue
        problem = _apply(mapping, override, score_pair)
        if problem:
            warnings.append(problem)
    return warnings


def _apply(mapping: FieldMapping, override: Override, score_pair: PairScorer) -> str | None:
    note = f"manual {override.action.value}" + (f" by {override.author}" if override.author else "") + (
        f": {override.note}" if override.note else ""
    )
    if override.action is OverrideAction.REJECT:
        if mapping.chosen:
            mapping.alternatives = (mapping.chosen, *mapping.alternatives)
        mapping.chosen = None
        mapping.status = MappingStatus.REJECTED
    elif override.action is OverrideAction.ACCEPT:
        if mapping.chosen is None:
            return f"override accept on {mapping.target.key} ignored: nothing was proposed"
        mapping.status = MappingStatus.MANUAL
    else:
        candidate = next((c for c in mapping.alternatives if c.source.key == override.source_key), None)
        candidate = candidate or score_pair(mapping.target.key, override.source_key or "")
        if candidate is None:
            return f"override on {mapping.target.key} ignored: source {override.source_key} no longer exists"
        previous = mapping.chosen
        mapping.alternatives = tuple(c for c in (previous, *mapping.alternatives) if c and c.source.key != candidate.source.key)
        mapping.chosen = candidate
        mapping.status = MappingStatus.MANUAL
        if candidate.vetoed_by:
            note += f" (tool vetoed this pair: {candidate.vetoed_by})"
    mapping.notes.append(note)
    return None


def load_overrides(path: Path) -> list[Override]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Override(
            target_key=item["target_key"],
            action=OverrideAction(item["action"]),
            source_key=item.get("source_key"),
            note=item.get("note", ""),
            author=item.get("author", ""),
        )
        for item in raw.get("overrides", [])
    ]


def save_overrides(path: Path, overrides: Iterable[Override]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"overrides": [asdict(o) for o in overrides]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
