from api_mapper.loaders.ref_resolver import CYCLE_KEY
from api_mapper.models import Endpoint
from api_mapper.normalize.flattener import flatten_endpoint, merge_all_of


def _flatten(schema, examples=()):
    endpoint = Endpoint(method="GET", path="/x", operation_id="x", response_schema=schema, response_examples=examples)
    return {(n.variant, n.path): n for n in flatten_endpoint("api", endpoint)}


def test_all_of_merges_properties_and_required():
    merged = merge_all_of(
        {
            "allOf": [
                {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                {"properties": {"id": {"description": "override"}, "name": {"type": "string"}}},
            ]
        }
    )
    assert merged["required"] == ["id"]
    assert merged["properties"]["id"] == {"type": "string", "description": "override"}
    assert "name" in merged["properties"]


def test_one_of_branches_become_variants_with_discriminator_conditions():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "discriminator": {"propertyName": "kind", "mapping": {"A": "#/x/Alpha"}},
                    "oneOf": [
                        {
                            "x-schema-name": "Alpha",
                            "type": "object",
                            "properties": {"kind": {"type": "string"}, "a": {"type": "integer"}},
                        },
                        {
                            "x-schema-name": "Beta",
                            "type": "object",
                            "properties": {"kind": {"enum": ["B"]}, "b": {"type": "string"}},
                        },
                    ],
                },
            }
        },
    }
    fields = _flatten(schema)
    assert fields[("Alpha", "items[].a")].condition == "kind = A"
    assert fields[("Beta", "items[].b")].condition == "kind = B"
    assert fields[("Alpha", "items[].a")].array_depth == 1


def test_scalar_arrays_maps_and_cycles():
    schema = {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "limits": {"type": "object", "additionalProperties": {"type": "number"}},
            "self": {CYCLE_KEY: "Node"},
        },
    }
    fields = _flatten(schema)
    assert (None, "tags[]") in fields
    assert (None, "limits.{key}") in fields
    assert not any(path.startswith("self") for _, path in fields)


def test_examples_follow_the_variant_condition():
    schema = {
        "type": "object",
        "properties": {
            "accounts": {
                "type": "array",
                "items": {
                    "discriminator": {"propertyName": "kind"},
                    "oneOf": [
                        {
                            "x-schema-name": "Loan",
                            "properties": {"kind": {"enum": ["LOAN"]}, "name": {"type": "string"}},
                        },
                        {
                            "x-schema-name": "Card",
                            "properties": {"kind": {"enum": ["CARD"]}, "name": {"type": "string"}},
                        },
                    ],
                },
            }
        },
    }
    example = {"accounts": [{"kind": "CARD", "name": "Visa"}, {"kind": "LOAN", "name": "Mortgage"}]}
    fields = _flatten(schema, (example,))
    assert fields[("Loan", "accounts[].name")].example == "Mortgage"
    assert fields[("Card", "accounts[].name")].example == "Visa"


def test_required_needs_every_ancestor_required():
    schema = {
        "type": "object",
        "required": ["outer"],
        "properties": {
            "outer": {"type": "object", "properties": {"inner": {"type": "string"}}, "required": ["inner"]},
            "loose": {"type": "object", "properties": {"inner": {"type": "string"}}, "required": ["inner"]},
        },
    }
    fields = _flatten(schema)
    assert fields[(None, "outer.inner")].required
    assert not fields[(None, "loose.inner")].required


def test_arrays_of_arrays_get_one_segment_per_level():
    schema = {
        "type": "object",
        "properties": {"matrix": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}},
    }
    fields = _flatten(schema)
    node = fields[(None, "matrix[].[]")]
    assert node.array_depth == 2 and node.name == "matrix"


def test_deprecated_and_unicode_names():
    schema = {"type": "object", "properties": {"montantDébit": {"type": "number", "deprecated": True}}}
    node = _flatten(schema)[(None, "montantDébit")]
    assert node.deprecated
