import math
from src.storage import load_all_chunks


def cosine_similarity(vec_a, vec_b):
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0

    return dot_product / (norm_a * norm_b)


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
