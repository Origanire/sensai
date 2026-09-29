from ddgs import DDGS


def web_search(query, max_results=5):
    """Effectue une recherche web et retourne une liste de résultats.

    Chaque résultat : {"title": ..., "url": ..., "snippet": ...}
    """
    results = []

    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
    except Exception as e:
        print(f"[Erreur] Recherche web échouée : {e}")
        return []

    return results


def format_results_for_context(results):
    """Transforme les résultats en texte lisible, prêt à injecter dans un prompt."""
    if not results:
        return "Aucun résultat trouvé."

    blocks = []
    for r in results:
        blocks.append(f"- {r['title']}\n  {r['snippet']}\n  Source: {r['url']}")

    return "\n\n".join(blocks)


def generate_search_query(question, client):
    prompt = f"""Transforme cette question en une requête de recherche web courte et efficace (mots-clés uniquement, pas de phrase complète, pas de point d'interrogation, pas de guillemets).

Question : {question}

Requête de recherche :"""

    messages = [{"role": "user", "content": prompt}]
    query = client.chat(messages)
    if query is None:
        return question
    return query.strip().strip('"').strip("'")


def web_chat(query, client, max_results=5):
    """Pipeline complet : reformule la question, cherche sur le web, répond avec sources."""
    search_query = generate_search_query(query, client)
    print(f"[Recherche] {search_query}")

    results = web_search(search_query, max_results=max_results)
    context = format_results_for_context(results)

    prompt = f"""Réponds à la question en te basant sur les résultats de recherche web ci-dessous.
Cite tes sources (les URLs) dans ta réponse.

Résultats de recherche :
{context}

Question : {query}"""

    messages = [{"role": "user", "content": prompt}]
    return client.chat(messages)