from dataclasses import dataclass, field
from enum import StrEnum

from api_mapper.models.field_node import FieldNode
from api_mapper.models.transform import TransformStep


class MappingStatus(StrEnum):
    AUTO = "auto"
    REVIEW = "review"
    UNMAPPED = "unmapped"
    DERIVED = "derived"
    MANUAL = "manual"
    REJECTED = "rejected"


class EvidenceEffect(StrEnum):
    WEIGHTED = "weighted"
    MULTIPLIER = "multiplier"
    VETO = "veto"


@dataclass(frozen=True)
class Evidence:
    signal: str
    score: float
    weight: float
    detail: str
    effect: EvidenceEffect = EvidenceEffect.WEIGHTED


@dataclass(frozen=True)
class Candidate:
    source: FieldNode
    score: float
    evidence: tuple[Evidence, ...]
    transforms: tuple[TransformStep, ...] = ()
    vetoed_by: str | None = None


@dataclass
class FieldMapping:
    target: FieldNode
    status: MappingStatus
    chosen: Candidate | None = None
    alternatives: tuple[Candidate, ...] = ()
    notes: list[str] = field(default_factory=list)
    category: str = ''

    @property
    def is_mapped(self) -> bool:
        if self.status is MappingStatus.DERIVED:
            return True
        return self.chosen is not None and self.status in (
            MappingStatus.AUTO,
            MappingStatus.REVIEW,
            MappingStatus.MANUAL,
        )
