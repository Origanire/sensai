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
    db_connection.commit()
    return db_connection

def save_message(db_connection, viewer, role, content):
    db_connection.execute(
        "INSERT INTO viewer_messages (viewer, role, content) VALUES (?, ?, ?)",
        (viewer, role, content),
    )
    db_connection.commit()

def load_history(db_connection, viewer):
    rows = db_connection.execute(
        "SELECT role, content FROM viewer_messages WHERE viewer = ? ORDER BY id",
        (viewer,),
    ).fetchall()
    return [{"role": role, "content": content} for role, content in rows]
