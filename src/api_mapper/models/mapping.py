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


class Signal(StrEnum):
    """Every kind of evidence the matcher records. Rules test these members, never raw strings."""

    NAME = "name"
    SPELLING = "spelling"
    TYPE = "type"
    STRUCTURE = "structure"
    ENUM = "enum"
    SAMPLE = "sample"
    DESCRIPTION = "description"
    ENDPOINT = "endpoint"
    CONTEXT = "context"
    QUALIFIER = "qualifier"
    MEANING = "meaning"
    ROLE = "role"
    MODIFIER = "modifier"
    ANCHOR = "anchor"
    COLLECTION = "collection"
    LIST_TO_ONE = "list-to-one"
    FAN_OUT = "fan-out"
    REACH = "reach"
    RECORD = "record"
    ECHO = "echo"
    DEPRECATED = "deprecated"
    ORIGIN_REQUIREMENT = "origin_requirement"
    PURPOSE_SUPPORT = "purpose_support"
    PURPOSE_CONFLICT = "purpose_conflict"
    PURPOSE_UNCERTAIN = "purpose_uncertain"
    DEFINITION_PREFERRED = "definition_preferred"
    DOCUMENTATION_CONTEXT = "documentation_context"
    DOCUMENTATION_SAMPLES = "documentation_samples"
    CONTEXT_REVIEW = "context_review"
    BODY_CONTEXT = "body_context"
    IDENTITY_REVIEW = "identity_review"
    RULES_SCORE = "rules_score"
    LOCAL_NLP = "local_nlp"
    NLP_ONLY = "nlp_only"
    SEMANTIC_REVIEW = "semantic_review"


@dataclass(frozen=True)
class Evidence:
    signal: Signal
    score: float
    weight: float
    detail: str
    effect: EvidenceEffect = EvidenceEffect.WEIGHTED

    def __post_init__(self) -> None:
        # Rejects unknown names here, so a misspelt signal fails loudly instead of disabling a rule.
        object.__setattr__(self, "signal", Signal(self.signal))


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
    category: str = ""

    @property
    def is_mapped(self) -> bool:
        if self.status is MappingStatus.DERIVED:
            return True
        return self.chosen is not None and self.status in (
            MappingStatus.AUTO,
            MappingStatus.REVIEW,
            MappingStatus.MANUAL,
        )
