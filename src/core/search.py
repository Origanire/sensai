## @file search.py
# @brief Recherche sémantique par similarité cosinus et chat RAG.

import math
from src.core.storage import load_all_chunks


## @brief Calcule la similarité cosinus entre deux vecteurs.
#
# @param vec_a Premier vecteur.
# @param vec_b Second vecteur.
# @return Score de similarité entre -1 et 1 (0 si un vecteur est nul).
def cosine_similarity(vec_a, vec_b):
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0

    return dot_product / (norm_a * norm_b)


## @brief Recherche les chunks les plus proches sémantiquement d'une requête.
#
# La requête est embeddée puis comparée (similarité cosinus) à tous les
# chunks de la base, qui sont triés par score décroissant.
#
# @param query Requête en langue naturelle.
# @param client Client Ollama, utilisé pour embedder la requête.
# @param conn Connexion SQLite contenant les chunks.
# @param top_k Nombre de chunks à renvoyer.
# @return Liste de tuples (score, chunk), triée par similarité décroissante.
def search(query, client, conn, top_k=3):
    query_vector = client.embed(query)
    if query_vector is None:
        return []

    all_chunks = load_all_chunks(conn)

    scored = []
    for chunk in all_chunks:
        score = cosine_similarity(query_vector, chunk["embedding"])
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    return scored[:top_k]

## @brief Répond à une requête en s'appuyant sur les documents ingérés (RAG).
#
# Récupère les top_k chunks les plus pertinents, les injecte comme contexte
# dans un prompt, puis demande au modèle de répondre uniquement à partir
# de ce contexte.
#
# @param query Question de l'utilisateur.
# @param client Client Ollama (embedding de la requête + chat).
# @param conn Connexion SQLite contenant les chunks.
# @param top_k Nombre de chunks injectés dans le contexte.
# @return Réponse du modèle, ou None en cas d'erreur.
def rag_chat(query, client, conn, top_k=3):
    results = search(query, client, conn, top_k=top_k)

    if not results:
        context = "Aucun document pertinent trouvé."
    else:
        context = "\n\n".join(chunk["text"] for score, chunk in results)

    prompt = f"""Réponds à la question en te basant UNIQUEMENT sur le contexte ci-dessous.
Si le contexte ne contient pas la réponse, dis-le clairement.

Contexte :
{context}

Question : {query}"""

    messages = [{"role": "user", "content": prompt}]
    return client.chat(messages)
