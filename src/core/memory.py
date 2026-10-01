import sqlite3


def init_memory(path="sensai.db"):
    db_connection = sqlite3.connect(path)
    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS viewer_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS viewer_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer TEXT NOT NULL,
            fact TEXT NOT NULL
        )
    """)

    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS viewer_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer TEXT NOT NULL,
            summary TEXT NOT NULL
        )
    """)

    add_missing_column(
        db_connection, "viewer_messages", "archived", "INTEGER NOT NULL DEFAULT 0"
    )

    db_connection.commit()
    return db_connection


def add_missing_column(db_connection, table, column, definition):
    columns = {row[1] for row in db_connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db_connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def save_message(db_connection, viewer, role, content):
    db_connection.execute(
        "INSERT INTO viewer_messages (viewer, role, content) VALUES (?, ?, ?)",
        (viewer, role, content),
    )
    db_connection.commit()


def load_history(db_connection, viewer):
    rows = db_connection.execute(
        "SELECT role, content FROM viewer_messages "
        "WHERE viewer = ? AND archived = 0 ORDER BY id",
        (viewer,),
    ).fetchall()
    return [{"role": role, "content": content} for role, content in rows]


def save_fact(db_connection, viewer, fact):
    db_connection.execute(
        "INSERT INTO viewer_facts (viewer, fact) VALUES (?, ?)",
        (viewer, fact),
    )
    db_connection.commit()


def load_facts(db_connection, viewer):
    rows = db_connection.execute(
        "SELECT fact FROM viewer_facts WHERE viewer = ? ORDER BY id",
        (viewer,),
    ).fetchall()
    return [fact for (fact,) in rows]


def save_summary(db_connection, viewer, summary, archived_count):
    db_connection.execute(
        "INSERT INTO viewer_summaries (viewer, summary) VALUES (?, ?)",
        (viewer, summary),
    )
    db_connection.execute(
        "UPDATE viewer_messages SET archived = 1 WHERE id IN ("
        "  SELECT id FROM viewer_messages"
        "  WHERE viewer = ? AND archived = 0"
        "  ORDER BY id LIMIT ?"
        ")",
        (viewer, archived_count),
    )
    db_connection.commit()


def load_summary(db_connection, viewer):
    row = db_connection.execute(
        "SELECT summary FROM viewer_summaries WHERE viewer = ? ORDER BY id DESC LIMIT 1",
        (viewer,),
    ).fetchone()
    return row[0] if row else None
