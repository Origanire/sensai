## @file strategy.py
# @brief Recommandations stratégiques basées sur l'historique des streams :
# archivage des comptes-rendus, ingestion RAG et génération de conseils.

import json
import os
import shutil
from datetime import datetime

from src.core.ingestion import chunk_text, embed_chunks
from src.core.storage import save_chunks
from src.core.search import search
from src.tools.report import render_report


## @brief Requête utilisée pour retrouver les passages utiles de l'historique.
STRATEGY_QUERY = "stratégie performance stream catégories viewers moments forts"


## @brief Archive le compte-rendu du stream actuel sous un nom horodaté.
#
# @param current_path Chemin du compte-rendu du stream en cours.
# @param archive_dir Dossier d'archivage des comptes-rendus passés.
# @return Chemin du fichier archivé, ou None si aucun compte-rendu n'existait.
def archive_current_report(current_path="stream_report.json", archive_dir="reports"):
    os.makedirs(archive_dir, exist_ok=True)

    if not os.path.exists(current_path):
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    archive_path = os.path.join(archive_dir, f"stream_report_{timestamp}.json")
    shutil.copy(current_path, archive_path)
    return archive_path


## @brief Ingère tous les comptes-rendus archivés dans la base vectorielle.
#
# Chaque compte-rendu est rendu en Markdown, découpé en chunks, embeddé
# puis sauvegardé avec le nom du fichier comme source.
#
# @param client Client Ollama utilisé pour les embeddings.
# @param conn Connexion SQLite où stocker les chunks.
# @param archive_dir Dossier contenant les comptes-rendus archivés.
# @return Dict {nom_de_fichier: nombre_de_chunks}.
def ingest_past_reports(client, conn, archive_dir="reports"):
    results = {}

    if os.path.isdir(archive_dir):
        filenames = sorted(f for f in os.listdir(archive_dir) if f.endswith(".json"))
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

        # Le rendu Markdown garde les titres de section, utiles au modèle
        text = render_report(report)
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        embedded = embed_chunks(chunks, client)
        save_chunks(conn, source=filename, embedded_chunks=embedded)

        results[filename] = len(embedded)
        print(f"[Ingestion stratégie] {filename} -> {len(embedded)} chunks")

    return results


## @brief Génère des recommandations stratégiques à partir des streams passés.
#
# Récupère les passages les plus pertinents de l'historique, puis demande au
# modèle des recommandations fondées uniquement sur ce contexte.
#
# @param client Client Ollama (embedding de la requête + chat).
# @param conn Connexion SQLite contenant les chunks des streams passés.
# @param top_k Nombre de chunks injectés dans le contexte.
# @return Recommandations du modèle, ou un message si l'historique est vide.
def generate_strategy_recommendations(client, conn, top_k=5):
    results = search(STRATEGY_QUERY, client, conn, top_k=top_k)

    if not results:
        return ("Aucun historique de stream disponible. Archive d'abord au moins un "
                "stream (archive_current_report) puis ingère-le (ingest_past_reports).")

    # Chaque extrait est précédé de son fichier source pour distinguer les streams
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
