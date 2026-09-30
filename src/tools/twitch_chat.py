import socket

HOST = "irc.chat.twitch.tv"
PORT = 6667
NICK = "justinfan82730"
CHANNEL = "kevinaigre"

sock = socket.create_connection((HOST, PORT))
sock.sendall(f"PASS SCHMOOPIIE\r\nNICK {NICK}\r\nJOIN #{CHANNEL}\r\n".encode())

buffer = ""
while True:
    buffer += sock.recv(4096).decode("utf-8", errors="replace")
    while "\r\n" in buffer:
        line, buffer = buffer.split("\r\n", 1)

        if line.startswith("PING"):
            sock.sendall(b"PONG :tmi.twitch.tv\r\n")
            continue

        if not line.startswith(":") or " PRIVMSG " not in line:
            continue

        head, separator, text = line[1:].partition(" :")
        if not separator:
            continue

        author = head.split("!", 1)[0]
        print(f"{author} : {text}")
