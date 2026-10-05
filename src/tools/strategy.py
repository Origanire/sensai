## @file strategy.py
# @brief Strategic recommendations based on stream history: report
# archiving, RAG ingestion and advice generation.

import json
import os
import shutil
from datetime import datetime

from src.core.ingestion import chunk_text, embed_chunks
from src.core.storage import STREAMS, save_chunks
from src.core.search import search
from src.tools.report import render_report


## @brief Query used to retrieve the useful passages of the history.
STRATEGY_QUERY = "stratégie performance stream catégories viewers moments forts"


## @brief Archive the current stream's report under a timestamped name.
#
# @param current_path Path of the report of the ongoing stream.
# @param archive_dir Directory where past reports are archived.
# @return Path of the archived file, or None if no report existed.
def archive_current_report(current_path="stream_report.json", archive_dir="reports"):
    os.makedirs(archive_dir, exist_ok=True)

    if not os.path.exists(current_path):
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    archive_path = os.path.join(archive_dir, f"stream_report_{timestamp}.json")
    shutil.copy(current_path, archive_path)
    return archive_path


## @brief Ingest every archived report into the vector database.
#
# Each report is rendered to Markdown, split into chunks, embedded,
# then saved with the file name as the source.
#
# @param client Ollama client used for the embeddings.
# @param conn SQLite connection where to store the chunks.
# @param archive_dir Directory holding the archived reports.
# @return Dict {filename: number_of_chunks}.
def ingest_past_reports(client, conn, archive_dir="reports"):
    results = {}

    if os.path.isdir(archive_dir):
        filenames = sorted(
            f for f in os.listdir(archive_dir)
            if f.startswith("stream_report_") and f.endswith(".json")
        )
    else:
        filenames = []

    if not filenames:
        print("[Ingestion stratégie] Aucun stream archivé pour le moment.")
        return results

    for filename in filenames:
        full_path = os.path.join(archive_dir, filename)

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[Erreur] Impossible de lire {filename} : {e}")
            continue

        # The Markdown rendering keeps the section titles, useful to the model
        text = render_report(report)
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        embedded = embed_chunks(chunks, client)
        save_chunks(conn, source=filename, embedded_chunks=embedded, collection=STREAMS)

        results[filename] = len(embedded)
        print(f"[Ingestion stratégie] {filename} -> {len(embedded)} chunks")

    return results


## @brief Generate strategic recommendations from past streams.
#
# Retrieves the most relevant passages of the history, then asks the
# model for recommendations based only on that context.
#
# @param client Ollama client (query embedding + chat).
# @param conn SQLite connection holding the chunks of past streams.
# @param top_k Number of chunks injected into the context.
# @return The model's recommendations, or a message if the history is empty.
def generate_strategy_recommendations(client, conn, top_k=5):
    results = search(STRATEGY_QUERY, client, conn, top_k=top_k, collection=STREAMS)

    if not results:
        return ("Aucun historique de stream disponible. Termine d'abord au moins un "
                "stream avec /stream end.")

    # Each excerpt is preceded by its source file to tell the streams apart
    context = "\n\n".join(
        f"[Source : {chunk['source']}]\n{chunk['text']}" for score, chunk in results
    )

    prompt = f"""Tu es un conseiller en stratégie pour un streamer Twitch.
Voici des extraits des comptes-rendus de ses streams précédents :

{context}

En te basant UNIQUEMENT sur ces extraits, propose 3 à 5 recommandations
stratégiques concrètes et actionnables pour son prochain stream : quels moments
ont bien marché, quelles catégories ou jeux semblent engager les viewers, ce
qu'il faut refaire ou éviter.

Règles :
- Chaque recommandation doit s'appuyer sur un fait précis tiré des extraits
  (cite le jeu, le moment ou le chiffre concerné).
- Aucun conseil générique ni supposition qui ne figure pas dans les extraits.
- Si les extraits ne suffisent pas pour une recommandation, ne l'invente pas.
- Réponds en français, sous forme de liste à puces."""

    messages = [{"role": "user", "content": prompt}]
    return client.chat(messages)


## @brief Close the current stream: archive its report and index it.
#
# The archived report joins the "streams" collection, where the strategy
# advice looks for it; the current report is then reset for the next
# stream. Nothing happens if no report was started.
#
# @param client Ollama client used for the embeddings.
# @param conn SQLite connection where to store the chunks.
# @param current_path Path of the report of the ongoing stream.
# @param archive_dir Directory where past reports are archived.
# @return Path of the archived report, or None if there was none.
def end_stream(client, conn, current_path="stream_report.json", archive_dir="reports"):
    archive_path = archive_current_report(current_path, archive_dir)
    if archive_path is None:
        return None

    ingest_past_reports(client, conn, archive_dir)
    os.remove(current_path)
    return archive_path
