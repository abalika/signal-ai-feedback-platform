import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from server import ai
from server.main import create_app
from server.model_settings import ModelInput, test_connection as probe_connection
from scripts.check_publication import inspect_file
from scripts.package_delivery import source_allowed

KEY = 'private-settings-test-value'
PAYLOAD = {'base_url': 'https://api.example.com/v1', 'model': 'test-model', 'api_key': KEY}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for name in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_MODEL'):
        monkeypatch.delenv(name, raising=False)
    app = create_app(tmp_path / 'app.db', offline=True, connection_tester=lambda _: 7)
    client = TestClient(app)
    headers = {'X-Signal-Settings-Token': client.get('/api/model-settings').json()['csrf_token']}
    return app, client, headers


def enable(client, headers, payload=None):
    payload = {**PAYLOAD, **(payload or {})}
    response = client.post('/api/model-settings/test', json=payload, headers=headers)
    assert response.status_code == 200
    return client.put('/api/model-settings', json={**payload, 'verification_token': response.json()['verification_token']}, headers=headers)


def test_test_then_enable_without_restart_and_without_returning_key(setup):
    app, client, headers = setup
    assert client.get('/api/health').json()['demo_mode']
    response = enable(client, headers)
    assert response.status_code == 200
    assert response.json()['mode'] == 'live' and response.json()['has_key']
    assert KEY not in response.text + client.get('/api/model-settings').text
    assert 'api_key' not in response.json()
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/api/health').json() == {'status': 'ok', 'ai_configured': True}
    assert app.state.model_config.current().api_key == KEY
    assert not app.state.model_config.path.exists()


def test_only_successful_unchanged_test_allows_activation(setup):
    _, client, headers = setup
    assert client.put('/api/model-settings', json=PAYLOAD, headers=headers).status_code == 409
    token = client.post('/api/model-settings/test', json=PAYLOAD, headers=headers).json()['verification_token']
    changed = {**PAYLOAD, 'model': 'changed', 'verification_token': token}
    assert client.put('/api/model-settings', json=changed, headers=headers).status_code == 409
    assert client.get('/api/health').json()['demo_mode']


def test_expired_proof_cannot_be_used(setup):
    app, client, headers = setup
    token = client.post('/api/model-settings/test', json=PAYLOAD, headers=headers).json()['verification_token']
    fingerprint, _ = app.state.model_config.verified[token]
    app.state.model_config.verified[token] = (fingerprint, 0)
    assert client.put('/api/model-settings', json={**PAYLOAD, 'verification_token': token}, headers=headers).status_code == 409


def test_credential_reuse_requires_unchanged_endpoint(setup):
    _, client, headers = setup
    assert enable(client, headers).status_code == 200
    blank = {**PAYLOAD, 'api_key': ''}
    assert client.post('/api/model-settings/test', json=blank, headers=headers).status_code == 200
    changed = {**blank, 'base_url': 'https://other.example.com/v1'}
    assert client.post('/api/model-settings/test', json=changed, headers=headers).status_code == 422


def test_remember_restart_force_offline_and_forget(setup):
    app, client, headers = setup
    assert enable(client, headers, {'remember': True}).status_code == 200
    path = app.state.model_config.path
    assert json.loads(path.read_text())['api_key'] == KEY
    if os.name != 'nt':
        assert path.stat().st_mode & 0o077 == 0
    restarted = TestClient(create_app(path.parent / 'app.db', offline=True, restore_saved_model=True))
    assert restarted.get('/api/health').json()['ai_configured']
    forced = TestClient(create_app(path.parent / 'app.db', offline=True))
    assert forced.get('/api/health').json()['demo_mode']
    assert client.post('/api/model-settings/offline', headers=headers).status_code == 200
    restarted = TestClient(create_app(path.parent / 'app.db', restore_saved_model=True))
    assert restarted.get('/api/health').json()['demo_mode']
    assert client.delete('/api/model-settings', headers=headers).status_code == 200
    assert not path.exists() and not client.get('/api/model-settings').json()['has_key']


