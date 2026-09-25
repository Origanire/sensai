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


def save_chunks(conn, source, embedded_chunks):
    cursor = conn.cursor()

    for item in embedded_chunks:
        embedding_json = json.dumps(item["embedding"])

        cursor.execute(
            "INSERT INTO chunks (source, text, embedding) VALUES (?, ?, ?)",
            (source, item["text"], embedding_json)
        )

    conn.commit()


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


def count_chunks(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM chunks")
    return cursor.fetchone()[0]