import re
from dataclasses import replace
from functools import lru_cache

from api_mapper.models import ApiSpec, Endpoint, FieldNode
from api_mapper.models.profile import FieldProfile
from api_mapper.normalize.inputs import bindable_body, input_name
from api_mapper.normalize.lexicon import ENTITY_CONCEPT, Lexicon
from api_mapper.normalize.purpose import field_purposes
from api_mapper.normalize.resolver import TokenResolver
from api_mapper.normalize.tokenizer import singularize, split_identifier

_VERSION_SEGMENT = re.compile(r"^v\d+(\.\d+)*$", re.IGNORECASE)
_DESCRIPTION_WORD_LIMIT = 40
_TEMPORAL_CONCEPTS = frozenset({"date", "timestamp"})
_TEMPORAL_FORMATS = frozenset({"date", "date-time", "time"})

LEAF_WEIGHT = 1.0
PARENT_WEIGHT = 0.5
GRANDPARENT_WEIGHT = 0.25
RESOURCE_WEIGHT = 0.8


class Profiler:
    """Profiles fields. Words it does not know are first read against the lexicon and
    the upstream spec's own vocabulary (see TokenResolver)."""

    def __init__(self, lexicon: Lexicon, vocabulary: frozenset[str] = frozenset()):
        self.lexicon = lexicon
        known = lexicon.known_words | lexicon.stopwords | set(lexicon.abbreviations)
        self.resolver = TokenResolver(known | vocabulary, lexicon.abbreviations)
        self._concepts = lru_cache(maxsize=None)(self._read)

    @staticmethod
    def vocabulary_of(nodes: list[FieldNode]) -> frozenset[str]:
        words = set()
        for node in nodes:
            for segment in (*node.segments, *node.schema_names):
                words.update(singularize(t) for t in split_identifier(segment))
        return frozenset(words)

    def _read(self, text: str) -> tuple[str, ...]:
        return self.lexicon.concepts_of_tokens(self.resolver.resolve_all(split_identifier(text)))

    def profile_spec(self, spec: ApiSpec, nodes: list[FieldNode]) -> list[FieldProfile]:
        api_scope = self.lexicon.family_of(self._concepts(" ".join((spec.name, spec.title, *spec.tags))))
        endpoints = {endpoint.key: endpoint for endpoint in spec.endpoints}
        endpoint_info = {key: self._endpoint_context(endpoint) for key, endpoint in endpoints.items()}
        inputs = {key: self._input_concepts(endpoint) for key, endpoint in endpoints.items()}
        profiles = []
        for node in nodes:
            concepts, endpoint_scope = endpoint_info.get(node.endpoint, ((), frozenset()))
            profile = self.profile(node, api_scope | endpoint_scope, concepts)
            profiles.append(
                replace(
                    profile, identity=self._identity(profile), endpoint_inputs=frozenset(inputs.get(node.endpoint, ()))
                )
            )
        return profiles

    def _input_concepts(self, endpoint: Endpoint) -> set[frozenset[str]]:
        return {
            self.param_identity(input_name(parameter, self.lexicon), endpoint.path)
            for parameter in endpoint.parameters
            if parameter.location == "path" or (parameter.location == "body" and bindable_body(parameter))
        }

    def param_identity(self, name: str, path: str) -> frozenset[str]:
        """What a request parameter names; a bare `{id}` borrows the resource before it (`/cards/accounts/{id}`)."""
        concepts = list(self._concepts(name))
        if self.lexicon.is_generic(concepts):
            segments = path.split("/")
            position = segments.index(f"{{{name}}}") if f"{{{name}}}" in segments else len(segments)
            resource = next((s for s in reversed(segments[:position]) if s and not s.startswith("{")), "")
            concepts = [*self._concepts(resource), *concepts]
        return self._without_families(concepts)

    def _identity(self, profile: FieldProfile) -> frozenset[str]:
        concepts = (
            [c for c, share in profile.bag.items() if share >= 1.0] if profile.leaf_is_generic else list(profile.leaf)
        )
        return self._without_families(concepts)

    def _without_families(self, concepts) -> frozenset[str]:
        return frozenset(ENTITY_CONCEPT if c in self.lexicon.families else c for c in concepts)

    def profile(self, node: FieldNode, scope: frozenset[str], endpoint_concepts: tuple[str, ...]) -> FieldProfile:
        leaf = self._concepts(node.name)
        ancestors = [c for c in (self._concepts(s) for s in reversed(node.parent_segments)) if c]
        leaf_is_generic = self.lexicon.is_generic(leaf)
        bag = self._bag(leaf, ancestors, leaf_is_generic, endpoint_concepts)
        path_concepts = [c for group in ancestors for c in group]
        context_names = [self._concepts(name) for name in (*node.schema_names, *(node.variant or "").split("/"))]

        return FieldProfile(
            node=node,
            leaf=leaf,
            anchor=self._anchor(leaf),
            parent=ancestors[0] if ancestors else (),
            collection=self._collection(node, endpoint_concepts),
            leaf_is_generic=leaf_is_generic,
            bag=bag,
            compact_leaf="".join(leaf),
            compact_context="".join((*(ancestors[0] if ancestors else ()), *leaf)),
            qualifiers=self.lexicon.family_of([*path_concepts, *(c for group in context_names for c in group)]),
            scope=scope,
            roles=self.lexicon.roles_of([*leaf, *path_concepts]),
            endpoint_concepts=endpoint_concepts,
            description_concepts=self._description_concepts(
                " ".join((node.description, *(c.text for c in node.documentation)))
            ),
            temporal=bool(_TEMPORAL_CONCEPTS & set(leaf)) or (node.format in _TEMPORAL_FORMATS),
            guesses=tuple(dict.fromkeys(g for segment in node.segments for g in self._guesses(segment))),
            purposes=field_purposes(node, self.lexicon.purpose_rules),
        )

    def _bag(
        self,
        leaf: tuple[str, ...],
        ancestors: list[tuple[str, ...]],
        leaf_is_generic: bool,
        endpoint_concepts: tuple[str, ...],
    ) -> dict[str, float]:
        bag: dict[str, float] = {}

        def add(concepts: tuple[str, ...], weight: float) -> None:
            for concept in concepts:
                bag[concept] = max(bag.get(concept, 0.0), weight)

        add(leaf, LEAF_WEIGHT)
        if ancestors:
            add(ancestors[0], LEAF_WEIGHT if leaf_is_generic else PARENT_WEIGHT)
        if len(ancestors) > 1:
            add(ancestors[1], PARENT_WEIGHT if leaf_is_generic else GRANDPARENT_WEIGHT)
        if leaf_is_generic and not ancestors and endpoint_concepts:
            add(endpoint_concepts[-1:], RESOURCE_WEIGHT)
        return bag

    def _anchor(self, leaf: tuple[str, ...]) -> frozenset[str]:
        own = [c for c in leaf if c != ENTITY_CONCEPT]
        meaningful = [c for c in own if c not in self.lexicon.generic and c not in self.lexicon.weak]
        return frozenset(meaningful or own)

    def _collection(self, node: FieldNode, endpoint_concepts: tuple[str, ...]) -> tuple[str, ...]:
        """Concepts of the innermost array's item. When the array's name is unknown, or only a
        guess or abbreviation that the endpoint path contradicts (`trans[]` under `/transfers`),
        the endpoint's resource names the items instead;
        if that is unknown too, it stays empty, since an unknown name is no evidence either way."""
        raw_segments = node.path.split(".")
        array_positions = [i for i, segment in enumerate(raw_segments) if segment.endswith("[]")]
        if not array_positions:
            return ()
        resource = endpoint_concepts[-1:] if endpoint_concepts and self._is_known(endpoint_concepts[-1]) else ()
        for segment in raw_segments[array_positions[-1] : -1] or raw_segments[-1:]:
            name = segment.removesuffix("[]")
            concepts = self._concepts(name)
            if not concepts:
                continue
            uncertain = bool(self._guesses(name)) or self._abbreviated(name)
            if self._is_known(concepts[-1]) and not (uncertain and resource and resource[-1] != concepts[-1]):
                return concepts
            break
        return resource

    def _guesses(self, text: str) -> list[tuple[str, str]]:
        return [(token, word) for token in split_identifier(text) if (word := self.resolver.resolve(token)) != token]

    def _abbreviated(self, text: str) -> bool:
        abbreviations = self.lexicon.abbreviations
        return any(t in abbreviations or singularize(t) in abbreviations for t in split_identifier(text))

    def _is_known(self, concept: str) -> bool:
        return concept in self.lexicon.known_words or self.resolver.is_known(concept)

    def _endpoint_context(self, endpoint: Endpoint) -> tuple[tuple[str, ...], frozenset[str]]:
        literal_segments = [
            segment
            for segment in endpoint.path.split("/")
            if segment and not segment.startswith("{") and not _VERSION_SEGMENT.match(segment)
        ]
        concepts = tuple(c for segment in literal_segments for c in self._concepts(segment))
        parameter_concepts = [c for p in endpoint.path_parameters for c in self._concepts(p.name)]
        scope = self.lexicon.family_of([*concepts, *parameter_concepts, *self._concepts(" ".join(endpoint.tags))])
        return concepts, scope

    def _description_concepts(self, description: str) -> frozenset[str]:
        if not description:
            return frozenset()
        words = split_identifier(description)[:_DESCRIPTION_WORD_LIMIT]
        return frozenset(self.lexicon.concepts_of_tokens(words))