def test_environment_config_stays_unchanged(setup, monkeypatch):
    _, client, headers = setup
    for name, value in [('OPENAI_API_KEY', KEY), ('OPENAI_BASE_URL', PAYLOAD['base_url']), ('OPENAI_MODEL', PAYLOAD['model'])]:
        monkeypatch.setenv(name, value)
    assert client.get('/api/model-settings').json()['source'] == 'environment'
    assert enable(client, headers, {'api_key': ''}).status_code == 200
    assert client.delete('/api/model-settings', headers=headers).status_code == 200
    assert os.environ['OPENAI_API_KEY'] == KEY
    assert client.get('/api/model-settings').json()['source'] == 'environment'
    assert client.get('/api/health').json()['demo_mode']


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://remote.example.com/v1', 'https://user:password@example.com',
                                 'https://example.com/v1?key=private', 'https://example.com/#private', 'https://example.com:bad'])
def test_invalid_or_credential_bearing_urls_are_rejected_without_input_echo(setup, url):
    _, client, headers = setup
    response = client.post('/api/model-settings/test', json={**PAYLOAD, 'base_url': url}, headers=headers)
    assert response.status_code == 422
    assert KEY not in response.text and url not in response.text
    assert 'input' not in response.text


@pytest.mark.parametrize('invalid', [{'api_key': {'secret': KEY}}, {'verification_token': KEY * 20}, {'extra_secret': KEY}])
def test_validation_does_not_echo_secrets(setup, invalid):
    _, client, headers = setup
    response = client.post('/api/model-settings/test', json={**PAYLOAD, **invalid}, headers=headers)
    assert response.status_code == 422 and KEY not in response.text
    assert response.headers['cache-control'] == 'no-store'
    if 'extra_secret' in invalid:
        response = client.post('/api/model-settings/test', json={**PAYLOAD, KEY: 'value'}, headers=headers)
        assert response.status_code == 422 and KEY not in response.text


def test_csrf_and_origin_guards(setup):
    _, client, headers = setup
    assert client.post('/api/model-settings/test', json=PAYLOAD).status_code == 403
    for origin in ['https://attacker.example.com', 'null']:
        response = client.get('/api/model-settings', headers={'Origin': origin})
        assert response.status_code == 403 and 'csrf_token' not in response.text
    assert client.get('/api/model-settings', headers={'Host': 'attacker.example.com'}).status_code == 403
    assert client.get('/api/model-settings', headers={'Origin': 'http://127.0.0.1:5173'}).status_code == 200
    assert client.post('/api/model-settings/test', json=PAYLOAD, headers={**headers, 'Origin': 'https://attacker.example.com'}).status_code == 403


def test_failed_file_write_preserves_active_configuration(setup, monkeypatch):
    app, client, headers = setup
    assert enable(client, headers).status_code == 200
    previous = app.state.model_config.current()
    def fail(*args):
        raise OSError('private path and secret')
    monkeypatch.setattr(app.state.model_config, 'write', fail)
    assert enable(client, headers, {'model': 'new', 'remember': True}).status_code == 503
    assert app.state.model_config.current() == previous


def test_corrupt_saved_configuration_does_not_break_startup(tmp_path):
    path = tmp_path / 'model-settings.json'
    path.write_text('{invalid json')
    client = TestClient(create_app(tmp_path / 'app.db', offline=True))
    assert client.get('/api/model-settings').json()['load_error']
    assert client.get('/api/health').json()['demo_mode']


