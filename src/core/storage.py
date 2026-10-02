## @file storage.py
# @brief Storage and retrieval of embedded chunks in a local SQLite database.

import sqlite3
import json


## @brief Open (or create) the SQLite database holding the chunks.
#
# Creates the "chunks" table if it does not exist yet.
#
# @param path Path of the database file.
# @return Open SQLite connection.
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


## @brief Save embedded chunks for a given source.
#
# @param conn Open SQLite connection.
# @param source Name of the source file.
# @param embedded_chunks List of {"text", "embedding"} dicts.
def save_chunks(conn, source, embedded_chunks):
    cursor = conn.cursor()

    for item in embedded_chunks:
        embedding_json = json.dumps(item["embedding"])

        cursor.execute(
            "INSERT INTO chunks (source, text, embedding) VALUES (?, ?, ?)",
            (source, item["text"], embedding_json)
        )

    conn.commit()


## @brief Load every chunk stored in the database.
#
# @param conn Open SQLite connection.
# @return List of {"id", "source", "text", "embedding"} dicts.
def load_all_chunks(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, source, text, embedding FROM chunks")
    rows = cursor.fetchall()

    chunks = []
    for row in rows:
        chunk_id, source, text, embedding_json = row
        chunks.append({
            "id": chunk_id,
            "source": source,
            "text": text,
            "embedding": json.loads(embedding_json)
        })

    return chunks


## @brief Count the total number of stored chunks.
#
# @param conn Open SQLite connection.
# @return Number of chunks in the database.
def count_chunks(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM chunks")
    return cursor.fetchone()[0]