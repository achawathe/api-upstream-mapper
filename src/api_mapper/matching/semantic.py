"""Optional offline sentence embeddings, prepared once per run and shared by the matcher."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite, sqrt
from pathlib import Path
from typing import Protocol

from api_mapper.models import FieldProfile
from api_mapper.normalize.definitions import leading_definition
from api_mapper.normalize.tokenizer import split_identifier


class LocalNlpError(ValueError):
    """An explicitly requested local NLP model could not be used."""


class TextEncoder(Protocol):
    def encode(self, texts: list[str]) -> Sequence[Sequence[float]]: ...


@dataclass(frozen=True)
class NlpSettings:
    model_path: str = ""
    min_similarity: float = 0.80
    top_k: int = 10

    def __post_init__(self) -> None:
        if not isfinite(self.min_similarity) or not 0 < self.min_similarity <= 1:
            raise ValueError("NLP minimum similarity must be above 0 and at most 1")
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int) or self.top_k < 1:
            raise ValueError("NLP top_k must be a positive integer")


class LocalSentenceEncoder:
    def __init__(self, model_path: str):
        path = Path(model_path).expanduser().resolve()
        if not path.is_dir():
            raise LocalNlpError(f"local NLP model folder does not exist: {path}")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise LocalNlpError('install local NLP dependencies with python -m pip install -e ".[nlp]"') from error
        try:
            self._model = SentenceTransformer(str(path), device="cpu", local_files_only=True, trust_remote_code=False)
        except Exception as error:
            raise LocalNlpError(f"could not load local NLP model at {path}: {error}") from error

    def encode(self, texts: list[str]) -> Sequence[Sequence[float]]:
        try:
            return self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32)
        except Exception as error:
            raise LocalNlpError(f"local NLP encoding failed: {error}") from error


class SemanticIndex:
    def __init__(self, profiles: list[FieldProfile], encoder: TextEncoder, settings: NlpSettings):
        self.settings = settings
        has_documents = any(p.node.documentation for p in profiles)
        definitions = {p.node.key: _definitions(p) if has_documents else [] for p in profiles}
        texts = list(dict.fromkeys([*(_field_text(p) for p in profiles),
                                   *(text for values in definitions.values() for text, _ in values)]))
        vectors = list(encoder.encode(texts)) if texts else []
        if len(vectors) != len(texts):
            raise LocalNlpError("local NLP encoder returned the wrong number of vectors")
        normalised = [_normalise(vector) for vector in vectors]
        if len({len(vector) for vector in normalised}) > 1:
            raise LocalNlpError("local NLP encoder returned inconsistent vector dimensions")
        by_text = dict(zip(texts, normalised, strict=True))
        self._vectors = {profile.node.key: by_text[_field_text(profile)] for profile in profiles}
        self._definitions = {key: [(by_text[text], documented) for text, documented in values]
                             for key, values in definitions.items()}

    def similarity(self, target: FieldProfile, source: FieldProfile) -> float:
        left, right = self._vectors[target.node.key], self._vectors[source.node.key]
        scores = [_cosine(left, right)]
        scores.extend(_cosine(a, b) for a, a_doc in self._definitions[target.node.key]
                      for b, b_doc in self._definitions[source.node.key] if a_doc or b_doc)
        return max(scores)

    def candidates_for(self, target: FieldProfile, sources: list[FieldProfile]) -> list[FieldProfile]:
        scored = [(self.similarity(target, source), source) for source in sources]
        ranked = sorted(scored, key=lambda pair: (-pair[0], pair[1].node.key))
        return [source for score, source in ranked if score >= self.settings.min_similarity][: self.settings.top_k]


def _field_text(profile: FieldProfile) -> str:
    name = " ".join(split_identifier(" ".join(profile.node.segments)))
    description = " ".join(profile.node.description.split()[:80])
    text = f"{name}. {description}".strip()
    if profile.node.documentation:
        excerpts = ' '.join(c.text for c in profile.node.documentation)
        text = f'{excerpts} {text}'
    text = f"{text} {profile.node.sample_context}" if profile.node.sample_context else text
    clues = " ".join(f"Associated definition: {clue.text}." for clue in profile.node.context_clues[:3])
    return f"{text} {clues}" if clues else text


def _definitions(profile: FieldProfile) -> list[tuple[str, bool]]:
    found = [(clue.text, True) for clue in profile.node.documentation]
    if profile.node.description.strip():
        found.append((leading_definition(profile.node.description), False))
    return [(text, documented) for text, documented in found if text.strip()]


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


def _normalise(vector: Sequence[float]) -> tuple[float, ...]:
    values = tuple(float(value) for value in vector)
    if not values or not all(isfinite(value) for value in values):
        raise LocalNlpError("local NLP encoder returned an empty or non-finite vector")
    norm = sqrt(sum(value * value for value in values))
    if not isfinite(norm) or norm == 0:
        raise LocalNlpError("local NLP encoder returned an invalid vector norm")
    return tuple(value / norm for value in values)
