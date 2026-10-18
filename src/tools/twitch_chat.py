# Ce module lit et envoie les messages du chat Twitch grâce au protocole IRC.

import socket
import ssl
import textwrap

from requests import certs
from src.core.chat_text import MAX_CHAT_CHARACTERS, fit_chat_text

# Cette adresse correspond au serveur IRC de Twitch.
HOST = "irc.chat.twitch.tv"
# On utilise le port chiffré pour protéger les identifiants du bot.
PORT = 6697
# Ce pseudo permet de lire le chat sans compte ni jeton.
NICK = "justinfan82730"
# Ces options IRC ajoutent les identifiants, pseudos, badges et dates aux messages.
CAPABILITIES = "twitch.tv/tags twitch.tv/commands"
# Cette valeur fixe la longueur maximale d’un message Twitch.
MAX_MESSAGE_LENGTH = MAX_CHAT_CHARACTERS
# Ces messages de Twitch signalent un problème de connexion au compte.
LOGIN_FAILURES = ("Login authentication failed", "Improperly formatted auth")

# Ces séquences représentent les caractères échappés dans les métadonnées Twitch.
TAG_ESCAPES = (
    ("\\s", " "),
    ("\\:", ";"),
    ("\\r", "\r"),
    ("\\n", "\n"),
    ("\\\\", "\\"),
)


# Cette fonction ouvre le chat et demande ses métadonnées. Sans identifiants, elle reste en lecture seule.
def connect(channel, username=None, token=None):
    if username and token:
        password = token if token.startswith("oauth:") else f"oauth:{token}"
        login = f"PASS {password}\r\nNICK {username.lower()}\r\n"
    else:
        login = f"PASS SCHMOOPIIE\r\nNICK {NICK}\r\n"

    raw_sock = socket.create_connection((HOST, PORT), timeout=20)
    try:
        context = ssl.create_default_context()
        # Certaines installations Python sur macOS n’ont pas de certificats système configurés.
        context.load_verify_locations(cafile=certs.where())
        sock = context.wrap_socket(raw_sock, server_hostname=HOST)
    except Exception:
        raw_sock.close()
        raise
    sock.settimeout(None)
    sock.sendall(
        f"CAP REQ :{CAPABILITIES}\r\n{login}JOIN #{channel}\r\n".encode()
    )
    return sock


# Cette fonction nettoie et raccourcit le texte avant de l’envoyer sur Twitch, sans liens ni retours à la ligne.
def send_message(sock, channel, text):
    text = fit_chat_text(text, MAX_MESSAGE_LENGTH)
    sock.sendall(f"PRIVMSG #{channel} :{text}\r\n".encode())
    return text


# Cette fonction remet les caractères échappés dans leur forme lisible.
def unescape_tag(value):
    for escaped, character in TAG_ESCAPES:
        value = value.replace(escaped, character)
    return value


# Cette fonction transforme les métadonnées IRC en dictionnaire.
def parse_tags(raw):
    tags = {}
    for item in raw.split(";"):
        key, _, value = item.partition("=")
        if key:
            tags[key] = unescape_tag(value)
    return tags


# Cette fonction sépare les métadonnées du reste de la ligne IRC.
def split_tags(line):
    if not line.startswith("@"):
        return {}, line

    raw, _, rest = line[1:].partition(" ")
    return parse_tags(raw), rest


# Cette fonction reconnaît les modérateurs et le streamer grâce aux badges et aux métadonnées Twitch.
def is_moderator(tags):
    badges = tags.get("badges", "")
    return tags.get("mod") == "1" or "broadcaster/" in badges


# Cette fonction extrait le texte et l’auteur d’un message IRC, même si certaines métadonnées manquent.
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


# Cette boucle reconstitue les messages reçus et répond aux PING de Twitch pour garder la connexion ouverte.
def messages(sock, on_ready=None):
    buffer = ""
    ready = False
    while True:
        data = sock.recv(4096)
        if not data:
            raise ConnectionError("Twitch a fermé la connexion au chat.")
        buffer += data.decode("utf-8", errors="replace")
        while "\r\n" in buffer:
            line, buffer = buffer.split("\r\n", 1)

            if line.startswith("PING"):
                sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                continue

            if " NOTICE " in line and any(f in line for f in LOGIN_FAILURES):
                raise ConnectionError(
                    "Twitch a refusé la connexion du bot : vérifie "
                    "TWITCH_BOT_USERNAME et TWITCH_OAUTH_TOKEN dans .env."
                )

            if not ready and (" JOIN #" in line or " ROOMSTATE #" in line):
                ready = True
                if on_ready is not None:
                    on_ready()

            message = parse_privmsg(line)
            if message is not None:
                yield message


# Ce test manuel affiche les messages d’une chaîne avec python -m src.tools.twitch_chat NOM_CHAINE.
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
