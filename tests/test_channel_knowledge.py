import pytest
from src.core.channel_knowledge import load_faq, save_faq, load_profile, save_profile, faq_prompt, memory_status
from src.core.memory import init_memory, remember_viewer, save_message, save_fact
from src.agents.chat_agent import load_viewer, build_prompt


def test_questionnaire_and_faq_survive_reopening_and_stay_per_channel(tmp_path):
    a={'channel':'firsttv','bot_name':'Lumi'}; b={'channel':'secondtv','bot_name':'Lumi'}
    load_faq(a,tmp_path)
    save_profile(a,{'presentation':'Je suis Alex.', 'schedule':'Le mardi à 20 h, Europe/Paris.'},tmp_path)
    save_faq(a,'Quelle est la règle ?\nPas de spoilers.',tmp_path)
    assert load_profile(a,tmp_path)['presentation']=='Je suis Alex.'
    prompt=faq_prompt(a,tmp_path)
    assert 'Alex' in prompt and 'mardi' in prompt and 'Pas de spoilers' in prompt
    assert 'Alex' not in faq_prompt(b,tmp_path)
    assert load_profile(b,tmp_path)=={}
    assert 'non renseigné' in load_faq(b,tmp_path).lower()


def test_invalid_profile_rejected(tmp_path):
    for value in [{'unknown':'x'}, {'rules':['x']}, {'rules':'x'*701}]:
        with pytest.raises(ValueError):save_profile({'channel':'firsttv'},value,tmp_path)


def test_viewer_memory_reloaded_after_restart(tmp_path):
    path=tmp_path/'data/channels/firsttv/viewers.db';path.parent.mkdir(parents=True)
    db=init_memory(path);remember_viewer(db,'123','viewer','Viewer')
    save_message(db,'123','user','Mon jeu préféré est Stardew Valley.')
    save_message(db,'123','assistant','Je retiens Stardew Valley.')
    save_fact(db,'123','Aime les jeux coopératifs.');db.close()
    db=init_memory(path)
    try:
        state=load_viewer(db,'123','NouveauPseudo')
        prompt=build_prompt(state,'{facts} {summary}','Lumi')
        assert 'Stardew Valley' in str(prompt) and 'coopératifs' in str(prompt)
        assert memory_status('firsttv',tmp_path)['messages']==2
        assert memory_status('secondtv',tmp_path)['messages']==0
    finally:db.close()
