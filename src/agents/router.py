## @file router.py
# @brief Router agent (A2): picks which specialized agent answers a viewer.
#
# Three agents can answer a mention in the chat:
# - "chat": the conversation agent, with the viewer's memory (default);
# - "docs": the documents agent, which answers from the channel's knowledge
#   base (RAG over the FAQ: planning, setup, rules...);
# - "web": the Internet agent, for fresh facts (news, release dates, scores).
# The router is a small model call constrained to a JSON schema: it only
# classifies, it never answers. Any failure falls back to "chat".

## @brief Routes the router may choose, with what they cover.
ROUTES = {
    "chat": "conversation, salutation, avis, blague, question sur le viewer lui-même",
    "docs": "question sur la chaîne : planning, horaires, setup PC, matériel, règles, "
            "jeu en cours, abonnements, Discord, commandes du bot",
    "web": "information récente ou factuelle hors de la chaîne : actualité, date de "
           "sortie, patch, résultat sportif, prix",
}
## @brief Route used when the model fails or answers out of the schema.
DEFAULT_ROUTE = "chat"

## @brief JSON schema of the router's answer.
ROUTER_SCHEMA = {
    "type": "object",
    "properties": {"route": {"type": "string", "enum": list(ROUTES)}},
    "required": ["route"],
}

## @brief Instructions and examples given to the router.
ROUTER_PROMPT = """Tu aiguilles les messages que les viewers adressent au bot d'une chaîne
Twitch. Dans ces messages, « tu », « ton », « ta » désignent souvent le streamer.
Choisis QUI doit répondre :
{routes}

Exemples :
- "salut sensai ça va ?" -> chat
- "tu préfères Mario ou Zelda ?" -> chat
- "tu te souviens de moi ?" -> chat
- "gg pour la victoire" -> chat
- "c'est quand le prochain stream ?" -> docs
- "il stream le jeudi ?" -> docs
- "c'est quoi ta carte graphique ?" -> docs
- "c'est quoi ta souris ?" -> docs
- "c'est quel jeu là ?" -> docs
- "on a le droit de parler politique ?" -> docs
- "on a le droit de mettre des liens ?" -> docs
- "c'est quand la sortie de GTA 6 ?" -> web
- "qui a gagné le match du PSG hier ?" -> web
- "c'est quoi le dernier patch d'Elden Ring ?" -> web
- "quoi de neuf dans la saison 3 de Rocket League ?" -> web
- "combien coûte la PS5 Pro ?" -> web

Message : {question}"""


## @brief Pick the agent that should answer a viewer's message.
#
# @param question Viewer's message, without the mention.
# @param client OllamaClient.
# @return "chat", "docs" or "web".
def route(question, client):
    routes = "\n".join(f'- "{name}" : {scope}' for name, scope in ROUTES.items())
    answer = client.chat_json(
        [{"role": "user", "content": ROUTER_PROMPT.format(routes=routes, question=question)}],
        ROUTER_SCHEMA,
    )
    choice = (answer or {}).get("route")
    return choice if choice in ROUTES else DEFAULT_ROUTE
