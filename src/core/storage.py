# Ce module stocke les passages et leurs vecteurs dans SQLite, en séparant les documents des anciens rapports de live.

import sqlite3
import json

# Cette collection regroupe les documents de la base de connaissances.
DOCUMENTS = "documents"
# Cette collection regroupe les rapports de live archivés.
STREAMS = "streams"


# Cette fonction ouvre la base des passages et crée les tables ou colonnes manquantes.
def init_db(path="sensai.db"):
    conn = sqlite3.connect(path, check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            text TEXT,
            embedding TEXT
        )
    """)

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(chunks)")}
    if "collection" not in columns:
        cursor.execute(
            f"ALTER TABLE chunks ADD COLUMN collection TEXT NOT NULL DEFAULT '{DOCUMENTS}'"
        )

    conn.commit()
    return conn


# Cette fonction remplace les passages d’une source pour éviter les doublons après une nouvelle indexation.
def save_chunks(conn, source, embedded_chunks, collection=DOCUMENTS):
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM chunks WHERE source = ? AND collection = ?",
        (source, collection),
    )

    for item in embedded_chunks:
        embedding_json = json.dumps(item["embedding"])

        cursor.execute(
            "INSERT INTO chunks (source, text, embedding, collection) VALUES (?, ?, ?, ?)",
            (source, item["text"], embedding_json, collection)
        )

    conn.commit()


# Cette fonction charge les passages enregistrés, avec un filtre de collection si nécessaire.
def load_all_chunks(conn, collection=None):
    cursor = conn.cursor()
    if collection is None:
        cursor.execute("SELECT id, source, text, embedding, collection FROM chunks")
    else:
        cursor.execute(
            "SELECT id, source, text, embedding, collection FROM chunks "
            "WHERE collection = ?",
            (collection,),
        )
    rows = cursor.fetchall()

    chunks = []
    for row in rows:
        chunk_id, source, text, embedding_json, chunk_collection = row
        chunks.append({
            "id": chunk_id,
            "source": source,
            "text": text,
            "embedding": json.loads(embedding_json),
            "collection": chunk_collection,
        })

    return chunks


# Cette fonction compte les passages enregistrés dans la collection choisie.
def count_chunks(conn, collection=None):
    cursor = conn.cursor()
    if collection is None:
        cursor.execute("SELECT COUNT(*) FROM chunks")
    else:
        cursor.execute("SELECT COUNT(*) FROM chunks WHERE collection = ?", (collection,))
    return cursor.fetchone()[0]


# Cette fonction liste les fichiers sources et leur nombre de passages.
def list_sources(conn, collection=DOCUMENTS):
    return conn.execute(
        "SELECT source, COUNT(*) FROM chunks WHERE collection = ? "
        "GROUP BY source ORDER BY source",
        (collection,),
    ).fetchall()
