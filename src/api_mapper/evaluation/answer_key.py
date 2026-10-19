"""Loads a ground-truth answer key (see samples/answer_key.yaml for the format)."""

from dataclasses import dataclass
from pathlib import Path

from api_mapper.loaders.document import SpecLoadError, load_document

DERIVED = "derived"


@dataclass(frozen=True)
class Expectation:
    sources: frozenset[str]
    derived: bool = False
    optional: bool = False


@dataclass(frozen=True)
class AnswerKey:
    upstream_api: str
    expectations: dict[str, Expectation]

    def for_target(self, target_key: str) -> Expectation | None:
        return self.expectations.get(target_key)


def load_answer_key(path: Path, upstream_api: str) -> AnswerKey:
    raw = load_document(path) or {}
    aliases = raw.get("sources") or {}
    expectations: dict[str, Expectation] = {}
    for group in raw.get("groups") or []:
        endpoint = group.get("endpoint")
        if not endpoint:
            raise SpecLoadError(str(path), "every group needs an endpoint")
        for variant in group.get("variants") or [None]:
            for field_path, value in (group.get("expect") or {}).items():
                key = _target_key(upstream_api, endpoint, variant, field_path)
                expectations[key] = _expectation(value, aliases, optional=False)
            for field_path, value in (group.get("optional") or {}).items():
                key = _target_key(upstream_api, endpoint, variant, field_path)
                expectations[key] = _expectation(value, aliases, optional=True)
    return AnswerKey(upstream_api=upstream_api, expectations=expectations)


def _target_key(api: str, endpoint: str, variant: str | None, path: str) -> str:
    return f"{api}|{endpoint}|{f'<{variant}>' if variant else ''}{path}"


def _expectation(value: str | list[str], aliases: dict[str, str], optional: bool) -> Expectation:
    if value == DERIVED:
        return Expectation(sources=frozenset(), derived=True, optional=optional)
    return Expectation(sources=frozenset(_expand(source, aliases) for source in value), optional=optional)


def _expand(source: str, aliases: dict[str, str]) -> str:
    alias, separator, rest = source.partition(":")
    if separator and alias in aliases:
        return f"{aliases[alias]}{rest}"
    return source
