import json
import re
from pathlib import Path
from typing import Any

import yaml


class SpecLoadError(Exception):
    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


class _SpecYamlLoader(yaml.SafeLoader):
    """YAML 1.1 reads unquoted dates as date objects and yes/no/on/off as booleans.

    Specs mean those as plain strings (an enum of [Y, N, yes, no] is common), so only
    true/false stay boolean and dates stay text.
    """


_YAML_BOOL = "tag:yaml.org,2002:bool"
_YAML_TIMESTAMP = "tag:yaml.org,2002:timestamp"
_SpecYamlLoader.yaml_implicit_resolvers = {
    first_char: [(tag, regex) for tag, regex in resolvers if tag not in (_YAML_BOOL, _YAML_TIMESTAMP)]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_SpecYamlLoader.add_implicit_resolver(_YAML_BOOL, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))


def parse_document(text: str, source: str) -> Any:
    stripped = text.lstrip()
    if not stripped:
        raise SpecLoadError(source, "file is empty")
    if stripped[0] in "{[":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    try:
        return yaml.load(text, Loader=_SpecYamlLoader)
    except yaml.YAMLError as error:
        raise SpecLoadError(source, f"not valid JSON or YAML ({error})") from error


def load_document(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SpecLoadError(str(path), f"cannot read file ({error.strerror})") from error
    except UnicodeDecodeError as error:
        raise SpecLoadError(str(path), "file is not UTF-8 text") from error
    return parse_document(text, str(path))
