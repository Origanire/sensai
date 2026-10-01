## @file twitch_chat.py
# @brief Connecteur de chat Twitch : lecture anonyme des messages via IRC.

import socket

## @brief Serveur IRC du chat Twitch.
HOST = "irc.chat.twitch.tv"
## @brief Port IRC en clair.
PORT = 6667
## @brief Pseudo anonyme : Twitch accepte tout pseudo commençant par
# "justinfan" en lecture seule, sans compte ni token.
NICK = "justinfan82730"
## @brief Capacités IRC demandées. "tags" ajoute les métadonnées de chaque
# message (user-id, pseudo d'affichage, badges, horodatage).
CAPABILITIES = "twitch.tv/tags twitch.tv/commands"

## @brief Séquences d'échappement utilisées par Twitch dans les valeurs de
# tags : l'espace et le point-virgule y sont des séparateurs.
TAG_ESCAPES = (
    ("\\s", " "),
    ("\\:", ";"),
    ("\\r", "\r"),
    ("\\n", "\n"),
    ("\\\\", "\\"),
)


## @brief Ouvre la connexion au chat d'une chaîne et demande les tags.
#
# @param channel Nom de la chaîne, sans le "#".
# @return Socket connecté, prêt à être lu par messages().
def connect(channel):
    sock = socket.create_connection((HOST, PORT))
    sock.sendall(
        f"CAP REQ :{CAPABILITIES}\r\n"
        f"PASS SCHMOOPIIE\r\nNICK {NICK}\r\nJOIN #{channel}\r\n".encode()
    )
    return sock


## @brief Restitue les caractères échappés d'une valeur de tag.
#
# @param value Valeur brute telle que reçue de Twitch.
# @return Valeur lisible.
def unescape_tag(value):
    for escaped, character in TAG_ESCAPES:
        value = value.replace(escaped, character)
    return value


## @brief Découpe la portion de tags d'une ligne IRC.
#
# @param raw Chaîne de la forme "cle=valeur;cle=valeur", sans le "@".
# @return Dictionnaire des tags, valeurs déséchappées.
def parse_tags(raw):
    tags = {}
    for item in raw.split(";"):
        key, _, value = item.partition("=")
        if key:
            tags[key] = unescape_tag(value)
    return tags


## @brief Sépare les tags du reste d'une ligne IRC.
#
# @param line Ligne complète, avec ou sans préfixe de tags.
# @return Couple (dictionnaire des tags, ligne sans les tags).
def split_tags(line):
    if not line.startswith("@"):
        return {}, line

    raw, _, rest = line[1:].partition(" ")
    return parse_tags(raw), rest


## @brief Indique si l'auteur a les droits de modération.
#
# Le streamer a le badge "broadcaster" mais son tag "mod" vaut 0 : il faut
# donc tester les deux, sinon il n'a aucun droit sur sa propre chaîne.
#
# @param tags Tags du message.
# @return True pour le streamer et les modérateurs, False sinon.
def is_moderator(tags):
    badges = tags.get("badges", "")
    return tags.get("mod") == "1" or "broadcaster/" in badges


## @brief Extrait un message de chat d'une ligne IRC.
#
# Si les tags sont absents, user_id et display_name retombent sur le login,
# ce qui évite de casser sur une ligne sans métadonnées.
#
# @param line Ligne IRC brute, sans le "\r\n" final.
# @return Dictionnaire "author", "text", "user_id", "display_name",
#         "is_moderator", "sent_at" ; ou None si ce n'est pas un message.
def parse_privmsg(line):
    tags, line = split_tags(line)

    if not line.startswith(":") or " PRIVMSG " not in line:
        return None

    head, separator, text = line[1:].partition(" :")
    if not separator:
        return None

    login = head.split("!", 1)[0]
    return {
        "author": login,
        "text": text,
        "user_id": tags.get("user-id") or login,
        "display_name": tags.get("display-name") or login,
        "is_moderator": is_moderator(tags),
        "sent_at": tags.get("tmi-sent-ts"),
    }


## @brief Générateur des messages de chat reçus.
#
# recv() renvoie des octets, pas des lignes : un message peut arriver coupé
# en deux. Le reste incomplet est conservé dans le buffer jusqu'au prochain
# appel. Répond aussi aux PING de Twitch, sans quoi le serveur déconnecte.
#
# @param sock Socket ouvert par connect().
# @return Itérateur de dictionnaires produits par parse_privmsg().
def messages(sock):
    buffer = ""
    while True:
        buffer += sock.recv(4096).decode("utf-8", errors="replace")
        while "\r\n" in buffer:
            line, buffer = buffer.split("\r\n", 1)

            if line.startswith("PING"):
                sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                continue

            message = parse_privmsg(line)
            if message is not None:
                yield message


## @brief Test manuel : affiche en direct les messages d'une chaîne.
#
# Usage : python3 -m src.tools.twitch_chat NOM_DE_CHAINE
def main():
    import sys

    channel = sys.argv[1] if len(sys.argv) > 1 else "kevinaigre"

    sock = connect(channel)
    print(f"Connecté au chat de #{channel}. Ctrl+C pour quitter.\n")
    try:
        for message in messages(sock):
            mod = " [mod]" if message["is_moderator"] else ""
            print(
                f"{message['display_name']}{mod} "
                f"({message['user_id']}) : {message['text']}"
            )
    finally:
        sock.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
