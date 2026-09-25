import sqlite3
import json


def init_db(path="sensai.db"):
    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            text TEXT,
            embedding TEXT
        )
    """)

    conn.commit()
    return conn
