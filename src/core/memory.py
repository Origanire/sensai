## @file memory.py
# @brief Mémoire persistante des viewers : identité, historique, profil,
# résumés et statistiques, dans une base SQLite locale.

import sqlite3

## @brief Tables issues du schéma antérieur, indexé sur le pseudo de login.
LEGACY_TABLES = ("viewer_messages", "viewer_facts", "viewer_summaries")

## @brief Colonnes de statistiques ajoutées à la table viewers.
VIEWER_STATS_COLUMNS = (
    ("first_seen", "INTEGER"),
    ("last_seen", "INTEGER"),
    ("visits", "INTEGER NOT NULL DEFAULT 0"),
    ("message_count", "INTEGER NOT NULL DEFAULT 0"),
    ("active_seconds", "INTEGER NOT NULL DEFAULT 0"),
)


## @brief Met de côté les tables de l'ancien schéma.
#
# Les anciennes tables étaient indexées sur le pseudo de login, qu'un viewer
# peut changer. Elles sont renommées en *_v1 plutôt que supprimées : rien
# n'est perdu, et les nouvelles tables se créent proprement à côté.
#
# @param db_connection Connexion SQLite ouverte.
def rename_legacy_tables(db_connection):
    for table in LEGACY_TABLES:
        columns = {
            row[1] for row in db_connection.execute(f"PRAGMA table_info({table})")
        }
        if columns and "viewer_id" not in columns:
            db_connection.execute(f"ALTER TABLE {table} RENAME TO {table}_v1")
    db_connection.commit()


## @brief Ajoute une colonne si elle n'existe pas déjà.
#
# CREATE TABLE IF NOT EXISTS ne modifie jamais une table existante : sans
# cette migration, une base créée avant l'ajout resterait incomplète.
# L'opération est idempotente.
#
# @param db_connection Connexion SQLite ouverte.
# @param table Nom de la table.
# @param column Nom de la colonne.
# @param definition Type et contraintes SQL de la colonne.
def add_missing_column(db_connection, table, column, definition):
    columns = {
        row[1] for row in db_connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        db_connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


## @brief Ouvre la base et met le schéma à jour.
#
# @param path Chemin du fichier SQLite.
# @return Connexion SQLite ouverte.
def init_memory(path="sensai.db"):
    db_connection = sqlite3.connect(path)
    rename_legacy_tables(db_connection)

    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS viewers (
            viewer_id TEXT PRIMARY KEY,
            login TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
    """)
    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS viewer_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0
        )
    """)
    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS viewer_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer_id TEXT NOT NULL,
            fact TEXT NOT NULL
        )
    """)
    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS viewer_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer_id TEXT NOT NULL,
            summary TEXT NOT NULL
        )
    """)

    for column, definition in VIEWER_STATS_COLUMNS:
        add_missing_column(db_connection, "viewers", column, definition)

    db_connection.commit()
    return db_connection


## @brief Enregistre ou met à jour l'identité d'un viewer.
#
# La clé est l'identifiant Twitch, qui ne change jamais. Le login et le
# pseudo d'affichage sont rafraîchis à chaque passage : un viewer qui se
# renomme garde donc toute sa mémoire.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @param login Pseudo de connexion, en minuscules.
# @param display_name Pseudo tel qu'affiché dans le chat.
def remember_viewer(db_connection, viewer_id, login, display_name):
    db_connection.execute(
        "INSERT INTO viewers (viewer_id, login, display_name) VALUES (?, ?, ?) "
        "ON CONFLICT(viewer_id) DO UPDATE SET "
        "login = excluded.login, display_name = excluded.display_name",
        (viewer_id, login, display_name),
    )
    db_connection.commit()


## @brief Ajoute un message à l'historique d'un viewer.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @param role "user" ou "assistant".
# @param content Texte du message.
def save_message(db_connection, viewer_id, role, content):
    db_connection.execute(
        "INSERT INTO viewer_messages (viewer_id, role, content) VALUES (?, ?, ?)",
        (viewer_id, role, content),
    )
    db_connection.commit()


