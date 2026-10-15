"""Local dashboard boundaries; no Twitch or model network calls."""
import json
from unittest.mock import Mock, patch

import pytest

from src.core.bot_settings import load_bot_settings, save_bot_settings, validate_settings, bot_persona
from src.core.bot_runtime import acquire_bot_lock, bot_is_running
from src.dashboard import BotController, DashboardError, create_app
from src.agents.chat_agent import ChatOutput
from src.tools.twitch_chat import messages


@pytest.fixture
def controller(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/chat_agent.yaml').write_text('channel: exampletv\ntrigger: "@examplebot"\nbot_name: ExampleBot\ncommand_prefix: "!"\n')
    (tmp_path / 'config.yaml').write_text('model: llama3.2\nollama_url: http://localhost:11434\n')
    (tmp_path / '.env').write_text('TWITCH_CLIENT_ID=test-client\nTWITCH_BOT_USERNAME=examplebot\nTWITCH_OAUTH_TOKEN=private-test-token\n')
    return BotController(tmp_path)


@pytest.fixture
def api(controller):
    app = create_app(controller)
    app.testing = True
    return app.test_client(), {'X-CSRF-Token': app.config['DASHBOARD_CSRF']}


@pytest.mark.parametrize('values', [None, [], {'reply_cooldown': True}, {'reply_cooldown': -1}, {'reply_cooldown': 121}, {'channel': 'https://twitch.tv/name'}, {'stream_context': 'x'*3001}, {'mentions_only': 'false'}, {'TWITCH_OAUTH_TOKEN': 'secret'}, {'tone': 'unknown'}])
def test_invalid_settings(values):
    with pytest.raises(ValueError):
        validate_settings(values)


def test_settings_persist_without_rewriting_base(controller):
    original = (controller.root / 'config/chat_agent.yaml').read_text()
    controller.save({'channel': '#OtherTV', 'reply_cooldown': 30, 'stream_context': 'Partie coopérative'})
    loaded = load_bot_settings(controller.root)
    assert loaded['channel'] == 'othertv'
    assert loaded['reply_cooldown'] == 30
    assert loaded['command_prefix'] == '!'
    assert (controller.root / 'config/chat_agent.yaml').read_text() == original
    assert 'Partie coopérative' in bot_persona('Tu es {bot_name}. Règles initiales.', loaded)
    controller.phase = 'running'
    with pytest.raises(DashboardError):
        controller.save({'channel': 'thirdtv'})
    controller.save({'reply_cooldown': 10})


def test_local_api_protection_and_no_credentials(api):
    client, headers = api
    assert client.get('/api/state').status_code == 403
    assert client.get('/api/state', headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/settings', json={}, headers={**headers, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.get('/', headers={'Host': 'evil.example'}).status_code == 400
    response = client.get('/api/state', headers=headers)
    assert response.status_code == 200
    assert 'private-test-token' not in response.text
    assert 'TWITCH_OAUTH_TOKEN' not in response.text
    assert 'frame-ancestors' in response.headers['Content-Security-Policy']
    assert client.post('/api/settings', json={'reply_cooldown': 35}, headers=headers).json['settings']['reply_cooldown'] == 35
    assert client.post('/api/settings', json={'reply_cooldown': 'no'}, headers=headers).status_code == 400


def test_process_lock_prevents_duplicate_bot(controller):
    with acquire_bot_lock(controller.root / '.bot.lock'):
        assert bot_is_running(controller.root / '.bot.lock')
        with pytest.raises(DashboardError):
            controller.start()
        with pytest.raises(DashboardError):
            controller.begin_auth()
    assert not bot_is_running(controller.root / '.bot.lock')


def test_cooldown_counts_only_successful_posts():
    chat = ChatOutput(Mock(), 'exampletv', True, cooldown=15)
    with patch('src.agents.chat_agent.send_message') as send, patch('src.agents.chat_agent.time.monotonic', return_value=100):
        assert chat.post('first')
        assert not chat.post('too soon')
        assert send.call_count == 1
    with patch('src.agents.chat_agent.send_message', side_effect=OSError('offline')), patch('src.agents.chat_agent.time.monotonic', return_value=115):
        assert not chat.post('fails')
        assert chat.last_post_at == 100
    with patch('src.agents.chat_agent.send_message'), patch('src.agents.chat_agent.time.monotonic', return_value=116):
        assert chat.post('next')


def test_metrics_measure_observed_activity(controller):
    controller.active_channel = 'exampletv'
    controller.consume({'kind': 'connected', 'at': 100})
    for viewer in ('1', '1', '2'):
        controller.consume({'kind': 'message', 'viewer': viewer})
    controller.consume({'kind': 'reply', 'latency': 2})
    controller.consume({'kind': 'reply', 'latency': 4})
    controller.consume({'kind': 'cooldown'})
    with patch('src.dashboard.time.time', return_value=160):
        result = controller.metrics_snapshot()
    assert result['received_per_minute'] == 3
    assert result['viewers'] == 2
    assert result['median_latency'] == 3
    assert result['cooldown_skipped'] == 1


def test_private_preview_has_no_persistence(controller):
    before = sorted(str(p) for p in controller.root.rglob('*'))
    with patch('src.dashboard.OllamaClient') as client:
        client.return_value.chat_silent.return_value = 'Bienvenue sur le live !'
        result = controller.preview({'message': 'Salut', 'settings': {'stream_topic': 'Coopération'}})
        prompt = client.return_value.chat_silent.call_args.args[0]
        assert 'Coopération' in prompt[0]['content']
    assert result['reply'] == 'Bienvenue sur le live !'
    assert before == sorted(str(p) for p in controller.root.rglob('*'))
    assert controller.metrics['replies'] == 0


def test_exports_actual_report(api, controller):
    client, headers = api
    assert client.post('/api/export', json={'format': 'md'}, headers=headers).status_code == 409
    (controller.root / 'stream_report.json').write_text(json.dumps({'resume': '<script>sample</script>'}))
    response = client.post('/api/export', json={'format': 'json'}, headers=headers)
    assert response.json['resume'] == '<script>sample</script>'
    response = client.post('/api/export', json={'format': 'html'}, headers=headers)
    assert '<script>' not in response.text
    assert '&lt;script&gt;' in response.text
    assert client.post('/api/export', json={'format': '../env'}, headers=headers).status_code == 400


def test_connection_only_ready_after_join():
    sock = Mock()
    sock.recv.side_effect = [b':tmi.twitch.tv 001 examplebot :Welcome\r\n', b':examplebot!examplebot JOIN #exampletv\r\n:user!user PRIVMSG #exampletv :hello\r\n', b'']
    ready = Mock()
    incoming = messages(sock, on_ready=ready)
    assert next(incoming)['text'] == 'hello'
    with pytest.raises(ConnectionError):
        next(incoming)
    ready.assert_called_once_with()


def test_credentials_reload_after_reconnection(controller, monkeypatch):
    monkeypatch.setenv('TWITCH_OAUTH_TOKEN', 'stale-token')
    assert controller.credentials()['TWITCH_OAUTH_TOKEN'] == 'private-test-token'


def test_refresh_checks_identity_before_saving(controller):
    from src.tools import twitch_auth as auth
    before = (controller.root / '.env').read_text()
    with patch.object(auth, 'request_json', return_value=(200, {'access_token': 'new', 'refresh_token': 'new-refresh'})), patch.object(auth, 'validate_token', side_effect=auth.AuthError('Wrong account')):
        with pytest.raises(auth.AuthError):
            auth.refresh_authorization('app', 'bot', 'refresh', controller.root / '.env')
    assert (controller.root / '.env').read_text() == before
    identity = {'login': 'examplebot', 'expires_in': 3600}
    with patch.object(auth, 'request_json', return_value=(200, {'access_token': 'new', 'refresh_token': 'refresh/+=%'})), patch.object(auth, 'validate_token', return_value=identity):
        assert auth.refresh_authorization('app', 'bot', 'refresh', controller.root / '.env') == identity
    assert controller.credentials()['TWITCH_OAUTH_TOKEN'] == 'new'


def test_device_callback_exposes_only_user_code(controller):
    from src.tools import twitch_auth as auth
    replies = [(200, {'device_code': 'private-device', 'user_code': 'PUBLIC', 'expires_in': 600}), (400, {'message': 'access_denied'})]
    callback = Mock()
    with patch.object(auth, 'request_json', side_effect=replies), patch.object(auth.time, 'sleep'):
        with pytest.raises(auth.AuthError):
            auth.authorize('app', 'bot', controller.root / '.env', on_device=callback)
    callback.assert_called_once_with({'user_code': 'PUBLIC', 'expires_in': 600})


def test_pdf_export_returns_real_pdf(api, controller, tmp_path, monkeypatch):
    import src.core.export as export
    monkeypatch.setattr(export, 'EXPORT_DIR', tmp_path / 'exports')
    (controller.root / 'stream_report.json').write_text(json.dumps({'resume': 'Session de démonstration.'}))
    client, headers = api
    response = client.post('/api/export', json={'format': 'pdf'}, headers=headers)
    assert response.status_code == 200
    assert response.data.startswith(b'%PDF-')
    assert 'attachment' in response.headers['Content-Disposition']


def test_dashboard_preview_uses_research_without_posting(controller):
    from tests.fakes import FakeClient
    from src.tools.web_search import SEARCH_UNAVAILABLE
    client = FakeClient(texts=['query'])
    with patch('src.dashboard.OllamaClient', return_value=client), patch('src.tools.web_search.web_search', return_value=[]):
        result = controller.preview({'message': 'cherche sur internet le dernier patch'})
    assert result['route'] == 'web'
    assert result['reply'] == SEARCH_UNAVAILABLE
    assert controller.metrics['replies'] == 0
    assert not (controller.root / 'sensai.db').exists()
