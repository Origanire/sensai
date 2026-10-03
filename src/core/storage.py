## @file storage.py
# @brief Storage and retrieval of embedded chunks in a local SQLite database.
#
# Chunks are grouped into collections ("documents" for the streamer's
# knowledge base, "streams" for archived stream reports), so a search on
# one never returns passages of the other.

import sqlite3
import json

## @brief Collection of the documents ingested from the knowledge folder.
DOCUMENTS = "documents"
## @brief Collection of the archived stream reports.
STREAMS = "streams"


## @brief Open (or create) the SQLite database holding the chunks.
#
# Creates the "chunks" table if it does not exist yet, and adds the
# "collection" column to a table created before it existed.
#
# @param path Path of the database file.
# @return Open SQLite connection.
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


## @brief Save embedded chunks for a given source.
#
# The chunks previously stored for the same source are replaced: ingesting
# a document twice, after editing it, never leaves duplicates.
#
# @param conn Open SQLite connection.
# @param source Name of the source file.
# @param embedded_chunks List of {"text", "embedding"} dicts.
# @param collection Collection the chunks belong to.
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


## @brief Load the chunks stored in the database.
#
# @param conn Open SQLite connection.
# @param collection Collection to load, or None for every chunk.
# @return List of {"id", "source", "text", "embedding", "collection"} dicts.
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


## @brief Count the stored chunks.
#
# @param conn Open SQLite connection.
# @param collection Collection to count, or None for every chunk.
# @return Number of chunks.
def count_chunks(conn, collection=None):
    cursor = conn.cursor()
    if collection is None:
        cursor.execute("SELECT COUNT(*) FROM chunks")
    else:
        cursor.execute("SELECT COUNT(*) FROM chunks WHERE collection = ?", (collection,))
    return cursor.fetchone()[0]


## @brief List the sources of a collection with their number of chunks.
#
# @param conn Open SQLite connection.
# @param collection Collection to describe.
# @return List of (source, number of chunks) pairs, sorted by source.
def list_sources(conn, collection=DOCUMENTS):
    return conn.execute(
        "SELECT source, COUNT(*) FROM chunks WHERE collection = ? "
        "GROUP BY source ORDER BY source",
        (collection,),
    ).fetchall()
