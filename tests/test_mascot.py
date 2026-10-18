from unittest.mock import patch, Mock
from src.agents.mascot import MascotPacer, mascot_reaction
from src.agents.router import route, explicit_search
from src.core.bot_settings import validate_settings
from src.core.guardrails import load_guardrails
from src.agents.chat_agent import ViewerState, respond
from tests.fakes import FakeClient
from tests.test_agents import make_ctx
import pytest


def test_mascot_does_not_speak_in_empty_or_single_viewer_chat():
    pacer = MascotPacer(now=0)
    assert not pacer.claim('gg',180,now=181)
    for _ in range(8):pacer.observe('one')
    assert not pacer.claim('gg',180,now=181)
    pacer.observe('two')
    assert not pacer.claim('bonjour',180,now=181)
    assert not pacer.claim('gg ?',180,now=181)
    assert not pacer.claim('gg',180,last_reply=100,now=181)
    assert pacer.claim('gg',180,now=181)
    for i in range(8):pacer.observe(str(i))
    assert not pacer.claim('gg',180,now=200)
    assert pacer.claim('gg',180,now=400)


def test_model_can_decline_and_reaction_is_bounded():
    guards=load_guardrails()
    recent=[{'viewer':'A','message':'gg'}]
    assert mascot_reaction(FakeClient(json_answers=[{'react':False,'text':'bonjour'}]),guards,'Lumi',recent) is None
    assert mascot_reaction(FakeClient(json_answers=[{'react':True,'text':'On fait un défi ?'}]),guards,'Lumi',recent) is None
    result=mascot_reaction(FakeClient(json_answers=[{'react':True,'text':'Encore un rebondissement ! '*40}]),guards,'Lumi',recent)
    assert len(result)<=180


def test_search_followup_cannot_fall_back_to_chat():
    for question in ["Qui l'as dévelloppé", "Qui l'a développé", '!search Nine Sols', 'date de sortie du jeu']:
        assert route(question,FakeClient(json_answers=[{'route':'chat'}]),topic='Nine Sols') == 'web'
    assert explicit_search('!search') == ''
    assert explicit_search('!SEARCH Nine Sols') == 'Nine Sols'
    assert explicit_search('salut') is None


def test_web_receives_topic_and_moderated_question():
    ctx=make_ctx(FakeClient());ctx['stream_topic']='Nine Sols'
    try:
        with patch('src.agents.chat_agent.ask_internet',return_value='Red Candle Games. https://example.org') as search:
            respond(ctx,'v1',ViewerState([],[],None,'Kevin'),"Qui l'a développé")
        assert search.call_args.kwargs['topic']=='Nine Sols'
        assert ctx['last_route']=='web'
    finally:
        ctx['db'].close();ctx['chunks'].close()


def test_mascot_settings_have_hard_minimum():
    assert validate_settings({'mascot_enabled':False,'mascot_interval':180})['mascot_enabled'] is False
    for settings in [{'mascot_interval':10},{'mascot_enabled':'true'},{'mascot_interval':True}]:
        with pytest.raises(ValueError):validate_settings(settings)


def test_search_command_reports_real_research_and_passes_topic():
    from src.agents.chat_agent import search_and_share
    chat=Mock()
    with patch('src.agents.chat_agent.ask_internet',return_value='Studio. https://example.org') as search, patch('src.agents.chat_agent.emit') as emit:
        search_and_share('qui a développé ce jeu ?', 'Viewer', FakeClient(), chat,
                         {'max_results':3}, {'enabled':False}, load_guardrails(), persona='Mascotte', topic='Nine Sols')
    assert search.call_args.kwargs['topic']=='Nine Sols'
    assert ('research',) in [call.args for call in emit.call_args_list]
    assert emit.call_args_list[-1].kwargs['stage']=='completed'
    assert chat.say.call_args.args[0].startswith('@Viewer ')


def test_preview_understands_mention_search_and_topic(tmp_path):
    import shutil
    from src.dashboard import BotController
    from src.core.bot_settings import ROOT
    (tmp_path/'config').mkdir()
    shutil.copyfile(ROOT/'config/chat_agent.yaml',tmp_path/'config/chat_agent.yaml')
    shutil.copyfile(ROOT/'config.yaml',tmp_path/'config.yaml')
    controller=BotController(tmp_path)
    with patch('src.dashboard.OllamaClient',return_value=FakeClient()), patch('src.dashboard.ask_internet',return_value='Trouvé. https://example.org') as search:
        result=controller.preview({'message':'@LumiTheBoat !search qui a développé ce jeu ?', 'settings':{'stream_topic':'Nine Sols'}})
    assert result['route']=='web'
    assert search.call_args.args[0]=='qui a développé ce jeu ?'
    assert search.call_args.kwargs['topic']=='Nine Sols'
