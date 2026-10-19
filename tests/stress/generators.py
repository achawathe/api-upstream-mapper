"""Builds stress inputs: renamed copies of the sample downstreams, and large sets of noise APIs.

Renaming follows how real APIs differ: casing style, abbreviations and synonyms from the
lexicon, applied consistently per API. The answer key is rewritten with the same renames,
so ground truth is preserved and never hand-edited.
"""

import json
import random
import shutil
from pathlib import Path
from typing import Any

import yaml

from api_mapper.loaders.document import load_document
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.normalize.tokenizer import split_identifier
from tests.conftest import SAMPLES

VOWELS = set("aeiou")
FILLERS = ("value", "field", "info")


class Renamer:
    """`hard` adds spellings the lexicon has never seen: dropped vowels, truncation,
    reversed word order and filler words."""

    def __init__(self, lexicon: Lexicon, rng: random.Random, abbreviate: float = 0.5, synonym: float = 0.3, hard: bool = False):
        self.rng = rng
        self.abbreviate = abbreviate
        self.synonym = synonym
        self.hard = hard
        self.style = rng.choice(["camel", "snake", "pascal"])
        self.short_forms: dict[str, list[str]] = {}
        for short, expansion in lexicon.abbreviations.items():
            if len(expansion) == 1 and short.isalpha():
                self.short_forms.setdefault(expansion[0], []).append(short)
        self.alternatives: dict[str, list[str]] = {}
        for word, concept in lexicon.synonyms.items():
            if word.isalpha():
                self.alternatives.setdefault(concept, []).append(word)
        self.renames: dict[str, str] = {}

    def rename(self, name: str) -> str:
        if name not in self.renames:
            self.renames[name] = self._new_name(name)
        return self.renames[name]

    def _new_name(self, name: str) -> str:
        words = []
        for word in split_identifier(name):
            if word in self.short_forms and self.rng.random() < self.abbreviate:
                word = self.rng.choice(sorted(self.short_forms[word]))
            elif word in self.alternatives and len(self.alternatives[word]) > 1 and self.rng.random() < self.synonym:
                word = self.rng.choice(sorted(self.alternatives[word]))
            elif self.hard and len(word) > 4 and self.rng.random() < 0.35:
                word = word[0] + "".join(c for c in word[1:] if c not in VOWELS)
            elif self.hard and len(word) > 6 and self.rng.random() < 0.2:
                word = word[:5]
            words.append(word)
        if self.hard and len(words) > 1 and self.rng.random() < 0.2:
            words.reverse()
        if self.hard and self.rng.random() < 0.1:
            words.append(self.rng.choice(FILLERS))
        if self.style == "snake":
            return "_".join(words)
        joined = "".join(w.capitalize() for w in words)
        return joined if self.style == "pascal" else joined[:1].lower() + joined[1:]


def mutate_schema_tree(node: Any, renamer: Renamer, inside_example: bool = False) -> Any:
    if isinstance(node, list):
        return [mutate_schema_tree(item, renamer, inside_example) for item in node]
    if not isinstance(node, dict):
        return node
    if inside_example:
        return {renamer.rename(k): mutate_schema_tree(v, renamer, True) for k, v in node.items()}
    result = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            result[key] = {renamer.rename(k): mutate_schema_tree(v, renamer) for k, v in value.items()}
        elif key == "required" and isinstance(value, list):
            result[key] = [renamer.rename(v) if isinstance(v, str) else v for v in value]
        elif key == "example":
            result[key] = mutate_schema_tree(value, renamer, True)
        elif key == "examples":
            result[key] = _mutate_examples(value, renamer)
        else:
            result[key] = mutate_schema_tree(value, renamer)
    return result


def _mutate_examples(examples: Any, renamer: Renamer) -> Any:
    """Swagger maps media types to bodies; OpenAPI 3 maps names to {value: body}; 3.1 schemas list bodies."""
    if isinstance(examples, list):
        return mutate_schema_tree(examples, renamer, True)
    if not isinstance(examples, dict):
        return examples
    result = {}
    for key, example in examples.items():
        if isinstance(example, dict) and "value" in example:
            result[key] = {**example, "value": mutate_schema_tree(example["value"], renamer, True)}
        else:
            result[key] = mutate_schema_tree(example, renamer, True)
    return result


