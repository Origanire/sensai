## @file search.py
# @brief Semantic search via cosine similarity and RAG chat.

import math

from src.core.ingestion import QUERY_PREFIX, with_prefix
from src.core.storage import DOCUMENTS, load_all_chunks

## @brief Settings used when config.yaml has no "rag" section.
DEFAULT_RAG_SETTINGS = {
    "folder": "knowledge/",
    "chunk_size": 500,
    "overlap": 50,
    "top_k": 3,
    "min_score": 0.55,
}
## @brief Answer given when no ingested passage is relevant enough.
NO_DOCUMENT = "Je ne trouve pas cette information dans mes documents."


## @brief Read the "rag" section of the configuration.
#
# @param config Configuration dictionary loaded from config.yaml.
# @return Dict completed with DEFAULT_RAG_SETTINGS for any missing key.
def load_rag_settings(config):
    section = (config or {}).get("rag") or {}
    return DEFAULT_RAG_SETTINGS | {k: v for k, v in section.items() if v is not None}


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
# of the collection, sorted by decreasing score. Chunks under min_score are
# dropped: a near-miss injected into the context makes a small model answer
# confidently from an unrelated passage.
#
# @param query Natural-language query.
# @param client Ollama client, used to embed the query.
# @param conn SQLite connection holding the chunks.
# @param top_k Number of chunks to return.
# @param collection Collection searched ("documents" or "streams").
# @param min_score Minimum similarity for a chunk to be kept.
# @return List of (score, chunk) tuples, sorted by decreasing similarity.
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


## @brief Build the prompt that makes the model answer from the passages.
#
# Each passage is numbered and labeled with its source, so the answer can
# cite [1], [2]... and the user can check them.
#
# @param query User's question.
# @param results (score, chunk) tuples returned by search().
# @return Message list ready for Ollama.
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


## @brief List the sources of a RAG answer, with their scores.
#
# @param results (score, chunk) tuples returned by search().
# @return Text such as "[1] faq.txt (0.71)", one source per line.
def format_sources(results):
    return "\n".join(
        f"[{i}] {chunk['source']} ({score:.2f})"
        for i, (score, chunk) in enumerate(results, 1)
    )


## @brief Answer a query using the ingested documents (RAG), streaming it.
#
# Retrieves the top_k relevant chunks, injects them as context into a
# prompt, then asks the model to answer using only that context. Without
# any relevant chunk, the model is not called at all.
#
# @param query User's question.
# @param client Ollama client (query embedding + chat).
# @param conn SQLite connection holding the chunks.
# @param top_k Number of chunks injected into the context.
# @param min_score Minimum similarity for a chunk to be used.
# @param collection Collection searched.
# @return A (answer, results) pair; answer is None on model error.
def rag_chat(query, client, conn, top_k=3, min_score=0.0, collection=DOCUMENTS):
    results = search(query, client, conn, top_k, collection, min_score)

    if not results:
        print(NO_DOCUMENT)
        return NO_DOCUMENT, []

    return client.chat(build_rag_messages(query, results)), results


## @brief Answer a viewer's question from the documents, without printing.
#
# Entry point of the documents agent for the other agents: never raises.
#
# @param question Question in natural language.
# @param client Ollama client.
# @param conn SQLite connection holding the chunks.
# @param settings Settings from load_rag_settings().
# @return The answer, or NO_DOCUMENT when nothing relevant was found.
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