def test_saved_model_files_are_not_publishable_or_packageable():
    for path in ['model-settings.json', 'server/data/model-settings.json', '.model-settings-private']:
        assert not source_allowed(path)
        assert 'excluded_local_file' in inspect_file(path, b'{}')


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def test_probe_is_one_short_request_and_does_not_log_key(monkeypatch):
    calls = []
    def transport(request, timeout):
        calls.append((json.loads(request.data), timeout))
        return Response(b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}')
    monkeypatch.setattr(ai, 'urlopen', transport)
    assert probe_connection(ai.AISettings(KEY, PAYLOAD['base_url'], 'deepseek-test')) >= 0
    assert len(calls) == 1 and calls[0][0]['max_tokens'] == 32 and calls[0][1] == 12
    assert calls[0][0]['thinking']['type'] == 'disabled'
    assert KEY not in repr(ai.AISettings(KEY, PAYLOAD['base_url'], PAYLOAD['model']))


@pytest.mark.parametrize('failure', [401, 403, 404, 429, 500, 'timeout', 'invalid'])
def test_probe_failures_are_safe_and_do_not_activate(tmp_path, monkeypatch, failure):
    calls = []
    def transport(request, timeout):
        calls.append(1)
        if isinstance(failure, int):
            raise HTTPError(request.full_url, failure, KEY, None, None)
        if failure == 'timeout': raise URLError(KEY)
        return Response(KEY.encode())
    monkeypatch.setattr(ai, 'urlopen', transport)
    client = TestClient(create_app(tmp_path / 'app.db', offline=True))
    headers = {'X-Signal-Settings-Token': client.get('/api/model-settings').json()['csrf_token']}
    response = client.post('/api/model-settings/test', json=PAYLOAD, headers=headers)
    assert response.status_code == 502 and KEY not in response.text
    assert len(calls) == 1 and client.get('/api/health').json()['demo_mode']


def test_credentials_are_not_forwarded_on_redirect():
    hits = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header('Location', '/stolen')
            self.end_headers()
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200); self.end_headers()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with pytest.raises(ai.ProviderError) as error:
            ai.OpenAICompatibleProvider().complete(system_prompt='test', user_prompt='test', settings=ai.AISettings(KEY, f'http://127.0.0.1:{server.server_port}', 'test'))
        assert error.value.code == 'http_302' and hits == ['/chat/completions']
    finally:
        server.shutdown(); server.server_close(); thread.join()


@pytest.mark.parametrize('switch_during_request', [False, True])
def test_analysis_uses_web_credentials_and_stable_mode_snapshot(tmp_path, monkeypatch, switch_during_request):
    for name in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_MODEL'):
        monkeypatch.delenv(name, raising=False)
    calls = []
    class Provider:
        def complete(self, **kwargs):
            calls.append(kwargs['settings'])
            if len(calls) == 1:
                if switch_during_request:
                    app.state.offline = True
                    app.state.ai_provider = object()
                return json.dumps({'tool': 'search_documents', 'arguments': {'query': '任务'}})
            return json.dumps({'category': 'question', 'summary': '人数限制', 'suggested_reply': '不能为零，必须是正整数。',
                               'proposed_task': '核对任务人数', 'citations': [{'document_id': 1, 'excerpt': '任务人数必须是正整数。'}]})
    app = create_app(tmp_path / 'app.db', offline=True, ai_provider=Provider(), connection_tester=lambda _: 1)
    client = TestClient(app)
    project = client.post('/api/projects', json={'name': '设置集成测试'}).json()
    client.post('/api/documents', json={'project_id': project['id'], 'title': '任务规则', 'content': '任务人数必须是正整数。'})
    feedback = client.post('/api/feedback', json={'project_id': project['id'], 'source': '固定测试', 'content': '任务人数可以为零吗？'}).json()
    headers = {'X-Signal-Settings-Token': client.get('/api/model-settings').json()['csrf_token']}
    assert enable(client, headers).status_code == 200
    result = client.post(f"/api/feedback/{feedback['id']}/analyze")
    assert result.status_code == 200 and result.json()['model_mode'] == 'ai'
    assert len(calls) == 2 and all(settings.api_key == KEY and settings.model == PAYLOAD['model'] for settings in calls)
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}")
    assert KEY not in traces.text and sum(trace['step'] == 'model' for trace in traces.json()) == 2
