# Ce module recherche les passages proches d’une question et les utilise pour préparer la réponse.

import math

from src.core.ingestion import QUERY_PREFIX, with_prefix
from src.core.storage import DOCUMENTS, load_all_chunks

# Ces valeurs sont utilisées si les réglages de recherche sont absents.
DEFAULT_RAG_SETTINGS = {
    "folder": "knowledge/",
    "chunk_size": 500,
    "overlap": 50,
    "top_k": 3,
    "min_score": 0.55,
}
# Ce texte est renvoyé quand aucun passage n’est assez pertinent.
NO_DOCUMENT = "Je ne trouve pas cette information dans mes documents."


# Cette fonction charge les réglages de recherche et complète les valeurs manquantes.
def load_rag_settings(config):
    section = (config or {}).get("rag") or {}
    return DEFAULT_RAG_SETTINGS | {k: v for k, v in section.items() if v is not None}


# Cette fonction mesure la proximité de deux vecteurs avec la similarité cosinus.
def cosine_similarity(vec_a, vec_b):
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0

    return dot_product / (norm_a * norm_b)


# Cette fonction classe les passages selon leur proximité avec la question et écarte ceux dont le score est trop faible.
def search(query, client, conn, top_k=3, collection=DOCUMENTS, min_score=0.0):
    query_vector = client.embed(with_prefix(client, QUERY_PREFIX, query))
    if query_vector is None:
        return []

    scored = []
    for chunk in load_all_chunks(conn, collection):
        score = cosine_similarity(query_vector, chunk["embedding"])
        if score >= min_score:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    return scored[:top_k]


# Cette fonction prépare les consignes avec des passages numérotés et leurs sources pour guider la réponse du modèle.
def build_rag_messages(query, results):
    context = "\n\n".join(
        f"[{i}] (source : {chunk['source']})\n{chunk['text'].strip()}"
        for i, (score, chunk) in enumerate(results, 1)
    )
    prompt = f"""Réponds à la question en te basant UNIQUEMENT sur les extraits numérotés ci-dessous.
Cite le numéro de l'extrait utilisé entre crochets, par exemple [1].
Si les extraits ne contiennent pas la réponse, dis-le clairement, sans inventer.

Extraits :
{context}

Question : {query}"""
    return [{"role": "user", "content": prompt}]


# Cette fonction affiche les sources retenues et leur score de pertinence.
def format_sources(results):
    return "\n".join(
        f"[{i}] {chunk['source']} ({score:.2f})"
        for i, (score, chunk) in enumerate(results, 1)
    )


# Cette fonction recherche les passages utiles et demande au modèle de répondre à partir de ces seuls éléments.
def rag_chat(query, client, conn, top_k=3, min_score=0.0, collection=DOCUMENTS):
    results = search(query, client, conn, top_k, collection, min_score)

    if not results:
        print(NO_DOCUMENT)
        return NO_DOCUMENT, []

    return client.chat(build_rag_messages(query, results)), results


# Cette fonction répond depuis les documents sans afficher le texte et renvoie un résultat exploitable même en cas d’échec.
def ask_documents(question, client, conn, settings):
    try:
        results = search(
            question, client, conn, settings["top_k"], DOCUMENTS, settings["min_score"]
        )
        if not results:
            return NO_DOCUMENT
        answer = client.chat_silent(build_rag_messages(question, results))
    except Exception as error:
        print(f"[RAG] ask_documents a échoué : {error}")
        return NO_DOCUMENT
    return answer.strip() if answer and answer.strip() else NO_DOCUMENT
