"""Channel value contracts stay authoritative across inference, review and execution."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_mapper.api.workspace import FileRole, RunState, Workspace
from api_mapper.loaders.documentation import read_documentation
from api_mapper.models import ApiSpec, Endpoint, FieldNode, SpecKind
from api_mapper.models.purpose import ContextClue
from api_mapper.normalize.enum_contract import enum_contract
from api_mapper.normalize.flattener import flatten_spec
from api_mapper.transforms.apply import TransformError, apply_transforms
from api_mapper.transforms.editor import parse_steps
from api_mapper.transforms.enum_normalization import validate_enum_outputs
from api_mapper.transforms.inference import TypeFitter
from api_mapper.validation.checks import check_document


def target(**kwargs):
    return FieldNode('channel', 'GET /orders', 'status', 'string', **kwargs)


def steps(mapping, **params):
    return parse_steps([{'kind': 'enum-map', 'params': {'mapping': mapping, **params}}])


def test_documented_contract_has_citations_and_explicit_aliases():
    node = target(documentation=(ContextClue('Allowed values: PROCESSING, COMPLETED, FAILED. Aliases: "in progress" -> "PROCESSING".', 'orders.md, line 2'),))
    contract = enum_contract(node)
    assert contract.values == ('PROCESSING', 'COMPLETED', 'FAILED')
    assert contract.aliases == {'in progress': 'PROCESSING'}
    assert contract.origin == 'documentation'
    assert contract.citations == ('orders.md, line 2',)
    assert check_document({'status': 'invented'}, [node])


def test_specification_wins_over_conflicting_documentation():
    node = target(enum=('OPEN', 'CLOSED'), description='Allowed values: OPEN, PENDING. "waiting" -> "PENDING".')
    contract = enum_contract(node)
    assert contract.values == ('OPEN', 'CLOSED')
    assert not contract.aliases
    assert len(contract.warnings) == 2


def test_conflicting_documents_and_aliases_are_not_combined():
    clues = (ContextClue('Allowed values: OPEN, CLOSED. "x" -> "OPEN".', 'one.md'),
             ContextClue('Allowed values: OPEN, PENDING. "x" -> "CLOSED".', 'two.md'))
    contract = enum_contract(target(documentation=clues))
    assert contract.values == ()
    assert contract.aliases == {}
    assert len(contract.warnings) == 2


def test_value_definitions_are_bound_to_the_documented_endpoint():
    api = ApiSpec('channel', 'Channel', '1', SpecKind.OPENAPI_3, 'test', endpoints=tuple(
        Endpoint('GET', path, path, response_schema={'type': 'object', 'properties': {'status': {'type': 'string'}}})
        for path in ('/orders', '/shipments')))
    documentation = read_documentation('guide.md', b'GET /orders\nstatus: Allowed values: PROCESSING, COMPLETED.\nstatus: "in progress" -> "PROCESSING".\nGET /shipments\nstatus: Allowed values: IN_TRANSIT, DELIVERED.')
    fields = flatten_spec(replace(api, documentation=documentation))
    contracts = {node.endpoint: enum_contract(node) for node in fields}
    assert contracts['GET /orders'].aliases == {'in progress': 'PROCESSING'}
    assert contracts['GET /shipments'].values == ('IN_TRANSIT', 'DELIVERED')
    assert not contracts['GET /shipments'].aliases


def test_ordinary_prose_is_not_an_enum_declaration():
    assert not enum_contract(target(description='Allowed values: depend on the provider and may change.')).values


@pytest.mark.parametrize('mode,value', [('exact', 'in progress'), ('trim-case', '  IN PROGRESS  '), ('trim-case-separators', ' In__Progress ')])
def test_string_normalization_preserves_canonical_output(mode, value):
    conversion = steps({'in progress': 'PROCESSING'}, normalization=mode)
    assert apply_transforms(conversion, value) == 'PROCESSING'
    with pytest.raises(TransformError):
        apply_transforms(conversion, 'not in progress')


def test_ambiguous_normalized_keys_cannot_be_saved():
    with pytest.raises(ValueError, match='ambiguous'):
        steps({'in-progress': 'OPEN', 'IN_PROGRESS': 'CLOSED'}, normalization='trim-case-separators')
    assert apply_transforms(steps({'A': 'OPEN', 'a': 'CLOSED'}), 'A') == 'OPEN'


def test_unknown_fallback_is_explicit_and_must_be_allowed():
    conversion = steps({'ready': 'OPEN'}, fallback='UNKNOWN')
    node = target(enum=('OPEN', 'UNKNOWN'))
    validate_enum_outputs(conversion, node)
    assert apply_transforms(conversion, 'new provider code') == 'UNKNOWN'
    assert apply_transforms(conversion, None) is None
    with pytest.raises(TransformError, match='expects a string'):
        apply_transforms(conversion, 42)
    with pytest.raises(ValueError, match='allowed outputs'):
        validate_enum_outputs(conversion, replace(node, enum=('OPEN',)))
    with pytest.raises(ValueError, match='requires an allowed'):
        validate_enum_outputs(conversion, target())


def test_documented_alias_is_inferred_without_inventing_a_value(lexicon):
    node = target(enum=('PROCESSING', 'COMPLETED'), description='"under way" -> "PROCESSING".')
    source = FieldNode('provider', 'GET /orders', 'status', 'string', observed=('under way', 'unexpected'))
    fit = TypeFitter(lexicon).fit(node, source, False)
    assert fit.enum_mapping.mapping['under way'] == 'PROCESSING'
    assert fit.enum_mapping.unmapped == ('unexpected',)
    assert apply_transforms(fit.steps, 'under way') == 'PROCESSING'
    with pytest.raises(TransformError):
        apply_transforms(fit.steps, 'unexpected')


def test_unbounded_source_has_a_guarded_conversion_even_without_samples(lexicon):
    fit = TypeFitter(lexicon).fit(target(enum=('OPEN', 'CLOSED')), FieldNode('provider', 'GET /orders', 'status', 'string'), False)
    assert fit.steps[0].params['open_source']
    assert apply_transforms(fit.steps, 'OPEN') == 'OPEN'
    with pytest.raises(TransformError):
        apply_transforms(fit.steps, 'UNRECOGNIZED')


def test_downstream_documentation_can_supply_channel_translations(lexicon):
    node = target(enum=('PROCESSING', 'COMPLETED'))
    source = FieldNode('provider', 'GET /orders', 'status', 'string', enum=('Q1', 'D2'),
                       documentation=(ContextClue('"Q1" -> "PROCESSING"; "D2" -> "COMPLETED".', 'provider.md'),))
    fit = TypeFitter(lexicon).fit(node, source, False)
    assert apply_transforms(fit.steps, 'Q1') == 'PROCESSING'
    assert apply_transforms(fit.steps, 'D2') == 'COMPLETED'
    assert 'provider.md' in fit.steps[-1].params['citations']


def test_conflicting_upstream_and_downstream_aliases_remain_unresolved(lexicon):
    node = target(enum=('OPEN', 'CLOSED'), description='"x" -> "OPEN".')
    source = FieldNode('provider', 'GET /orders', 'status', 'string', example='x', description='"x" -> "CLOSED".')
    fit = TypeFitter(lexicon).fit(node, source, False)
    assert fit.enum_mapping.unmapped == ('x',)
    assert fit.steps[-1].params['translation_warnings']
    with pytest.raises(TransformError):
        apply_transforms(fit.steps, 'x')


def test_conflicting_aliases_do_not_fall_back_to_an_exact_name_match(lexicon):
    node = target(enum=('OPEN', 'CLOSED'), description='"OPEN" -> "OPEN"; "OPEN" -> "CLOSED".')
    source = FieldNode('provider', 'GET /orders', 'status', 'string', enum=('OPEN',))
    fit = TypeFitter(lexicon).fit(node, source, False)
    assert fit.enum_mapping.unmapped == ('OPEN',)
    with pytest.raises(TransformError):
        apply_transforms(fit.steps, 'OPEN')


def test_api_save_preview_and_reload_preserve_the_channel_contract(tmp_path, monkeypatch):
    from api_mapper.api import app as module

    workspace = Workspace(tmp_path)
    for role, name, field in [(FileRole.UPSTREAM, 'channel', {'type': 'string', 'enum': ['PROCESSING', 'COMPLETED', 'UNKNOWN']}),
                              (FileRole.DOWNSTREAM, 'provider', {'type': 'string', 'example': 'in progress'})]:
        schema = {'type': 'object', 'properties': {'status': field}}
        spec = {'openapi': '3.0.3', 'info': {'title': name, 'version': '1'}, 'paths': {'/orders': {'get': {'responses': {'200': {'description': 'OK', 'content': {'application/json': {'schema': schema}}}}}}}}
        workspace.add_file(role, f'{name}.json', json.dumps(spec).encode())
    state = RunState('enums')
    workspace._run(state)
    assert not state.error
    monkeypatch.setattr(module, 'workspace', workspace)
    target_key = next(iter(workspace.result.prepared.targets))
    source_key = next(iter(workspace.result.prepared.sources))
    conversion = [{'kind': 'enum-map', 'params': {'mapping': {'in progress': 'PROCESSING'}, 'normalization': 'trim-case-separators', 'fallback': 'UNKNOWN'}}]
    body = {'target_key': target_key, 'source_key': source_key, 'transforms': conversion, 'action': 'choose'}
    with TestClient(module.app) as client:
        response = client.post('/api/conversion-preview', json={**body, 'sample': '  IN_PROGRESS '})
        assert response.status_code == 200
        assert response.json()['output'] == 'PROCESSING'
        assert response.json()['issues'] == []
        saved = client.post('/api/overrides', json=body)
        assert saved.status_code == 200
        assert saved.json()['mapping']['target']['enum_contract']['origin'] == 'specification'
        bad = {**body, 'transforms': [{'kind': 'enum-map', 'params': {'mapping': {'x': 'INVENTED'}}}]}
        assert client.post('/api/overrides', json=bad).status_code == 400
        assert client.post('/api/conversion-preview', json={**bad, 'sample': 'x'}).status_code == 400
    restored = Workspace(tmp_path)
    restored._run(RunState('reload'))
    chosen = restored.result.run.mappings[0].chosen
    assert apply_transforms(chosen.transforms, 'IN-PROGRESS') == 'PROCESSING'
    spec_path = Path(next(file.path for file in restored.files if file.role == FileRole.UPSTREAM))
    changed_spec = json.loads(spec_path.read_text())
    changed_spec['paths']['/orders']['get']['responses']['200']['content']['application/json']['schema']['properties']['status']['enum'] = ['CANCELLED']
    spec_path.write_text(json.dumps(changed_spec))
    changed = Workspace(tmp_path)
    changed._run(RunState('changed-contract'))
    assert changed.result.run.mappings[0].status.value != 'manual'
    assert any('override' in warning and 'ignored' in warning for warning in changed.result.run.warnings)
