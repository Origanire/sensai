from unittest.mock import Mock, patch
import pytest

from src.agents.chat_agent import match_trigger, respond, respond_to_voice, ViewerState
from src.core.chat_text import fit_chat_text, PING_REPLY
from src.core.chat_context import RecentChat
from src.core.bot_settings import bot_persona, DEFAULTS, channel_settings
from src.tools.live_audio import voice_request, LiveAudio, put_latest
from tests.test_agents import make_ctx
from tests.fakes import FakeClient


@pytest.mark.parametrize('text', ['@LumiTheBoat', '@LUMITHEBOAT !?', '@lumitheboat @LumiTheBoat'])
def test_empty_ping_is_deterministic(text):
    ctx = make_ctx(FakeClient())
    try:
        question = match_trigger(text, '@lumitheboat')
        assert question == ''
        assert respond(ctx, 'v1', ViewerState([], [], None, 'Kevin'), question) == PING_REPLY
        assert ctx['client'].requests == []
    finally:
        ctx['db'].close(); ctx['chunks'].close()


def test_mentions_do_not_match_longer_names_or_damage_commands():
    assert match_trigger('@LumiTheBoatExtra salut', '@lumitheboat') is None
    assert match_trigger('@LumiTheBoat !search qui ?', '@lumitheboat') == '!search qui ?'


@pytest.mark.parametrize('link', ['https://example.org/x', 'http://example.org', 'www.example.org', 'example.org/x', '[ici](https://example.org)', '<https://example.org>'])
def test_no_hyperlinks_even_if_model_ignores_prompt(link):
    answer = fit_chat_text('Une réponse utile. ' + link)
    assert 'example.org' not in answer
    assert answer.startswith('Une réponse utile.')


def test_channel_change_does_not_carry_context_and_restores_it(tmp_path):
    (tmp_path/'config').mkdir()
    old = {**DEFAULTS, 'channel':'firsttv', 'stream_topic':'Nine Sols', 'stream_context':'Premier streamer'}
    changed = channel_settings(old, {'channel':'secondtv','stream_topic':'Nine Sols','stream_context':'Premier streamer'}, tmp_path)
    assert changed['stream_topic'] == changed['stream_context'] == ''
    second = {**old, **changed, 'stream_topic':'Apex'}
    restored = channel_settings(second, {'channel':'firsttv'}, tmp_path)
    assert restored['stream_topic'] == 'Nine Sols'
    assert restored['stream_context'] == 'Premier streamer'
    assert 'firsttv' in bot_persona('Lumi', old)


def test_global_faq_not_used_for_channel_specific_question():
    ctx = make_ctx(FakeClient(json_answers=[{'route':'docs'}], texts=['Je ne connais pas son planning.']))
    ctx['channel'] = 'othertv'
    try:
        with patch('src.agents.chat_agent.ask_documents') as docs:
            reply = respond(ctx, 'v1', ViewerState([],[],None,'Kevin'), 'son planning ?')
        docs.assert_not_called()
        assert 'planning' in reply
    finally:
        ctx['db'].close(); ctx['chunks'].close()


def test_voice_wake_word_is_required_and_has_word_boundaries():
    assert voice_request('Quel jeu joue-t-on ?') is None
    assert voice_request('Une lumière arrive') is None
    assert voice_request('Dis Lumi, quel jeu joue-t-on ?') == 'quel jeu joue-t-on'
    assert voice_request('Lumi !') == ''
    assert voice_request('Lumie, peux-tu aider le chat ?') == 'peux-tu aider le chat'
    assert voice_request('Loumi, salut') == 'salut'


def test_voice_is_temporary_not_viewer_memory_and_cannot_execute_commands():
    client = FakeClient(json_answers=[{'route':'chat'}],texts=['On joue à Apex. https://example.org'])
    ctx = make_ctx(client)
    ctx.update(recent_chat=RecentChat(), stream_topic='Apex')
    chat = Mock(); chat.can_reply.return_value=True; chat.post.return_value=True
    try:
        respond_to_voice(ctx, chat, 'On joue à Apex', 'Lumi')
        assert client.requests == []
        respond_to_voice(ctx, chat, 'Lumi, quel jeu ?', 'Lumi')
        assert chat.post.call_args.args[0] == 'On joue à Apex.'
        assert ctx['db'].execute('SELECT COUNT(*) FROM viewer_messages').fetchone()[0] == 0
        ctx.pop('last_voice_reply')
        count=len(client.requests)
        respond_to_voice(ctx, chat, 'Lumi !remember Paul secret', 'Lumi')
        assert len(client.requests) == count
    finally:
        ctx['db'].close(); ctx['chunks'].close()


def test_audio_queue_discards_old_generation_and_stale_transcripts():
    import time
    audio=LiveAudio('example', Mock()); audio.process=Mock()
    put_latest(audio.inbox, (Mock(), {'text':'ancien processus', 'at':time.time()}))
    put_latest(audio.inbox, (audio.process, {'text':'trop vieux', 'at':time.time()-60}))
    put_latest(audio.inbox, (audio.process, {'text':'actuel', 'at':time.time()}))
    assert audio.poll() == 'actuel'
    assert audio.poll() is None


def test_audio_stop_kills_owned_process_group():
    audio=LiveAudio('example', Mock()); process=Mock(pid=12345); audio.process=process
    with patch('os.killpg') as kill:
        audio.stop()
    kill.assert_called_once()
    process.wait.assert_called_once()
    assert audio.process is None
