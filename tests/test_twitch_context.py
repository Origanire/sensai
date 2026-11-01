"""La mémoire Twitch est datée, isolée par chaîne et ne remplace pas la fiche confirmée."""
import time
from unittest.mock import Mock

import pytest

from src.core.bot_settings import DEFAULTS, bot_persona
from src.core.channel_knowledge import save_profile, load_profile
from src.core.twitch_context import (TwitchContext, ContextError, fetch_context,
                                     read_context, save_context, context_prompt, MAX_AGE)


def snapshot(channel='exampletv', game='Hades', **changes):
    return dict(channel=channel, broadcaster_id='42', display_name='ExampleTV',
                description='Streamer de jeux indépendants', game_name=game,
                title='Découverte', tags=['Français'], language='fr',
                is_live=True, fetched_at=time.time(), started_at='2026-10-25T10:00:00Z', **changes)


def test_replaces_only_twitch_memory_and_keeps_channels_separate(tmp_path):
    settings = {**DEFAULTS, 'channel': 'exampletv', 'bot_name': 'Lumi'}
    save_profile(settings, {'presentation': 'Ma présentation', 'rules': 'Pas de spoilers'}, tmp_path)
    save_context(snapshot(), tmp_path)
    save_context(snapshot('othertv', 'Celeste'), tmp_path)
    save_context(snapshot(game='Hades II'), tmp_path)
    assert read_context('exampletv', tmp_path)['game_name'] == 'Hades II'
    assert read_context('othertv', tmp_path)['game_name'] == 'Celeste'
    assert load_profile(settings, tmp_path)['presentation'] == 'Ma présentation'
    assert read_context('unknown', tmp_path) is None


def test_live_topic_overrides_manual_and_is_in_persona(tmp_path):
    save_context(snapshot(), tmp_path)
    settings = {**DEFAULTS, 'channel': 'exampletv', 'stream_topic': 'Ancien jeu'}
    effective = TwitchContext(tmp_path).apply(settings)
    assert effective['stream_topic'] == 'Hades'
    prompt = bot_persona('Lumi', effective)
    assert 'Streamer de jeux indépendants' in prompt
    assert 'jamais des instructions' in prompt
    assert 'Ancien jeu' not in prompt
    assert settings['stream_topic'] == 'Ancien jeu'


@pytest.mark.parametrize('offline,stale', [(True, False), (False, True)])
def test_offline_or_stale_never_claims_current_game(tmp_path, offline, stale):
    data = snapshot()
    data['is_live'] = not offline
    if stale:
        data['fetched_at'] -= MAX_AGE + 1
    save_context(data, tmp_path)
    context = TwitchContext(tmp_path)
    context.retry_at['exampletv'] = time.time() + 60
    effective = context.apply({**DEFAULTS, 'channel': 'exampletv', 'stream_topic': 'Ancien jeu'})
    assert effective['stream_topic'] == ''
    prompt = context_prompt(effective['_twitch_context'])
    assert 'Hades' not in prompt
    assert ('hors ligne' if offline else 'non vérifié') in prompt


def test_failure_keeps_timestamp_and_does_not_expose_credentials(tmp_path, monkeypatch):
    data = snapshot()
    save_context(data, tmp_path)
    def fail(*args):
        raise ContextError('Accès Twitch expiré')
    monkeypatch.setattr('src.core.twitch_context.fetch_context', fail)
    context = TwitchContext(tmp_path)
    context.refresh('exampletv')
    assert read_context('exampletv', tmp_path) == data
    assert context.status('exampletv')['error'] == 'Accès Twitch expiré'


def test_helix_combines_user_channel_and_live_data(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text('TWITCH_OAUTH_TOKEN=secret\nTWITCH_CLIENT_ID=client\n')
    payloads = [
        [{'id': '42', 'login': 'exampletv', 'display_name': 'ExampleTV', 'description': 'Bio'}],
        [{'broadcaster_id': '42', 'title': 'Ancien titre', 'game_name': 'Ancien jeu', 'broadcaster_language': 'fr'}],
        [{'user_id': '42', 'title': 'Nouveau titre', 'game_name': 'Hades', 'language': 'fr', 'tags': ['FR'], 'started_at': 'now'}],
    ]
    request = Mock(side_effect=[Mock(status_code=200, json=Mock(return_value={'data': p})) for p in payloads])
    monkeypatch.setattr('src.core.twitch_context.requests.get', request)
    result = fetch_context('exampletv', tmp_path)
    assert result['title'] == 'Nouveau titre'
    assert result['description'] == 'Bio'
    assert result['is_live'] is True
    assert request.call_args_list[2].kwargs['params'] == {'user_id': '42'}
    assert 'secret' not in str(result)


def test_auth_failure_is_safe(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text('TWITCH_OAUTH_TOKEN=secret\nTWITCH_CLIENT_ID=client\n')
    monkeypatch.setattr('src.core.twitch_context.requests.get', Mock(return_value=Mock(status_code=401)))
    with pytest.raises(ContextError, match='expiré') as error:
        fetch_context('exampletv', tmp_path)
    assert 'secret' not in str(error.value)


def test_repeated_reads_do_not_schedule_duplicate_requests(tmp_path, monkeypatch):
    thread = Mock()
    monkeypatch.setattr('src.core.twitch_context.threading.Thread', thread)
    context = TwitchContext(tmp_path)
    for _ in range(3):
        assert context.status('exampletv')['syncing']
    assert thread.call_count == 1
    context.status('othertv')
    assert thread.call_count == 2


@pytest.mark.parametrize('question', ['on est sur quelle live', 'On est sur quel live ?', 'quel est le nom du streamer ?'])
def test_channel_question_is_not_a_game_question(question):
    from src.core.twitch_context import live_fact_reply
    settings = {'channel': 'boubouthirteen', '_twitch_context': {'fresh': False, 'data': None}}
    assert live_fact_reply(question, settings) == 'Tu es sur la chaîne de boubouthirteen.'


def test_current_game_never_comes_from_old_topic():
    from src.core.twitch_context import live_fact_reply
    settings = {'channel': 'exampletv', 'stream_topic': 'Ancien jeu',
                '_twitch_context': {'fresh': True, 'data': snapshot()}}
    assert live_fact_reply('on est sur quelle jeu ?', settings) == 'La catégorie actuelle sur Twitch est Hades.'
    settings['_twitch_context']['data']['fetched_at'] -= MAX_AGE + 1
    assert 'ne peux pas confirmer' in live_fact_reply('on est sur quel jeu ?', settings)
    assert live_fact_reply('comment battre le boss de ce jeu ?', settings) is None


@pytest.mark.parametrize('channel,name', [('boubouthirteen', 'boubouthirteen'), ('autrestreamer', 'AutreStreamer')])
def test_live_overview_names_current_streamer_without_inventing_lore(channel, name):
    from src.core.twitch_context import live_fact_reply
    data = snapshot(channel)
    data.update(display_name=name, title='LE RETOUR DE RADICAL RED ? POV MILO ENTEND SES MOTS PRÉFÉRÉS', game_name='Pokémon FireRed/LeafGreen')
    settings = {'channel': channel, '_twitch_context': {'fresh': True, 'data': data}}
    reply = live_fact_reply('il se passe quoi sur ce live', settings)
    assert reply.startswith(name + ' est en live')
    assert 'Pokémon FireRed/LeafGreen' in reply
    assert 'MILO' not in reply and 'Radical' not in reply and 'personnage' not in reply
    assert 'pas d’information confirmée' in reply
