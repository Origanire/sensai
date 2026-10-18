from src.core.auto_memory import AutoMemory
from src.core.memory import init_memory, load_facts
from src.core.guardrails import load_guardrails
from tests.fakes import FakeClient


def model(quote,topic='favorite_game'):
    return FakeClient(json_answers=[{'remember':True,'topic':topic,'quote':quote}])


def test_learn_deduplicate_correct_and_reload(tmp_path):
    path=tmp_path/'memory.db';db=init_memory(path);guard=load_guardrails();worker=AutoMemory()
    text='Mon jeu préféré est Apex Legends.'
    assert worker.observe(db,'v1',text,model(text),guard,now=0)
    assert not worker.observe(db,'v1',text,model(text),guard,now=11)
    correction='Mon jeu préféré est maintenant Stardew Valley.'
    assert worker.observe(db,'v1',correction,model(correction),guard,now=22)
    assert 'Stardew Valley' in str(load_facts(db,'v1'))
    assert 'Apex' not in str(load_facts(db,'v1'))
    assert not load_facts(db,'v2')
    db.close();db=init_memory(path)
    assert 'Stardew Valley' in str(load_facts(db,'v1'));db.close()


def test_sensitive_quotes_questions_commands_do_not_reach_model():
    db=init_memory(':memory:');client=FakeClient();guard=load_guardrails()
    for text in ['Mon jeu préféré est Apex, mon email est x@test.fr',
                 'Mon jeu préféré est Apex, je suis malade et mon diagnostic est privé',
                 'Paul a dit mon jeu préféré est Apex', '!remember Paul mon jeu préféré est Apex',
                 'Mon jeu préféré est quoi ?', 'Il dit « mon jeu préféré est Apex »']:
        assert not AutoMemory().observe(db,'v1',text,client,guard)
    assert not client.requests;assert not load_facts(db,'v1');db.close()


def test_model_cannot_store_invented_quote_or_unapproved_topic():
    db=init_memory(':memory:');guard=load_guardrails();text='Mon jeu préféré est Apex.'
    assert not AutoMemory().observe(db,'v1',text,model('Mon jeu préféré est Minecraft.'),guard)
    assert not AutoMemory().observe(db,'v1',text,model(text,'address'),guard)
    assert not AutoMemory().observe(db,'v1',text,FakeClient(json_answers=[{'remember':False}]),guard)
    assert not load_facts(db,'v1');db.close()


def test_global_extraction_budget():
    db=init_memory(':memory:');guard=load_guardrails();worker=AutoMemory();text='Je main Wraith sur Apex.'
    assert worker.observe(db,'v1',text,model(text,'main_character'),guard,now=0)
    client=model(text,'main_character')
    assert not worker.observe(db,'v2',text,client,guard,now=2)
    assert not client.requests;db.close()


def test_smart_apostrophe_and_wrong_model_topic_cannot_overwrite_game():
    db=init_memory(':memory:');guard=load_guardrails()
    for text in ['Mon jeu préféré est Stardew Valley.', 'Je main Wraith.', 'J’aime les jeux coopératifs.']:
        assert AutoMemory().observe(db,'v1',text,model(text),guard)
    facts=load_facts(db,'v1')
    assert len(facts)==3
    assert 'Stardew' in str(facts) and 'Wraith' in str(facts) and 'coopératifs' in str(facts)
    db.close()
