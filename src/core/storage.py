## @file storage.py
# @brief Stockage et lecture des chunks embeddés dans une base SQLite locale.

import sqlite3
import json


## @brief Ouvre (ou crée) la base SQLite contenant les chunks.
#
# Crée la table "chunks" si elle n'existe pas encore.
#
# @param path Chemin du fichier de base de données.
# @return Connexion SQLite ouverte.
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


## @brief Enregistre des chunks embeddés pour une source donnée.
#
# @param conn Connexion SQLite ouverte.
# @param source Nom du fichier source.
# @param embedded_chunks Liste de dicts {"text", "embedding"}.
def save_chunks(conn, source, embedded_chunks):
    cursor = conn.cursor()

    for item in embedded_chunks:
        embedding_json = json.dumps(item["embedding"])

        cursor.execute(
            "INSERT INTO chunks (source, text, embedding) VALUES (?, ?, ?)",
            (source, item["text"], embedding_json)
        )

    conn.commit()


## @brief Charge l'ensemble des chunks stockés en base.
#
# @param conn Connexion SQLite ouverte.
# @return Liste de dicts {"id", "source", "text", "embedding"}.
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


## @brief Compte le nombre total de chunks stockés.
#
# @param conn Connexion SQLite ouverte.
# @return Nombre de chunks en base.
def count_chunks(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM chunks")
    return cursor.fetchone()[0]