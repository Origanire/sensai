## @file memory.py
# @brief Persistent memory of viewers: identity, history, profile,
# summaries and statistics, in a local SQLite database.

import sqlite3

## @brief Tables from the former schema, indexed on the login name.
LEGACY_TABLES = ("viewer_messages", "viewer_facts", "viewer_summaries")

## @brief Statistics columns added to the viewers table.
VIEWER_STATS_COLUMNS = (
    ("first_seen", "INTEGER"),
    ("last_seen", "INTEGER"),
    ("visits", "INTEGER NOT NULL DEFAULT 0"),
    ("message_count", "INTEGER NOT NULL DEFAULT 0"),
    ("active_seconds", "INTEGER NOT NULL DEFAULT 0"),
)


## @brief Set aside the tables of the old schema.
#
# The old tables were indexed on the login name, which a viewer can
# change. They are renamed to *_v1 rather than deleted: nothing is lost,
# and the new tables are created cleanly alongside.
#
# @param db_connection Open SQLite connection.
def rename_legacy_tables(db_connection):
    for table in LEGACY_TABLES:
        columns = {
            row[1] for row in db_connection.execute(f"PRAGMA table_info({table})")
        }
        if columns and "viewer_id" not in columns:
            db_connection.execute(f"ALTER TABLE {table} RENAME TO {table}_v1")
    db_connection.commit()


## @brief Add a column if it does not exist yet.
#
# CREATE TABLE IF NOT EXISTS never alters an existing table: without this
# migration, a database created before the addition would stay incomplete.
# The operation is idempotent.
#
# @param db_connection Open SQLite connection.
# @param table Name of the table.
# @param column Name of the column.
# @param definition SQL type and constraints of the column.
def add_missing_column(db_connection, table, column, definition):
    columns = {
        row[1] for row in db_connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        db_connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


## @brief Open the database and update the schema.
#
# @param path Path of the SQLite file.
# @return Open SQLite connection.
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


## @brief Store or update a viewer's identity.
#
# The key is the Twitch identifier, which never changes. The login and
# display name are refreshed on every visit: a viewer who renames
# therefore keeps their whole memory.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param login Login name, lowercase.
# @param display_name Name as displayed in the chat.
def remember_viewer(db_connection, viewer_id, login, display_name):
    db_connection.execute(
        "INSERT INTO viewers (viewer_id, login, display_name) VALUES (?, ?, ?) "
        "ON CONFLICT(viewer_id) DO UPDATE SET "
        "login = excluded.login, display_name = excluded.display_name",
        (viewer_id, login, display_name),
    )
    db_connection.commit()


## @brief Append a message to a viewer's history.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param role "user" or "assistant".
# @param content Text of the message.
def save_message(db_connection, viewer_id, role, content):
    db_connection.execute(
        "INSERT INTO viewer_messages (viewer_id, role, content) VALUES (?, ?, ?)",
        (viewer_id, role, content),
    )
    db_connection.commit()


## @brief Load a viewer's active history.
#
# Archived messages are excluded: they are already covered by the summary.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @return List of "role"/"content" dicts, in the format expected by Ollama.
def load_history(db_connection, viewer_id):
    rows = db_connection.execute(
        "SELECT role, content FROM viewer_messages "
        "WHERE viewer_id = ? AND archived = 0 ORDER BY id",
        (viewer_id,),
    ).fetchall()
    return [{"role": role, "content": content} for role, content in rows]


## @brief Add a fact to a viewer's profile.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param fact Fact to remember.
def save_fact(db_connection, viewer_id, fact):
    db_connection.execute(
        "INSERT INTO viewer_facts (viewer_id, fact) VALUES (?, ?)",
        (viewer_id, fact),
    )
    db_connection.commit()


## @brief Load the facts known about a viewer.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @return List of facts, from oldest to most recent.
def load_facts(db_connection, viewer_id):
    rows = db_connection.execute(
        "SELECT fact FROM viewer_facts WHERE viewer_id = ? ORDER BY id",
        (viewer_id,),
    ).fetchall()
    return [fact for (fact,) in rows]


## @brief Save a summary and archive the messages it covers.
#
# Archiving is done on the SQL side, on the N oldest still-active
# messages: the Python code therefore does not have to carry row
# identifiers inside the history sent to the model.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param summary Text of the summary.
# @param archived_count Number of messages covered by this summary.
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


## @brief Load the latest known summary of a viewer.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @return Text of the summary, or None if the viewer has none yet.
def load_summary(db_connection, viewer_id):
    row = db_connection.execute(
        "SELECT summary FROM viewer_summaries WHERE viewer_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (viewer_id,),
    ).fetchone()
    return row[0] if row else None


## @brief Find a viewer's identifier from their name.
#
# @param db_connection Open SQLite connection.
# @param login Name to look up, case-insensitive.
# @return Twitch identifier, or None if this viewer has never written.
def find_viewer_id(db_connection, login):
    row = db_connection.execute(
        "SELECT viewer_id FROM viewers WHERE LOWER(login) = LOWER(?)",
        (login,),
    ).fetchone()
    return row[0] if row else None


## @brief Add a session's activity to a viewer's totals.
#
# Called once per viewer, when the agent shuts down: the counters are
# held in memory during the stream to avoid a disk write on every
# message.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @param first_seen Timestamp of their first message of the session.
# @param last_seen Timestamp of their last message of the session.
# @param message_count Number of messages written during the session.
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


## @brief Load a viewer's cumulative statistics.
#
# @param db_connection Open SQLite connection.
# @param viewer_id Twitch identifier of the viewer.
# @return Dict "visits", "message_count", "active_seconds", "first_seen",
#         or None if the viewer is unknown.
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
