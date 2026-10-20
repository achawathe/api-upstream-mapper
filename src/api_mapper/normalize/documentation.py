"""Bind cited text to declared fields, respecting endpoint sections and ambiguous names."""

import re
from collections import defaultdict
from dataclasses import replace

from api_mapper.models import ApiSpec, FieldNode
from api_mapper.models.purpose import ContextClue

_ENDPOINT = re.compile(r'\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[^\s`|,;]+)', re.IGNORECASE)
_MAX_PASSAGES = 16


def enrich_documentation(spec: ApiSpec, nodes: list[FieldNode]) -> list[FieldNode]:
    if not spec.documentation:
        return nodes
    endpoints = {endpoint.key for endpoint in spec.endpoints}
    matches: dict[str, list[ContextClue]] = defaultdict(list)
    scopes = {}
    for passage in spec.documentation:
        document = passage.location.split(' · ', 1)[0]
        scope = passage.endpoint or scopes.get(document, '')
        for line_number, line in enumerate(passage.text.splitlines(), 1):
            mentions = {f'{method.upper()} {path.rstrip(".:")}' for method, path in _ENDPOINT.findall(line)}
            if mentions:
                scope = next(iter(mentions)) if len(mentions) == 1 else '!ambiguous'
                scopes[document] = scope
            if scope and scope not in endpoints:
                continue
            eligible = [node for node in nodes if not scope or node.endpoint == scope]
            line_fields = [node for node in eligible if _mentions(line, node.name)]
            for sentence in re.split(r'(?<=[.!?])\s+', line):
                found = [node for node in eligible if _mentions(sentence, node.name)]
                if not found and len(line_fields) == 1:
                    found = line_fields
                by_name = defaultdict(set)
                for node in found:
                    by_name[node.name].add((node.endpoint, node.path))
                for node in found:
                    if len(by_name[node.name]) > 1:
                        path_matches = {n.endpoint for n in found if n.path == node.path}
                        if len(path_matches) != 1 or node.path == node.name or not _mentions(sentence, node.path):
                            continue
                    if len(sentence.split()) > 120:
                        continue
                    definition = re.sub(r'^\s*[-*|` ]*' + re.escape(node.name) + r'[` ]*\s*[:|=-]\s*', '', sentence)
                    clue = ContextClue(definition.strip(), f'{passage.location}, line {line_number}')
                    if clue not in matches[node.key] and len(matches[node.key]) < _MAX_PASSAGES:
                        matches[node.key].append(clue)
    return [replace(node, documentation=tuple(matches[node.key])) for node in nodes]


def _mentions(text: str, identifier: str) -> bool:
    return bool(identifier and re.search(r'(?<![\w])' + re.escape(identifier) + r'(?![\w])', text))
