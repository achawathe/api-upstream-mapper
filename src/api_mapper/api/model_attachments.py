"""Attach referenced model documents to a private copy of an existing spec bundle."""

import shutil
import tempfile
import uuid
from pathlib import Path

from api_mapper.api.spec_uploads import local_references, save_bundle
from api_mapper.loaders import SpecLoadError, load_document


def attach_models(files_root: Path, entrypoint: Path, uploads: list[tuple[str, bytes]]) -> tuple[Path, list[str]]:
    files_root, entrypoint = files_root.resolve(), entrypoint.resolve()
    if not entrypoint.is_relative_to(files_root):
        raise ValueError("upload the upstream spec before attaching model files")
    bundle = files_root / entrypoint.relative_to(files_root).parts[0]
    destination = files_root / uuid.uuid4().hex[:12]
    try:
        shutil.copytree(bundle, destination)
        new_entrypoint = destination / entrypoint.relative_to(bundle)
        with tempfile.TemporaryDirectory(prefix="api-mapper-models-") as temporary:
            incoming = Path(temporary)
            paths = save_bundle(incoming, uploads)
            for path in paths:
                if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                    raise ValueError("model files must be YAML or JSON")
                if not isinstance(load_document(path), dict):
                    raise SpecLoadError(path.name, "a model file must contain a schema object")
            _place_models(new_entrypoint, destination, incoming, paths)
        names = sorted(
            str(p.relative_to(destination))
            for p in destination.rglob("*")
            if p.is_file() and p != new_entrypoint and p.suffix.lower() in {".yaml", ".yml", ".json"}
        )
        return new_entrypoint, names
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _place_models(entrypoint: Path, bundle: Path, incoming: Path, paths: list[Path]) -> None:
    pending, placed = list(paths), set()
    while pending:
        references = _reachable_references(entrypoint, bundle)
        progressed = False
        for path in pending[:]:
            relative = path.relative_to(incoming)
            exact = {bundle / relative, entrypoint.parent / relative} & references
            matches = exact or {ref for ref in references if ref.name == path.name}
            if len(matches) > 1:
                raise ValueError(
                    f"{relative}: more than one reference uses this filename; upload a folder with the referenced paths"
                )
            if not matches:
                continue
            _place(path, next(iter(matches)), entrypoint, bundle, placed)
            pending.remove(path)
            progressed = True
        if not progressed:
            for path in pending:
                _place(path, entrypoint.parent / path.relative_to(incoming), entrypoint, bundle, placed)
            break


def _place(source: Path, target: Path, entrypoint: Path, bundle: Path, placed: set[Path]) -> None:
    target = target.resolve()
    if not target.is_relative_to(bundle) or target == entrypoint:
        raise ValueError("model attachments cannot replace the upstream spec or write outside its bundle")
    if target in placed:
        raise ValueError(f"multiple model files resolve to {target.relative_to(bundle)}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    placed.add(target)


def _reachable_references(entrypoint: Path, bundle: Path) -> set[Path]:
    pending, visited, references = [entrypoint], set(), set()
    while pending:
        path = pending.pop()
        if path in visited or not path.is_relative_to(bundle):
            continue
        visited.add(path)
        try:
            document = load_document(path)
        except SpecLoadError:
            continue
        found = set(local_references(document, path.parent))
        references.update(found)
        pending.extend(found - visited)
    return references
