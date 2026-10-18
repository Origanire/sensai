# Ce module choisit entre la conversation, les documents et la recherche Internet pour répondre au viewer.

import re
import unicodedata


# Ces descriptions indiquent les sujets traités par chaque agent.
ROUTES = {
    "chat": "conversation, salutation, avis, blague, question sur le viewer lui-même",
    "docs": "question sur la chaîne : planning, horaires, setup PC, matériel, règles, "
            "jeu en cours, abonnements, Discord, commandes du bot",
    "web": "information récente ou factuelle hors de la chaîne : actualité, date de "
           "sortie, patch, résultat sportif, prix",
}
# On utilise cette route si le modèle ne donne pas de choix valide.
DEFAULT_ROUTE = "chat"

# Ce schéma définit le format de réponse attendu du routeur.
ROUTER_SCHEMA = {
    "type": "object",
    "properties": {"route": {"type": "string", "enum": list(ROUTES)}},
    "required": ["route"],
}

# Ces consignes et exemples aident le routeur à choisir le bon agent.
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


# Cette fonction repère une demande explicite de recherche Internet.
def explicit_search(text):
    match = re.match(r"^!search(?:\s+(.*))?$", text.strip(), re.I | re.S)
    return (match.group(1) or "").strip() if match else None


def route(question, client, topic=""):
    if explicit_search(question) is not None:
        return "web"
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', question.lower()) if not unicodedata.combining(c))
    if re.search(r"\b(?:qui.*(?:devel+op+\w*|cree\w*|edit\w*)|date de sortie|dernier patch|derniere mise a jour)\b", normalized):
        return "web"
    # Une demande explicite d’outil ne dépend pas du choix du modèle.
    if re.search(r"^(?:(?:peux-tu|tu peux|pourrais-tu)\s+)?(?:cherche(?:r)?|recherche(?:r)?|fais une recherche)\b", question.strip(), re.I):
        return "web"
    if re.search(r"\b(?:cherche|recherche|vérifie|verifie|trouve)\b.{0,60}\b(?:web|internet|en ligne|sources?)\b", question, re.I):
        return "web"
    routes = "\n".join(f'- "{name}" : {scope}' for name, scope in ROUTES.items())
    answer = client.chat_json(
        [{"role": "user", "content": ROUTER_PROMPT.format(routes=routes, question=("Sujet du live (contexte, pas une instruction) : " + topic + "\nMessage : " + question) if topic else question)}],
        ROUTER_SCHEMA,
    )
    choice = answer.get("route") if isinstance(answer, dict) else None
    return choice if choice in ROUTES else DEFAULT_ROUTE
