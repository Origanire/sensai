# Ce script compare la recherche documentaire entre plusieurs modèles de vecteurs. Il nécessite Ollama et s’utilise avec python -m tests.eval_rag.

import sys
import time

from src.core.ingestion import ingest_folder
from src.core.ollama_client import OllamaClient, load_config
from src.core.search import load_rag_settings, search
from src.core.storage import init_db, save_chunks

# Ces questions correspondent à des sections présentes dans la base.
ON_TOPIC = [
    ("c'est quoi ta carte graphique ?", "Setup PC"),
    ("quand est le prochain stream ?", "Planning"),
    ("il y a stream le jeudi ?", "Planning"),
    ("c'est quoi les règles du chat", "Règles"),
    ("quel est l'objectif de subs", "Abonnements"),
    ("tu joues à quoi en ce moment ?", "Jeu en cours"),
    ("c'est quoi ton micro ?", "Setup PC"),
]
# Ces questions ne peuvent pas être résolues avec les documents disponibles.
OFF_TOPIC = [
    "qui a gagné la coupe du monde 2022 ?",
    "recette de la pâte à crêpes",
    "salut ça va ?",
    "quelle est la capitale du Japon ?",
]


# Cette fonction mesure la qualité de recherche d’un modèle avec les réglages fournis.
def evaluate(model, settings):
    client = OllamaClient()
    client.embedding_model = model
    conn = init_db(":memory:")
    for source, chunks in ingest_folder(settings["folder"], client,
                                        settings["chunk_size"], settings["overlap"]).items():
        save_chunks(conn, source, chunks)

    start = time.time()
    hits = 0
    on_scores, off_scores = [], []
    for question, section in ON_TOPIC:
        score, chunk = search(question, client, conn, top_k=1)[0]
        hit = section in chunk["text"].split("\n")[0]
        hits += hit
        on_scores.append(score)
        print(f"  {'OK ' if hit else 'XX '} {score:.2f} {question}")
    for question in OFF_TOPIC:
        score, _ = search(question, client, conn, top_k=1)[0]
        off_scores.append(score)
        print(f"  OFF {score:.2f} {question}")

    threshold = settings["min_score"]
    kept = sum(s >= threshold for s in on_scores)
    rejected = sum(s < threshold for s in off_scores)
    print(f"== {model} : bonne section {hits}/{len(ON_TOPIC)}, "
          f"au-dessus du seuil {threshold} : {kept}/{len(ON_TOPIC)} pertinentes, "
          f"{rejected}/{len(OFF_TOPIC)} hors-sujet écartées, "
          f"{(time.time() - start) / (len(ON_TOPIC) + len(OFF_TOPIC)):.2f} s/question\n")


if __name__ == "__main__":
    config = load_config()
    models = sys.argv[1:] or [config.get("embedding_model", "nomic-embed-text")]
    for name in models:
        print(f"== {name}")
        evaluate(name, load_rag_settings(config))
