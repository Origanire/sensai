## @file search.py
# @brief Semantic search via cosine similarity and RAG chat.

import math
from src.core.storage import load_all_chunks


## @brief Compute the cosine similarity between two vectors.
#
# @param vec_a First vector.
# @param vec_b Second vector.
# @return Similarity score between -1 and 1 (0 if a vector is zero).
def cosine_similarity(vec_a, vec_b):
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0

    return dot_product / (norm_a * norm_b)


## @brief Find the chunks semantically closest to a query.
#
# The query is embedded then compared (cosine similarity) to every chunk
# in the database, which are sorted by decreasing score.
#
# @param query Natural-language query.
# @param client Ollama client, used to embed the query.
# @param conn SQLite connection holding the chunks.
# @param top_k Number of chunks to return.
# @return List of (score, chunk) tuples, sorted by decreasing similarity.
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

## @brief Answer a query using the ingested documents (RAG).
#
# Retrieves the top_k most relevant chunks, injects them as context into
# a prompt, then asks the model to answer using only that context.
#
# @param query User's question.
# @param client Ollama client (query embedding + chat).
# @param conn SQLite connection holding the chunks.
# @param top_k Number of chunks injected into the context.
# @return The model's response, or None on error.
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
