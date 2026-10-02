import textwrap

from ddgs import DDGS

## @brief Text returned to calling agents when the search cannot be done.
SEARCH_UNAVAILABLE = "Recherche indisponible pour le moment."
## @brief Maximum length of a quick fact, in characters: a few seconds of
# reading on an overlay.
QUICK_FACT_MAX_LENGTH = 160
## @brief Settings used when config.yaml has no "internet_agent" section.
DEFAULT_SETTINGS = {
    "cooldown_seconds": 30,
    "max_results": 5,
}


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


## @brief Search the web for a question, retrying with its raw wording.
#
# The query rewritten by the model sometimes finds nothing: DDGS fails
# intermittently, and a small model may distort a name. A second search
# with the question as typed covers both cases.
#
# @param question Question in natural language.
# @param client Client used to rewrite the question into a query.
# @param max_results Maximum number of results.
# @return A (query used, list of results) pair; the list may be empty.
def search_question(question, client, max_results=5):
    query = generate_search_query(question, client)
    print(f"[Recherche] {query}")
    results = web_search(query, max_results=max_results)

    if not results and query != question:
        print(f"[Recherche] aucun résultat, nouvel essai avec : {question}")
        query = question
        results = web_search(query, max_results=max_results)
    return query, results


def web_chat(query, client, max_results=5):
    """Pipeline complet : reformule la question, cherche sur le web, répond avec sources."""
    _, results = search_question(query, client, max_results=max_results)
    if not results:
        return SEARCH_UNAVAILABLE
    context = format_results_for_context(results)

    prompt = f"""Réponds à la question en te basant sur les résultats de recherche web ci-dessous.
Cite tes sources (les URLs) dans ta réponse.

Résultats de recherche :
{context}

Question : {query}"""

    messages = [{"role": "user", "content": prompt}]
    answer = client.chat(messages)

    # A small model regularly forgets the URLs: the first result is the source
    if answer and "http" not in answer:
        answer = f"{answer.rstrip()}\n\nSource : {results[0]['url']}"
    return answer


## @brief Read the "internet_agent" section of the configuration.
#
# @param config Configuration dictionary loaded from config.yaml.
# @return Dict with "cooldown_seconds" and "max_results", completed with
#         DEFAULT_SETTINGS for any missing key.
def load_internet_settings(config):
    section = (config or {}).get("internet_agent") or {}
    return DEFAULT_SETTINGS | {k: v for k, v in section.items() if v is not None}


## @brief Ollama client wrapper whose chat() never prints anything.
#
# web_chat() and generate_search_query() call client.chat(), which streams
# tokens to stdout. Called by another agent, the answer must be returned,
# not printed: this wrapper routes the call to chat_silent().
class SilentClient:
    ## @brief Wrap a client.
    #
    # @param client OllamaClient to wrap.
    def __init__(self, client):
        ## @brief Wrapped OllamaClient.
        self.client = client

    ## @brief Same contract as OllamaClient.chat(), without printing.
    #
    # @param messages Conversation (list of "role"/"content" dicts).
    # @return The model's response, or None on error.
    def chat(self, messages):
        return self.client.chat_silent(messages)


## @brief Answer a question from a live web search, with sources.
#
# Entry point of the Internet agent for the other agents: never raises,
# never prints the answer. Relies on web_chat() for the pipeline
# question -> search query -> results -> answer citing the URLs.
#
# @param question Question in natural language.
# @param client OllamaClient.
# @param max_results Number of web results given to the model.
# @return The answer, or SEARCH_UNAVAILABLE if the search or the model failed.
def ask_internet(question, client, max_results=5):
    try:
        answer = web_chat(question, SilentClient(client), max_results=max_results)
    except Exception as error:
        print(f"[Internet] ask_internet a échoué : {error}")
        return SEARCH_UNAVAILABLE

    if not answer or not answer.strip():
        return SEARCH_UNAVAILABLE
    return answer.strip()


## @brief Short fact about a topic, for an overlay or to be read aloud.
#
# One or two sentences, no list, no URL, at most QUICK_FACT_MAX_LENGTH
# characters. The model is asked to be short, and the length is enforced
# afterwards since a small model does not always comply.
#
# @param topic Topic or question.
# @param client OllamaClient.
# @param max_results Number of web results given to the model.
# @return The fact, or SEARCH_UNAVAILABLE if the search or the model failed.
def get_quick_fact(topic, client, max_results=3):
    silent = SilentClient(client)
    try:
        _, results = search_question(topic, silent, max_results=max_results)
        if not results:
            return SEARCH_UNAVAILABLE

        prompt = f"""À partir des résultats de recherche web ci-dessous, donne UN fait
précis sur : {topic}

Résultats de recherche :
{format_results_for_context(results)}

Règles :
- Une ou deux phrases, {QUICK_FACT_MAX_LENGTH} caractères maximum.
- Uniquement une information présente dans les résultats.
- Pas de liste, pas d'URL, pas de mise en forme, pas d'introduction."""

        fact = silent.chat([{"role": "user", "content": prompt}])
    except Exception as error:
        print(f"[Internet] get_quick_fact a échoué : {error}")
        return SEARCH_UNAVAILABLE

    if not fact or not fact.strip():
        return SEARCH_UNAVAILABLE
    fact = fact.strip().strip('"').replace("**", "")
    return textwrap.shorten(fact, QUICK_FACT_MAX_LENGTH, placeholder="...")
