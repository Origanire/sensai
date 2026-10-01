## @file chat_agent.py
# @brief Agent chat Twitch : répond aux viewers qui mentionnent Sensai, en
# s'appuyant sur leur historique et leur profil.

import time

from src.core.ollama_client import OllamaClient, load_config
from src.core.prompts import load_prompt
from src.tools.twitch_chat import connect, messages
from src.tools.report import add_moment
from src.core.memory import (
    init_memory,
    load_facts,
    load_history,
    find_viewer_id,
    load_stats,
    load_summary,
    add_activity,
    remember_viewer,
    save_fact,
    save_message,
    save_summary,
)

## @brief Fichier de configuration propre à cet agent.
AGENT_CONFIG = "config/chat_agent.yaml"
## @brief Nombre de messages gardés tels quels lors d'une compression ;
# tout ce qui est plus ancien part dans le résumé.
KEEP_RECENT_MESSAGES = 4
## @brief Valeur affichée dans le prompt quand une section est vide.
NOTHING = "(none)"


## @brief État d'un viewer en mémoire pendant la session.
class ViewerState:
    ## @brief Construit l'état d'un viewer.
    #
    # @param history Messages actifs, au format "role"/"content".
    # @param facts Faits connus sur ce viewer.
    # @param summary Résumé des échanges plus anciens, ou None.
    # @param display_name Pseudo tel qu'affiché dans le chat.
    def __init__(self, history, facts, summary, display_name):
        ## @brief Messages actifs, envoyés tels quels au modèle.
        self.history = history
        ## @brief Faits connus sur ce viewer.
        self.facts = facts
        ## @brief Résumé des échanges plus anciens, ou None.
        self.summary = summary
        ## @brief Pseudo tel qu'affiché dans le chat.
        self.display_name = display_name


## @brief Charge depuis la base tout ce que Sensai sait d'un viewer.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @param display_name Pseudo tel qu'affiché dans le chat.
# @return Instance de ViewerState.
def load_viewer(db_connection, viewer_id, display_name):
    return ViewerState(
        history=load_history(db_connection, viewer_id),
        facts=load_facts(db_connection, viewer_id),
        summary=load_summary(db_connection, viewer_id),
        display_name=display_name,
    )


## @brief Détecte si un message s'adresse à Sensai et en retire la mention.
#
# @param text Texte du message.
# @param trigger Mention attendue, par exemple "@sensai".
# @return Message nettoyé de la mention, ou None s'il ne s'adresse pas à
#         Sensai. Une chaîne vide signifie une mention sans question.
def match_trigger(text, trigger):
    lowered = text.lower()
    position = lowered.find(trigger.lower())
    if position == -1:
        return None
    cleaned = text[:position] + text[position + len(trigger):]
    return " ".join(cleaned.split())


## @brief Met à jour les compteurs d'un viewer pour la session en cours.
#
# Tout reste en mémoire : aucune écriture disque pendant le stream.
#
# @param activity Dictionnaire des sessions en cours, modifié sur place.
# @param viewer_id Identifiant Twitch du viewer.
# @param seen_at Horodatage du message, en secondes.
# @return Session du viewer : "first", "last", "messages".
def track_activity(activity, viewer_id, seen_at):
    session = activity.get(viewer_id)
    if session is None:
        session = {"first": seen_at, "last": seen_at, "messages": 0}
        activity[viewer_id] = session

    session["last"] = max(session["last"], seen_at)
    session["messages"] += 1
    return session


## @brief Écrit en base l'activité de la session et vide la mémoire.
#
# Appelée une seule fois, à la fermeture de l'agent. Un arrêt brutal
# (kill -9, coupure) perd donc les statistiques du stream en cours.
#
# @param db_connection Connexion SQLite ouverte.
# @param activity Dictionnaire des sessions, vidé après écriture.
def flush_activity(db_connection, activity):
    for viewer_id, session in activity.items():
        add_activity(
            db_connection,
            viewer_id,
            session["first"],
            session["last"],
            session["messages"],
        )
    activity.clear()


