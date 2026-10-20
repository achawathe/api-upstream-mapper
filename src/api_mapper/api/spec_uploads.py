"""Keep uploaded spec bundles intact and choose entrypoints independently of file order."""

from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from api_mapper.loaders import SpecLoadError, load_document


def save_bundle(folder: Path, uploads: list[tuple[str, bytes]]) -> list[Path]:
    names = [PurePosixPath(name.replace("\\", "/")) for name, _ in uploads]
    if not names:
        raise ValueError("choose at least one file")
    if any(p.is_absolute() or ".." in p.parts or not p.name or ":" in str(p) for p in names):
        raise ValueError("upload filenames must be relative paths within the spec folder")
    if len({str(p).casefold() for p in names}) != len(names):
        raise ValueError("duplicate upload filenames; upload a folder to preserve their paths")
    paths = [folder / str(name) for name in names]
    for path, (_, content) in zip(paths, uploads, strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return paths


def spec_entrypoints(paths: list[Path], single: bool) -> list[Path]:
    documents, broken = {}, []
    for path in paths:
        try:
            documents[path] = load_document(path)
        except SpecLoadError:
            broken.append(path)
    referenced = {target for path, document in documents.items() for target in local_references(document, path.parent)}
    roots = [p for p in paths if p.resolve() not in referenced]
    specs = [p for p in roots if _is_api(documents.get(p))]
    fragments = [p for p in roots if p not in specs and _is_fragment(documents.get(p))]
    candidates = (specs or fragments or broken) if single else [*specs, *fragments, *broken]
    if single and len(candidates) != 1:
        raise ValueError("upload one upstream entrypoint together with its referenced model files")
    if not candidates:
        raise ValueError("no API spec found; attach response JSON using Documentation response examples")
    return sorted(candidates)


def _is_api(document) -> bool:
    return isinstance(document, dict) and any(k in document for k in ("openapi", "swagger", "endpoints"))


def _is_fragment(document) -> bool:
    return isinstance(document, dict) and (document.get("type") in ("object", "array")
                                          or any(k in document for k in ("components", "definitions", "properties")))


def local_references(node, directory: Path):
    if isinstance(node, list):
        for item in node:
            yield from local_references(item, directory)
    elif isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            file = unquote(ref.partition("#")[0])
            if file and ":" not in file:
                yield (directory / file).resolve()
        for value in node.values():
            yield from local_references(value, directory)
