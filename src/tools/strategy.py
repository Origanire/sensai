# Ce module archive les rapports de live et les utilise pour proposer des conseils au streamer.

import json
import os
import shutil
from datetime import datetime

from src.core.ingestion import chunk_text, embed_chunks
from src.core.storage import STREAMS, save_chunks
from src.core.search import search
from src.tools.report import render_report


# Cette question sert à retrouver les passages utiles dans les anciens rapports.
STRATEGY_QUERY = "stratégie performance stream catégories viewers moments forts"


# Cette fonction archive le rapport actuel avec un nom daté, s’il existe.
def archive_current_report(current_path="stream_report.json", archive_dir="reports"):
    os.makedirs(archive_dir, exist_ok=True)

    if not os.path.exists(current_path):
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    archive_path = os.path.join(archive_dir, f"stream_report_{timestamp}.json")
    shutil.copy(current_path, archive_path)
    return archive_path


# Cette fonction découpe et indexe les rapports archivés en conservant leur fichier comme source.
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

        # Le format Markdown garde les titres des sections pour aider le modèle à comprendre les passages.
        text = render_report(report)
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        embedded = embed_chunks(chunks, client)
        save_chunks(conn, source=filename, embedded_chunks=embedded, collection=STREAMS)

        results[filename] = len(embedded)
        print(f"[Ingestion stratégie] {filename} -> {len(embedded)} chunks")

    return results


# Cette fonction retrouve les passages utiles des anciens lives et demande des conseils fondés sur ce contexte.
def generate_strategy_recommendations(client, conn, top_k=5):
    results = search(STRATEGY_QUERY, client, conn, top_k=top_k, collection=STREAMS)

    if not results:
        return ("Aucun historique de stream disponible. Termine d'abord au moins un "
                "stream avec /stream end.")

    # On ajoute le nom du fichier devant chaque extrait pour distinguer les lives.
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


# Cette fonction archive et indexe le rapport du live terminé, puis prépare le prochain rapport.
def end_stream(client, conn, current_path="stream_report.json", archive_dir="reports"):
    archive_path = archive_current_report(current_path, archive_dir)
    if archive_path is None:
        return None

    ingest_past_reports(client, conn, archive_dir)
    os.remove(current_path)
    return archive_path