## @brief Horodatage d'un message, en secondes.
#
# Utilise l'heure d'envoi fournie par Twitch, pour que les statistiques
# restent justes même si l'agent prend du retard.
#
# @param message Message produit par le connecteur.
# @return Horodatage en secondes, l'heure locale servant de repli.
def message_time(message):
    sent_at = message.get("sent_at")
    if sent_at and sent_at.isdigit():
        return int(sent_at) // 1000
    return int(time.time())


## @brief Met une durée en forme pour l'affichage.
#
# @param seconds Durée en secondes.
# @return Chaîne du type "2h05" ou "42min".
def format_duration(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes = rest // 60
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes}min"


## @brief Reconnaît une commande préfixée.
#
# @param text Texte du message.
# @param prefix Préfixe des commandes, par exemple "!".
# @return Couple (nom en minuscules, arguments), ou None si ce n'est pas
#         une commande.
def parse_command(text, prefix):
    if not text.startswith(prefix):
        return None

    name, _, arguments = text[len(prefix):].partition(" ")
    if not name:
        return None
    return name.lower(), arguments.strip()


## @brief Enregistre un fait sur un viewer désigné par son pseudo.
#
# Réservée au streamer et aux modérateurs ; la vérification des droits est
# faite par l'appelant.
#
# @param db_connection Connexion SQLite ouverte.
# @param viewers États des viewers chargés, mis à jour si le viewer visé y est.
# @param arguments Arguments de la commande : le pseudo visé, puis le fait.
# @return Pseudo visé si le fait a été enregistré ; None si les arguments
#         sont incomplets ou si ce viewer n'a jamais écrit.
def remember_about(db_connection, viewers, arguments):
    target, _, fact = arguments.partition(" ")
    target = target.lstrip("@")
    fact = fact.strip()
    if not target or not fact:
        return None

    viewer_id = find_viewer_id(db_connection, target)
    if viewer_id is None:
        return None

    save_fact(db_connection, viewer_id, fact)
    if viewer_id in viewers:
        viewers[viewer_id].facts.append(fact)
    return target


## @brief Compose le prompt envoyé au modèle pour un viewer.
#
# Le profil et le résumé sont recalculés à chaque appel dans un message
# "system" neuf : ils ne sont jamais ajoutés à l'historique, qui serait
# sinon pollué et persisté avec eux.
#
# @param state État du viewer.
# @param template Gabarit chargé depuis prompts/viewer_context.txt.
# @return Liste de messages prête pour Ollama.
def build_prompt(state, template):
    if not state.facts and not state.summary:
        return state.history

    facts = "\n".join(f"- {fact}" for fact in state.facts) or NOTHING
    system = template.format(facts=facts, summary=state.summary or NOTHING)
    return [{"role": "system", "content": system}] + state.history


## @brief Condense d'anciens échanges en un résumé.
#
# @param client Client Ollama.
# @param rules Consignes chargées depuis prompts/summarize.txt.
# @param previous_summary Résumé déjà existant, ou None.
# @param old_messages Messages à condenser.
# @return Texte du résumé, ou None en cas d'échec du modèle.
def summarize(client, rules, previous_summary, old_messages):
    lines = []
    for message in old_messages:
        speaker = "Viewer" if message["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {message['content']}")

    request = ""
    if previous_summary:
        request += f"Previous summary:\n{previous_summary}\n\n"
    request += "Exchanges to summarize:\n" + "\n".join(lines)

    summary = client.chat_silent(
        [
            {"role": "system", "content": rules},
            {"role": "user", "content": request},
        ],
        temperature=0,
    )
    return summary.strip() if summary else None


## @brief Résume les plus anciens messages et les retire de l'historique.
#
# @param client Client Ollama.
# @param rules Consignes de résumé.
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @param state État du viewer, modifié sur place.
# @return Nombre de messages résumés, 0 si rien n'a été fait.
def compress(client, rules, db_connection, viewer_id, state):
    if len(state.history) <= KEEP_RECENT_MESSAGES:
        return 0

    old_messages = state.history[:-KEEP_RECENT_MESSAGES]
    summary = summarize(client, rules, state.summary, old_messages)
    if summary is None:
        return 0

    state.summary = summary
    state.history = state.history[-KEEP_RECENT_MESSAGES:]
    save_summary(db_connection, viewer_id, summary, len(old_messages))
    return len(old_messages)


