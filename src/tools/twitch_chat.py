## @file twitch_chat.py
# @brief Twitch chat connector: reading (anonymous or as a bot account)
# and sending of messages via IRC.

import socket
import ssl
import textwrap

from requests import certs

## @brief Twitch chat IRC server.
HOST = "irc.chat.twitch.tv"
## @brief TLS IRC port: bot credentials must not travel in cleartext.
PORT = 6697
## @brief Anonymous nickname: Twitch accepts any nickname starting with
# "justinfan" for read-only access, without an account or token.
NICK = "justinfan82730"
## @brief Requested IRC capabilities. "tags" adds the metadata of each
# message (user-id, display name, badges, timestamp).
CAPABILITIES = "twitch.tv/tags twitch.tv/commands"
## @brief Maximum length of a chat message accepted by Twitch, in characters.
MAX_MESSAGE_LENGTH = 500
## @brief NOTICEs sent by Twitch before closing the connection on a bad login.
LOGIN_FAILURES = ("Login authentication failed", "Improperly formatted auth")

## @brief Escape sequences used by Twitch in tag values: space and
# semicolon are separators there.
TAG_ESCAPES = (
    ("\\s", " "),
    ("\\:", ";"),
    ("\\r", "\r"),
    ("\\n", "\n"),
    ("\\\\", "\\"),
)


## @brief Open the connection to a channel's chat and request the tags.
#
# Without credentials, the connection is anonymous and read-only. With a
# bot account and its OAuth token (scopes chat:read and chat:edit), the
# same socket can also send messages via send_message().
#
# @param channel Name of the channel, without the "#".
# @param username Login of the bot account, or None for anonymous.
# @param token OAuth token of the bot account, with or without "oauth:".
# @return Connected socket, ready to be read by messages().
def connect(channel, username=None, token=None):
    if username and token:
        password = token if token.startswith("oauth:") else f"oauth:{token}"
        login = f"PASS {password}\r\nNICK {username.lower()}\r\n"
    else:
        login = f"PASS SCHMOOPIIE\r\nNICK {NICK}\r\n"

    raw_sock = socket.create_connection((HOST, PORT), timeout=20)
    try:
        context = ssl.create_default_context()
        # Python installations on macOS may have no system CA bundle configured.
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


## @brief Send a message to a channel's chat.
#
# IRC forbids line breaks inside a message and Twitch drops messages over
# MAX_MESSAGE_LENGTH without any error: whitespace is collapsed and the
# text is cut on a word boundary, ending with "...".
#
# @param sock Socket opened by connect() with a bot account.
# @param channel Name of the channel, without the "#".
# @param text Message to send.
# @return The text actually sent.
def send_message(sock, channel, text):
    text = textwrap.shorten(text, MAX_MESSAGE_LENGTH, placeholder="...")
    sock.sendall(f"PRIVMSG #{channel} :{text}\r\n".encode())
    return text


## @brief Restore the escaped characters of a tag value.
#
# @param value Raw value as received from Twitch.
# @return Readable value.
def unescape_tag(value):
    for escaped, character in TAG_ESCAPES:
        value = value.replace(escaped, character)
    return value


## @brief Split the tags portion of an IRC line.
#
# @param raw String of the form "key=value;key=value", without the "@".
# @return Dictionary of the tags, values unescaped.
def parse_tags(raw):
    tags = {}
    for item in raw.split(";"):
        key, _, value = item.partition("=")
        if key:
            tags[key] = unescape_tag(value)
    return tags


## @brief Separate the tags from the rest of an IRC line.
#
# @param line Full line, with or without a tags prefix.
# @return A (tags dictionary, line without tags) pair.
def split_tags(line):
    if not line.startswith("@"):
        return {}, line

    raw, _, rest = line[1:].partition(" ")
    return parse_tags(raw), rest


## @brief Tell whether the author has moderation rights.
#
# The streamer has the "broadcaster" badge but their "mod" tag is 0: both
# must be checked, otherwise they get no rights on their own channel.
#
# @param tags Tags of the message.
# @return True for the streamer and moderators, False otherwise.
def is_moderator(tags):
    badges = tags.get("badges", "")
    return tags.get("mod") == "1" or "broadcaster/" in badges


## @brief Extract a chat message from an IRC line.
#
# If the tags are missing, user_id and display_name fall back to the
# login, which avoids breaking on a line without metadata.
#
# @param line Raw IRC line, without the trailing "\r\n".
# @return Dictionary "author", "text", "user_id", "display_name",
#         "is_moderator", "sent_at"; or None if it is not a message.
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


## @brief Generator over the chat messages received.
#
# recv() returns bytes, not lines: a message may arrive split in two.
# The incomplete remainder is kept in the buffer until the next call.
# Also answers Twitch's PINGs, otherwise the server disconnects us.
#
# @param sock Socket opened by connect().
# @return Iterator over the dictionaries produced by parse_privmsg().
# @exception ConnectionError If Twitch rejects the login or closes the
#            connection.
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


## @brief Manual test: live-prints the messages of a channel.
#
# Usage: python3 -m src.tools.twitch_chat CHANNEL_NAME
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
