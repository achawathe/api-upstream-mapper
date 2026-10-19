"""Dereferences `$ref` pointers, including refs into other local files.

Each resolved schema is tagged with `x-schema-name` (the ref's last segment) because
schema names carry context the matcher needs, e.g. `LineOfCreditAccount`.
A ref that points back into its own expansion becomes `{"x-cycle": name}`.
"""

from pathlib import Path
from typing import Any
from urllib.parse import unquote

from api_mapper.loaders.document import SpecLoadError, load_document

SCHEMA_NAME_KEY = "x-schema-name"
CYCLE_KEY = "x-cycle"
UNRESOLVED_KEY = "x-unresolved-ref"


class RefResolver:
    def __init__(self, document: Any, base_dir: Path):
        self._root_key = str(base_dir.resolve() / "<root>")
        self._documents: dict[str, Any] = {self._root_key: document}
        self._resolved: dict[str, Any] = {}
        self._in_progress: list[str] = []
        self.warnings: list[str] = []

    def resolve(self, node: Any, document_key: str | None = None) -> Any:
        document_key = document_key or self._root_key
        if isinstance(node, list):
            return [self.resolve(item, document_key) for item in node]
        if not isinstance(node, dict):
            return node
        if isinstance(node.get("$ref"), str):
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            resolved = self._resolve_reference(node["$ref"], document_key)
            if siblings and isinstance(resolved, dict):
                return {**resolved, **self.resolve(siblings, document_key)}
            return resolved
        return {key: self.resolve(value, document_key) for key, value in node.items()}

    def _resolve_reference(self, ref: str, document_key: str) -> Any:
        file_part, _, pointer = ref.partition("#")
        if file_part.startswith(("http://", "https://")):
            return self._unresolved(ref, "remote references are not fetched")
        try:
            target_key = self._document_key_for(file_part, document_key)
        except SpecLoadError as error:
            return self._unresolved(ref, error.reason)

        ref_id = f"{target_key}#{pointer}"
        name = _ref_name(pointer, file_part)
        if ref_id in self._in_progress:
            return {CYCLE_KEY: name}
        if ref_id not in self._resolved:
            try:
                raw = _follow_pointer(self._documents[target_key], pointer)
            except KeyError:
                return self._unresolved(ref, "pointer does not exist")
            self._in_progress.append(ref_id)
            try:
                resolved = self.resolve(raw, target_key)
            finally:
                self._in_progress.pop()
            if isinstance(resolved, dict) and SCHEMA_NAME_KEY not in resolved:
                resolved = {**resolved, SCHEMA_NAME_KEY: name}
            self._resolved[ref_id] = resolved
        return self._resolved[ref_id]

    def _document_key_for(self, file_part: str, current_key: str) -> str:
        if not file_part:
            return current_key
        path = (Path(current_key).parent / unquote(file_part)).resolve()
        key = str(path)
        if key not in self._documents:
            self._documents[key] = load_document(path)
        return key

    def _unresolved(self, ref: str, reason: str) -> dict[str, str]:
        self.warnings.append(f"unresolved $ref {ref!r}: {reason}")
        return {UNRESOLVED_KEY: ref}


def _follow_pointer(document: Any, pointer: str) -> Any:
    node = document
    for raw_part in pointer.lstrip("/").split("/") if pointer.strip("/") else []:
        part = unquote(raw_part).replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                raise KeyError(part)
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(part)
    return node


def _ref_name(pointer: str, file_part: str) -> str:
    if pointer.strip("/"):
        return unquote(pointer.rstrip("/").rsplit("/", 1)[-1])
    return Path(file_part).stem