## @brief Charge l'historique actif d'un viewer.
#
# Les messages archivés sont exclus : ils sont déjà couverts par le résumé.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @return Liste de dicts "role"/"content", au format attendu par Ollama.
def load_history(db_connection, viewer_id):
    rows = db_connection.execute(
        "SELECT role, content FROM viewer_messages "
        "WHERE viewer_id = ? AND archived = 0 ORDER BY id",
        (viewer_id,),
    ).fetchall()
    return [{"role": role, "content": content} for role, content in rows]


## @brief Ajoute un fait au profil d'un viewer.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @param fact Fait à retenir.
def save_fact(db_connection, viewer_id, fact):
    db_connection.execute(
        "INSERT INTO viewer_facts (viewer_id, fact) VALUES (?, ?)",
        (viewer_id, fact),
    )
    db_connection.commit()


## @brief Charge les faits connus sur un viewer.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @return Liste de faits, du plus ancien au plus récent.
def load_facts(db_connection, viewer_id):
    rows = db_connection.execute(
        "SELECT fact FROM viewer_facts WHERE viewer_id = ? ORDER BY id",
        (viewer_id,),
    ).fetchall()
    return [fact for (fact,) in rows]


## @brief Enregistre un résumé et archive les messages qu'il couvre.
#
# L'archivage se fait côté SQL, sur les N plus anciens messages encore
# actifs : le code Python n'a donc pas à transporter les identifiants de
# lignes dans l'historique envoyé au modèle.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @param summary Texte du résumé.
# @param archived_count Nombre de messages couverts par ce résumé.
def save_summary(db_connection, viewer_id, summary, archived_count):
    db_connection.execute(
        "INSERT INTO viewer_summaries (viewer_id, summary) VALUES (?, ?)",
        (viewer_id, summary),
    )
    db_connection.execute(
        "UPDATE viewer_messages SET archived = 1 WHERE id IN ("
        "  SELECT id FROM viewer_messages"
        "  WHERE viewer_id = ? AND archived = 0"
        "  ORDER BY id LIMIT ?"
        ")",
        (viewer_id, archived_count),
    )
    db_connection.commit()


## @brief Charge le dernier résumé connu d'un viewer.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @return Texte du résumé, ou None si le viewer n'en a pas encore.
def load_summary(db_connection, viewer_id):
    row = db_connection.execute(
        "SELECT summary FROM viewer_summaries WHERE viewer_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (viewer_id,),
    ).fetchone()
    return row[0] if row else None


## @brief Retrouve l'identifiant d'un viewer à partir de son pseudo.
#
# @param db_connection Connexion SQLite ouverte.
# @param login Pseudo recherché, casse indifférente.
# @return Identifiant Twitch, ou None si ce viewer n'a jamais écrit.
def find_viewer_id(db_connection, login):
    row = db_connection.execute(
        "SELECT viewer_id FROM viewers WHERE LOWER(login) = LOWER(?)",
        (login,),
    ).fetchone()
    return row[0] if row else None


## @brief Ajoute l'activité d'une session aux totaux d'un viewer.
#
# Appelée une seule fois par viewer, à la fermeture de l'agent : les
# compteurs sont tenus en mémoire pendant le stream pour éviter une
# écriture disque à chaque message.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @param first_seen Horodatage de son premier message de la session.
# @param last_seen Horodatage de son dernier message de la session.
# @param message_count Nombre de messages écrits pendant la session.
def add_activity(db_connection, viewer_id, first_seen, last_seen, message_count):
    db_connection.execute(
        "UPDATE viewers SET "
        "first_seen = COALESCE(first_seen, ?), "
        "last_seen = ?, "
        "visits = visits + 1, "
        "message_count = message_count + ?, "
        "active_seconds = active_seconds + ? "
        "WHERE viewer_id = ?",
        (first_seen, last_seen, message_count, last_seen - first_seen, viewer_id),
    )
    db_connection.commit()


## @brief Charge les statistiques cumulées d'un viewer.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @return Dict "visits", "message_count", "active_seconds", "first_seen",
#         ou None si le viewer est inconnu.
def load_stats(db_connection, viewer_id):
    row = db_connection.execute(
        "SELECT visits, message_count, active_seconds, first_seen "
        "FROM viewers WHERE viewer_id = ?",
        (viewer_id,),
    ).fetchone()
    if row is None:
        return None

    visits, message_count, active_seconds, first_seen = row
    return {
        "visits": visits,
        "message_count": message_count,
        "active_seconds": active_seconds,
        "first_seen": first_seen,
    }
