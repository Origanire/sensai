import socket

HOST = "irc.chat.twitch.tv"
PORT = 6667
NICK = "justinfan82730"
CAPABILITIES = "twitch.tv/tags twitch.tv/commands"

TAG_ESCAPES = (
    ("\\s", " "),
    ("\\:", ";"),
    ("\\r", "\r"),
    ("\\n", "\n"),
    ("\\\\", "\\"),
)


def connect(channel):
    sock = socket.create_connection((HOST, PORT))
    sock.sendall(
        f"CAP REQ :{CAPABILITIES}\r\n"
        f"PASS SCHMOOPIIE\r\nNICK {NICK}\r\nJOIN #{channel}\r\n".encode()
    )
    return sock


def unescape_tag(value):
    for escaped, character in TAG_ESCAPES:
        value = value.replace(escaped, character)
    return value


def parse_tags(raw):
    tags = {}
    for item in raw.split(";"):
        key, _, value = item.partition("=")
        if key:
            tags[key] = unescape_tag(value)
    return tags


def split_tags(line):
    if not line.startswith("@"):
        return {}, line

    raw, _, rest = line[1:].partition(" ")
    return parse_tags(raw), rest


def is_moderator(tags):
    badges = tags.get("badges", "")
    return tags.get("mod") == "1" or "broadcaster/" in badges


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


if __name__ == "__main__":
    import sys

    channel = sys.argv[1] if len(sys.argv) > 1 else "kevinaigre"

    sock = connect(channel)
    print(f"Connecté au chat de #{channel}. Ctrl+C pour quitter.\n")
    try:
        for message in messages(sock):
            mod = " [mod]" if message["is_moderator"] else ""
            print(f"{message['display_name']}{mod} ({message['user_id']}) : {message['text']}")
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
