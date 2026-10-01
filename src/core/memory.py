import sqlite3

LEGACY_TABLES = ("viewer_messages", "viewer_facts", "viewer_summaries")

VIEWER_STATS_COLUMNS = (
    ("first_seen", "INTEGER"),
    ("last_seen", "INTEGER"),
    ("visits", "INTEGER NOT NULL DEFAULT 0"),
    ("message_count", "INTEGER NOT NULL DEFAULT 0"),
    ("active_seconds", "INTEGER NOT NULL DEFAULT 0"),
)


def rename_legacy_tables(db_connection):
    for table in LEGACY_TABLES:
        columns = {
            row[1] for row in db_connection.execute(f"PRAGMA table_info({table})")
        }
        if columns and "viewer_id" not in columns:
            db_connection.execute(f"ALTER TABLE {table} RENAME TO {table}_v1")
    db_connection.commit()


def add_missing_column(db_connection, table, column, definition):
    columns = {
        row[1] for row in db_connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        db_connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


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


def remember_viewer(db_connection, viewer_id, login, display_name):
    db_connection.execute(
        "INSERT INTO viewers (viewer_id, login, display_name) VALUES (?, ?, ?) "
        "ON CONFLICT(viewer_id) DO UPDATE SET "
        "login = excluded.login, display_name = excluded.display_name",
        (viewer_id, login, display_name),
    )
    db_connection.commit()


def save_message(db_connection, viewer_id, role, content):
    db_connection.execute(
        "INSERT INTO viewer_messages (viewer_id, role, content) VALUES (?, ?, ?)",
        (viewer_id, role, content),
    )
    db_connection.commit()


def load_history(db_connection, viewer_id):
    rows = db_connection.execute(
        "SELECT role, content FROM viewer_messages "
        "WHERE viewer_id = ? AND archived = 0 ORDER BY id",
        (viewer_id,),
    ).fetchall()
    return [{"role": role, "content": content} for role, content in rows]


def save_fact(db_connection, viewer_id, fact):
    db_connection.execute(
        "INSERT INTO viewer_facts (viewer_id, fact) VALUES (?, ?)",
        (viewer_id, fact),
    )
    db_connection.commit()


def load_facts(db_connection, viewer_id):
    rows = db_connection.execute(
        "SELECT fact FROM viewer_facts WHERE viewer_id = ? ORDER BY id",
        (viewer_id,),
    ).fetchall()
    return [fact for (fact,) in rows]


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


def load_summary(db_connection, viewer_id):
    row = db_connection.execute(
        "SELECT summary FROM viewer_summaries WHERE viewer_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (viewer_id,),
    ).fetchone()
    return row[0] if row else None


def find_viewer_id(db_connection, login):
    row = db_connection.execute(
        "SELECT viewer_id FROM viewers WHERE LOWER(login) = LOWER(?)",
        (login,),
    ).fetchone()
    return row[0] if row else None


def record_activity(db_connection, viewer_id, seen_at, session_gap):
    row = db_connection.execute(
        "SELECT last_seen, visits, message_count, active_seconds "
        "FROM viewers WHERE viewer_id = ?",
        (viewer_id,),
    ).fetchone()
    if row is None:
        return None

    last_seen, visits, message_count, active_seconds = row

    if last_seen is None or seen_at - last_seen > session_gap:
        visits += 1
    elif seen_at > last_seen:
        active_seconds += seen_at - last_seen

    message_count += 1

    db_connection.execute(
        "UPDATE viewers SET first_seen = COALESCE(first_seen, ?), last_seen = ?, "
        "visits = ?, message_count = ?, active_seconds = ? WHERE viewer_id = ?",
        (seen_at, seen_at, visits, message_count, active_seconds, viewer_id),
    )
    db_connection.commit()

    return {
        "visits": visits,
        "message_count": message_count,
        "active_seconds": active_seconds,
    }


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
