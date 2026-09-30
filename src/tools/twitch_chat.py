import socket

HOST = "irc.chat.twitch.tv"
PORT = 6667
NICK = "justinfan82730"


def connect(channel):
    sock = socket.create_connection((HOST, PORT))
    sock.sendall(f"PASS SCHMOOPIIE\r\nNICK {NICK}\r\nJOIN #{channel}\r\n".encode())
    return sock

def parse_privmsg(line):
    if not line.startswith(":") or " PRIVMSG " not in line:
        return None

    head, separator, text = line[1:].partition(" :")
    if not separator:
        return None

    return {"author": head.split("!", 1)[0], "text": text}

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
            print(f"{message['author']} : {message['text']}")
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
