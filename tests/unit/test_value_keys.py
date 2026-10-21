"""Object keys that are data (cities, currency codes, account IDs) are read as a map, not as field names."""

import pytest

from api_mapper.loaders.sample_inference import MAP_KEYS_KEY, infer_schema
from api_mapper.models import Endpoint, FieldNode
from api_mapper.normalize.flattener import flatten_endpoint


def fields(samples):
    endpoint = Endpoint(
        method="GET", path="/x", operation_id="x", response_schema=infer_schema(samples), response_examples=samples
    )
    return {n.path: n for n in flatten_endpoint("api", endpoint)}


def test_keys_that_change_between_samples_become_a_map():
    found = fields([{"city": {"toronto": 12.5, "vancouver": 9.1}}, {"city": {"ottawa": 8.4, "calgary": 4.2}}])
    assert set(found) == {"city.@key", "city.{key}"}
    key, value = found["city.@key"], found["city.{key}"]
    assert key.observed == ("toronto", "vancouver", "ottawa", "calgary")
    assert key.is_map_key and key.map_path == "city" and key.name == "city"
    assert value.type == "number" and value.map_path == "city" and value.name == "city"


def test_value_like_keys_make_a_map_from_a_single_sample():
    sample = {"balances": {"ACC-1001": {"current": 1.0}, "ACC-2002": {"current": 2.0}, "ACC-3003": {"current": 3.0}}}
    found = fields([sample])
    assert {"balances.@key", "balances.{key}.current"} <= set(found)
    assert found["balances.{key}.current"].segments == ("balances", "current")
    assert infer_schema([{"EUR": 0.92, "CAD": 1.37, "GBP": 0.79}])[MAP_KEYS_KEY] == ["EUR", "CAD", "GBP"]


def test_fixed_field_names_stay_an_object():
    samples = [{"limits": {"daily": 500, "monthly": 2000, "yearly": 9000}}, {"limits": {"daily": 7, "monthly": 8}}]
    assert {"limits.daily", "limits.monthly", "limits.yearly"} <= set(fields(samples))


def test_optional_fields_or_mixed_values_do_not_make_a_map():
    optional = [{"a": 1, "b": 2, "c": 3, "d": 4}, {"a": 1, "b": 2, "c": 3, "e": 5}]
    mixed = [{"x": 1, "y": "two", "z": True}, {"p": 1, "q": "two", "r": False}]
    assert "properties" in infer_schema(optional)
    assert "properties" in infer_schema(mixed)


def test_declared_maps_expose_their_key():
    schema = {
        "type": "object",
        "properties": {"limits": {"type": "object", "additionalProperties": {"type": "number"}}},
    }
    endpoint = Endpoint(method="GET", path="/x", operation_id="x", response_schema=schema)
    assert {n.path for n in flatten_endpoint("api", endpoint)} == {"limits.@key", "limits.{key}"}


@pytest.mark.parametrize(
    "sample",
    [
        {"a": {}, "b": {}, "c": {}},
        {"a": {}, "b": None, "c": {}},
        {"EUR": {}, "CAD": {}, "GBP": {}},
    ],
)
def test_empty_objects_do_not_provide_enough_shape_evidence_for_a_map(sample):
    schema = infer_schema([sample])
    assert schema["type"] == "object"
    assert set(schema["properties"]) == set(sample)
    assert "additionalProperties" not in schema


def test_nested_maps_and_map_values_containing_arrays_keep_all_selections():
    node = FieldNode("down", "GET /x", "regions.{key}.cities.{key}[].temperature", "number", array_depth=1)
    assert node.map_paths == ("regions", "regions.{key}.cities")
    assert node.map_path == "regions.{key}.cities"
    assert node.segments == ("regions", "cities", "temperature")
    assert fields([{"EUR": 0.92, "CAD": 1.37, "GBP": 0.79}])["@key"].is_map_key
