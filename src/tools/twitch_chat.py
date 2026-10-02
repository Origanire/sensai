## @file twitch_chat.py
# @brief Twitch chat connector: anonymous reading of messages via IRC.

import socket

## @brief Twitch chat IRC server.
HOST = "irc.chat.twitch.tv"
## @brief Cleartext IRC port.
PORT = 6667
## @brief Anonymous nickname: Twitch accepts any nickname starting with
# "justinfan" for read-only access, without an account or token.
NICK = "justinfan82730"
## @brief Requested IRC capabilities. "tags" adds the metadata of each
# message (user-id, display name, badges, timestamp).
CAPABILITIES = "twitch.tv/tags twitch.tv/commands"

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
# @param channel Name of the channel, without the "#".
# @return Connected socket, ready to be read by messages().
def connect(channel):
    sock = socket.create_connection((HOST, PORT))
    sock.sendall(
        f"CAP REQ :{CAPABILITIES}\r\n"
        f"PASS SCHMOOPIIE\r\nNICK {NICK}\r\nJOIN #{channel}\r\n".encode()
    )
    return sock


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