## @brief Fait répondre Sensai à un viewer et enregistre l'échange.
#
# En cas d'échec du modèle, la question est retirée de l'historique pour
# ne pas y laisser un tour sans réponse.
#
# @param client Client Ollama.
# @param db_connection Connexion SQLite ouverte.
# @param viewer_id Identifiant Twitch du viewer.
# @param state État du viewer, modifié sur place.
# @param question Message du viewer, sans la mention.
# @param template Gabarit de contexte.
# @return Réponse du modèle, ou None en cas d'échec.
def answer(client, db_connection, viewer_id, state, question, template):
    state.history.append({"role": "user", "content": question})

    print(f"Sensai : @{state.display_name} ", end="", flush=True)
    reply = client.chat(build_prompt(state, template))
    print()

    if reply is None:
        state.history.pop()
        return None

    state.history.append({"role": "assistant", "content": reply})
    save_message(db_connection, viewer_id, "user", question)
    save_message(db_connection, viewer_id, "assistant", reply)
    return reply


## @brief Point d'entrée de l'agent chat.
#
# Boucle sur les messages du chat : compte l'activité de tout le monde,
# exécute les commandes des modérateurs, et répond à ceux qui mentionnent
# Sensai. Aucun contenu n'est enregistré pour les messages qui ne lui sont
# pas adressés.
def main():
    config = load_config()
    agent_config = load_config(AGENT_CONFIG)

    channel = agent_config["channel"]
    trigger = agent_config["trigger"]
    command_prefix = agent_config["command_prefix"]
    remember_command = agent_config["remember_command"]
    fact_saved_message = agent_config["fact_saved_message"]
    viewer_not_found_message = agent_config["viewer_not_found_message"]
    moment_command = agent_config["moment_command"]
    moment_saved_message = agent_config["moment_saved_message"]
    moment_usage_message = agent_config["moment_usage_message"]
    token_budget = agent_config["history_token_budget"]

    context_template = load_prompt("viewer_context")
    summary_rules = load_prompt("summarize")

    client = OllamaClient(config)
    db_connection = init_memory()
    sock = connect(channel)
    viewers = {}
    activity = {}

    print(f"Listening on #{channel}, trigger \"{trigger}\". Ctrl+C to quit.\n")

    try:
        for message in messages(sock):
            viewer_id = message["user_id"]
            if viewer_id not in activity:
                remember_viewer(
                    db_connection,
                    viewer_id,
                    message["author"],
                    message["display_name"],
                )
            session = track_activity(
                activity, viewer_id, message_time(message)
            )

            command = parse_command(message["text"], command_prefix)
            if command is not None:
                name, arguments = command
                author = message["display_name"]
                if name == remember_command and message["is_moderator"]:
                    target = remember_about(db_connection, viewers, arguments)
                    if target is None:
                        print(f"Sensai : @{author} {viewer_not_found_message}")
                    else:
                        print(f"Sensai : @{author} {fact_saved_message}")
                elif name == moment_command and message["is_moderator"]:
                    if not arguments:
                        print(f"Sensai : @{author} {moment_usage_message}")
                    else:
                        line = add_moment(arguments, message_time(message))
                        print(f"[moment] {line}")
                        print(f"Sensai : @{author} {moment_saved_message}")
                continue

            question = match_trigger(message["text"], trigger)
            if question is None:
                continue

            if viewer_id not in viewers:
                viewers[viewer_id] = load_viewer(
                    db_connection, viewer_id, message["display_name"]
                )
            state = viewers[viewer_id]

            print(f"{state.display_name} : {question}")
            total = load_stats(db_connection, viewer_id)
            print(
                f"[viewer] {total['visits']} past visits, "
                f"{session['messages']} messages tonight, "
                f"{format_duration(session['last'] - session['first'])} active"
            )

            reply = answer(
                client, db_connection, viewer_id, state, question, context_template
            )
            if reply is None:
                continue

            used = client.last_prompt_tokens
            print(f"[tokens] {used}/{token_budget}")

            if used is not None and used > token_budget:
                compressed = compress(
                    client, summary_rules, db_connection, viewer_id, state
                )
                if compressed:
                    print(f"[compress] {compressed} messages summarized")
    finally:
        flush_activity(db_connection, activity)
        sock.close()
        db_connection.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
