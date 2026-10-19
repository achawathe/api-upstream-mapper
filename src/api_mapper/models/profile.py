from dataclasses import dataclass, field

from api_mapper.models.field_node import FieldNode


@dataclass(frozen=True)
class FieldProfile:
    """A FieldNode translated into lexicon concepts, ready for comparison.

    `bag` weighs each concept by where it came from: the leaf name counts fully,
    parent names count less, unless the leaf is too generic (`id`, `amount`) to stand alone.
    `anchor` is what the field itself is about: its leaf concepts without the entity
    word, preferring meaningful ones over generic ones. `collection` is the concept of the
    innermost array it sits in (`transaction` for `transactions[].amount`).
    `qualifiers` are account families stated on the field's own path or schemas;
    `scope` are families implied only by the API or endpoint it belongs to.
    `identity` is what the field names, without account-family words (`loan_id` -> account
    identifier); `endpoint_inputs` holds the identities of its endpoint's path parameters and bindable JSON body inputs.
    `guesses` lists unknown spellings that were read as known words, e.g. ("blnc", "balance").
    """

    node: FieldNode
    leaf: tuple[str, ...]
    anchor: frozenset[str]
    parent: tuple[str, ...]
    collection: tuple[str, ...]
    leaf_is_generic: bool
    bag: dict[str, float] = field(compare=False)
    compact_leaf: str
    compact_context: str
    qualifiers: frozenset[str]
    scope: frozenset[str]
    roles: frozenset[str]
    endpoint_concepts: tuple[str, ...]
    description_concepts: frozenset[str]
    temporal: bool
    guesses: tuple[tuple[str, str], ...] = ()
    identity: frozenset[str] = frozenset()
    endpoint_inputs: frozenset[frozenset[str]] = frozenset()

    @property
    def families(self) -> frozenset[str]:
        return self.qualifiers or self.scope

    @property
    def echoes_input(self) -> bool:
        """The field only repeats its endpoint's own input (`acctNum` from `/routing/{acctNum}`)."""
        return self.node.array_depth == 0 and self.identity in self.endpoint_inputs
