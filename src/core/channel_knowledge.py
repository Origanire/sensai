"""Ce module conserve une petite FAQ modifiable pour chaque chaîne dans SQLite, sans modèle de recherche supplémentaire."""
from pathlib import Path
import re
import sqlite3

from src.core.bot_settings import ROOT


def database_path(channel, root=ROOT):
    if not re.fullmatch(r'[a-z0-9_]{3,25}', channel):
        raise ValueError('Chaîne invalide.')
    return Path(root) / 'data/channels' / channel / 'viewers.db'


def seed_faq(settings):
    return (f"Qui est le streamer ?\nLa chaîne suivie est {settings['channel']}. "
            "Sa présentation détaillée n’est pas encore renseignée.\n\n"
            f"Qui est le bot ?\n{settings.get('bot_name', 'LumiTheBoat')} est la mascotte et l’aide du streamer, un compte séparé.\n\n"
            "Quel est le jeu du live ?\nUtilise le sujet actuel indiqué dans les réglages du dashboard. Ce sujet peut changer.\n\n"
            "Quels sont les horaires ?\nHoraires non renseignés : ne pas inventer de planning.\n\n"
            "Quel matériel utilise le streamer ?\nMatériel non renseigné.\n\n"
            "Quels sont les jeux habituels et les règles de la chaîne ?\nNon renseignés : demander au streamer.\n\n"
            "Comment parler à Lumi ?\nMentionne le bot dans le chat. Une mention seule lui fait demander ce que tu veux. "
            "La commande !search permet une recherche Internet, sans publier de lien. "
            "Si l’écoute du live est activée, le mot d’appel vocal configuré déclenche une réponse écrite.\n\n"
            "Comment fonctionne la mémoire ?\nLes échanges adressés à Lumi sont conservés par viewer et par chaîne. "
            "Le streamer et les modérateurs peuvent ajouter un fait avec !remember pseudo fait. "
            "L’essai privé du dashboard ne consulte pas cette mémoire.\n")


def load_faq(settings, root=ROOT, initialize=True):
    path = database_path(settings['channel'], root)
    if not initialize:
        if not path.exists():
            return seed_faq(settings)
        with sqlite3.connect('file:'+str(path)+'?mode=ro', uri=True) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='channel_faq'").fetchone()
            row = db.execute('SELECT content FROM channel_faq WHERE id=1').fetchone() if exists else None
        return row[0] if row else seed_faq(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS channel_faq (id INTEGER PRIMARY KEY CHECK(id=1), content TEXT NOT NULL)')
        db.execute('INSERT OR IGNORE INTO channel_faq VALUES (1, ?)', (seed_faq(settings),))
        content = db.execute('SELECT content FROM channel_faq WHERE id=1').fetchone()[0]
    return content


def save_faq(settings, content, root=ROOT):
    if not isinstance(content, str) or len(content) > 8000 or '\x00' in content:
        raise ValueError('La FAQ doit contenir au maximum 8 000 caractères.')
    load_faq(settings, root)
    with sqlite3.connect(database_path(settings['channel'], root), timeout=5) as db:
        db.execute('UPDATE channel_faq SET content=? WHERE id=1', (content.strip(),))


def faq_prompt(settings, root=ROOT):
    return ('\n\nFAQ de la chaîne ' + settings['channel'] + ' (renseignements locaux ; '
            'ne pas en déduire les informations manquantes). Le sujet et le contexte actuels du live '
            'priment sur un ancien renseignement de cette FAQ.\n' + load_faq(settings, root, initialize=False) + profile_prompt(settings, root))


def memory_status(channel, root=ROOT):
    path = database_path(channel, root)
    counts = {'viewers':0, 'messages':0, 'facts':0, 'auto_facts':0, 'summaries':0}
    if path.exists():
        with sqlite3.connect('file:'+str(path)+'?mode=ro', uri=True, timeout=5) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for key, table in [('viewers','viewers'),('messages','viewer_messages'),('facts','viewer_facts'),('summaries','viewer_summaries')]:
                if table in tables:
                    counts[key] = db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            if 'viewer_auto_facts' in tables:
                import time
                counts['auto_facts'] = db.execute('SELECT COUNT(*) FROM viewer_auto_facts WHERE updated_at>?', (time.time()-90*86400,)).fetchone()[0]
                counts['facts'] += counts['auto_facts']
    return {'enabled':True, 'channel':channel, **counts}


PROFILE_QUESTIONS = {
    'presentation': 'Comment veux-tu être présenté ? Pseudo, description et pronoms si tu le souhaites.',
    'ambiance': 'Quelle ambiance veux-tu sur ton stream ? Et quel rôle pour Lumi ?',
    'games': 'Quels jeux ou sujets proposes-tu habituellement ?',
    'schedule': 'Quels sont tes horaires habituels ? Indique aussi le fuseau horaire.',
    'rules': 'Quelles sont les règles de ton chat ?',
    'equipment': 'Quel matériel souhaites-tu présenter aux viewers ?',
    'boundaries': 'Quels sujets, blagues ou spoilers Lumi doit-il éviter ?',
    'rituals': 'Quels sont tes rituels, expressions ou animations préférées ?',
}


def load_profile(settings, root=ROOT, initialize=True):
    import json
    if not initialize:
        path = database_path(settings['channel'], root)
        if not path.exists():
            return {}
        with sqlite3.connect('file:'+str(path)+'?mode=ro', uri=True) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='streamer_profile'").fetchone()
            row = db.execute('SELECT content FROM streamer_profile WHERE id=1').fetchone() if exists else None
        return json.loads(row[0]) if row else {}
    load_faq(settings, root)
    with sqlite3.connect(database_path(settings['channel'], root), timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS streamer_profile (id INTEGER PRIMARY KEY CHECK(id=1), content TEXT NOT NULL)')
        row = db.execute('SELECT content FROM streamer_profile WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {}


def save_profile(settings, answers, root=ROOT):
    import json
    if not isinstance(answers, dict) or set(answers) - set(PROFILE_QUESTIONS):
        raise ValueError('Questionnaire invalide.')
    if any(not isinstance(value,str) or len(value)>700 or '\x00' in value for value in answers.values()):
        raise ValueError('Chaque réponse est limitée à 700 caractères.')
    answers = {key:value.strip() for key,value in answers.items()}
    load_profile(settings, root)
    with sqlite3.connect(database_path(settings['channel'], root), timeout=5) as db:
        db.execute('INSERT INTO streamer_profile VALUES(1,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content', (json.dumps(answers,ensure_ascii=False),))
    return answers


def profile_prompt(settings, root=ROOT):
    profile = load_profile(settings, root, initialize=False)
    if not any(profile.values()):
        return ''
    return '\n\nFiche confirmée par le streamer (prioritaire sur les champs non renseignés de la FAQ) :\n' + '\n'.join(
        question+'\n'+(profile.get(key) or 'Non renseigné.') for key,question in PROFILE_QUESTIONS.items())