def write_mutated_downstreams(target: Path, seed: int, lexicon: Lexicon, hard: bool = False) -> tuple[list[Path], dict[str, Renamer]]:
    rng = random.Random(seed)
    source_root = SAMPLES / "downstream"
    shutil.copytree(source_root / "common", target / "common")
    specs, renamers = [], {}
    for api_dir in sorted(p for p in source_root.iterdir() if p.is_dir() and p.name != "common"):
        renamer = Renamer(lexicon, random.Random(rng.random()), hard=hard)
        renamers[api_dir.name] = renamer
        out_dir = target / api_dir.name
        out_dir.mkdir(parents=True)
        for file in sorted(api_dir.iterdir()):
            document = load_document(file)
            is_manifest = file.stem == "manifest"
            is_payload = file.suffix == ".json" and api_dir.name == "routing" and not is_manifest
            mutated = mutate_schema_tree(document, renamer, inside_example=is_payload) if not is_manifest else document
            _write(out_dir / file.name, mutated)
            if file.stem in ("openapi", "swagger", "manifest"):
                specs.append(out_dir / file.name)
    return specs, renamers


def write_mutated_answer_key(target: Path, renamers: dict[str, Renamer]) -> Path:
    raw = load_document(SAMPLES / "answer_key.yaml")

    def rename_source(source: str) -> str:
        alias, sep, path = source.partition(":")
        full = f"{raw['sources'][alias]}{path}" if sep and alias in raw["sources"] else source
        api, endpoint, field_path = full.split("|")
        return f"{api}|{endpoint}|{_rename_path(field_path, renamers[api])}"

    for group in raw["groups"]:
        for section in ("expect", "optional"):
            for field_path, value in (group.get(section) or {}).items():
                if value != "derived":
                    group[section][field_path] = [rename_source(s) for s in value]
    path = target / "answer_key.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path


def _rename_path(path: str, renamer: Renamer) -> str:
    segments = []
    for segment in path.split("."):
        name, arrays = segment.split("[", 1) if "[" in segment else (segment, None)
        renamed = renamer.renames.get(name, name) if name else name
        segments.append(f"{renamed}[{arrays}" if arrays is not None else renamed)
    return ".".join(segments)


NOISE_RESOURCES = [
    "branch", "atm", "merchant", "offer", "notification", "document", "device", "session", "fx rate", "reward",
    "dispute", "beneficiary", "standing order", "direct debit", "card control", "budget", "goal", "alert",
    "consent", "kyc check", "loyalty tier", "statement request", "address change", "travel notice", "tax form",
    "fee schedule", "product catalog", "interest tier", "rate sheet", "chargeback", "token", "webhook",
    "audit event", "login", "message", "appointment", "complaint", "survey", "campaign", "referral", "voucher",
    "limit change",
]
NOISE_FIELDS = [
    "id", "name", "status", "type", "createdAt", "updatedAt", "description", "amount", "currency", "code",
    "externalRef", "ownerPartyId", "accountId", "nickname", "email", "phone", "effectiveDate", "expiryDate",
    "rate", "priority", "channel", "category", "region", "count", "enabled", "label", "version",
]


def write_noise_apis(target: Path, count: int, seed: int) -> list[Path]:
    """Plausible APIs that have nothing the upstream needs, but share many generic field names."""
    rng = random.Random(seed)
    paths = []
    for index in range(count):
        resource = NOISE_RESOURCES[index % len(NOISE_RESOURCES)]
        slug = resource.replace(" ", "-")
        camel = "".join(w.capitalize() for w in resource.split())
        fields = rng.sample(NOISE_FIELDS, 12) + [f"{camel[0].lower()}{camel[1:]}Id", f"{camel[0].lower()}{camel[1:]}Name"]
        properties = {f: _noise_schema(f) for f in fields}
        item = {"type": "object", "properties": properties}
        spec = {
            "openapi": "3.0.3",
            "info": {"title": f"{camel} Service {index}", "version": "1.0.0"},
            "paths": {
                f"/{slug}s": {"get": {"responses": {"200": {"description": "list", "content": {"application/json": {"schema": {"type": "object", "properties": {"items": {"type": "array", "items": item}}}}}}}}},
                f"/{slug}s/{{{camel[0].lower()}{camel[1:]}Id}}": {"get": {"parameters": [{"name": f"{camel[0].lower()}{camel[1:]}Id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "one", "content": {"application/json": {"schema": item}}}}}},
            },
        }
        path = target / f"noise-{index:02d}-{slug}.json"
        path.write_text(json.dumps(spec))
        paths.append(path)
    return paths


def _noise_schema(field: str) -> dict[str, Any]:
    if field.endswith(("At",)):
        return {"type": "string", "format": "date-time"}
    if field.endswith("Date"):
        return {"type": "string", "format": "date"}
    if field in ("amount", "rate"):
        return {"type": "number"}
    if field in ("count", "priority", "version"):
        return {"type": "integer"}
    if field == "enabled":
        return {"type": "boolean"}
    return {"type": "string"}


def _write(path: Path, document: Any) -> None:
    if path.suffix == ".json":
        path.write_text(json.dumps(document, indent=1))
    else:
        path.write_text(yaml.safe_dump(document, sort_keys=False))
