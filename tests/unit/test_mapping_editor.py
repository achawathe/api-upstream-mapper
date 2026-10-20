"""Visual edits persist independently from inference and preview actual conversions."""

import json

import pytest
from fastapi.testclient import TestClient

from api_mapper.api.workspace import FileRole, RunState, Workspace
from api_mapper.transforms.editor import parse_steps


def setup_workspace(tmp_path):
    workspace = Workspace(tmp_path)
    for role, name, kind in [(FileRole.UPSTREAM, 'output', 'integer'), (FileRole.DOWNSTREAM, 'input', 'string')]:
        field = {'type': kind, 'example': 42 if kind == 'integer' else '42'}
        schema = {'type': 'object', 'properties': {'quantity': field}}
        response = {'description': 'OK', 'content': {'application/json': {'schema': schema}}}
        spec = {'openapi': '3.0.3', 'info': {'title': name, 'version': '1'},
                'paths': {'/stock': {'get': {'responses': {'200': response}}}}}
        workspace.add_file(role, f'{name}.json', json.dumps(spec).encode())
    state = RunState('test')
    workspace._run(state)
    assert state.error is None
    return workspace


def test_edit_conversion_preview_category_and_reload(tmp_path, monkeypatch):
    from api_mapper.api import app as module
    workspace = setup_workspace(tmp_path)
    monkeypatch.setattr(module, 'workspace', workspace)
    mapping = workspace.result.run.mappings[0]
    source = next(iter(workspace.result.prepared.sources))
    body = {'target_key': mapping.target.key, 'source_key': source, 'action': 'choose', 'transforms': [{'kind': 'cast', 'params': {'to': 'integer'}}]}
    with TestClient(module.app) as client:
        preview = client.post('/api/conversion-preview', json={**body, 'sample': '42'})
        assert preview.status_code == 200
        assert preview.json()['output'] == 42
        assert preview.json()['issues'] == []
        assert client.post('/api/conversion-preview', json={**body, 'sample': 'not a number'}).status_code == 400
        assert client.post('/api/overrides', json={**body, 'transforms': [None]}).status_code == 400
        saved = client.post('/api/overrides', json=body)
        assert saved.status_code == 200
        assert saved.json()['mapping']['status'] == 'manual'
        assert saved.json()['mapping']['chosen']['transforms'][0]['params'] == {'to': 'integer'}
        response = client.put('/api/mapping-category', json={'target_key': mapping.target.key, 'category': 'Stock'})
        assert response.json()['mapping']['category'] == 'Stock'
        assert client.get('/api/report.json').json()['mappings'][0]['category'] == 'Stock'
        assert client.put('/api/mapping-category', json={'target_key': 'absent', 'category': 'Stock'}).status_code == 400
    restored = Workspace(tmp_path)
    state = RunState('reload')
    restored._run(state)
    assert state.error is None
    mapping = restored.result.run.mappings[0]
    assert mapping.category == 'Stock'
    assert mapping.chosen.transforms[0].params == {'to': 'integer'}
    restored.set_override(None, mapping.target.key)
    assert mapping.target.key in restored.categories


@pytest.mark.parametrize('steps', [[{'kind': 'exec'}], [{'kind': 'cast', 'params': {'to': 'object'}}], [{'kind': 'minor-units-to-decimal', 'params': {'exponent': 100}}], [{'kind': 'enum-map', 'params': {'mapping': {'a': 1}}}]])
def test_conversion_editor_rejects_unsupported_blocks(steps):
    with pytest.raises(ValueError):
        parse_steps(steps)


def test_date_examples_do_not_require_a_matching_field_name(lexicon):
    from api_mapper.models import FieldNode
    from api_mapper.transforms.inference import TypeFitter
    target = FieldNode('up', 'GET /x', 'created', 'string', format='date-time')
    source = FieldNode('down', 'GET /x', 'x7', 'string', example='2026-10-19T11:30:00Z')
    fit = TypeFitter(lexicon).fit(target, source, False)
    assert fit.veto is None
    assert fit.score < 0.75


def test_edited_value_map_removes_resolved_gaps():
    steps = parse_steps([{'kind': 'enum-map', 'params': {'mapping': {'ready': 'READY'}, 'unmapped': ['ready', 'pending']}}])
    assert steps[0].params['unmapped'] == ['pending']
