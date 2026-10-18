# Ce module lance un serveur MCP et échange des messages JSON-RPC avec lui par ses entrées et sorties standard.

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

# Les serveurs sont lancés depuis ce dossier du projet.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Ce dossier conserve les erreurs des serveurs pour le débogage.
LOG_DIR = PROJECT_ROOT / "logs"
# Cette valeur annonce la version du protocole MCP utilisée par le client.
PROTOCOL_VERSION = "2025-06-18"
# Ce délai limite l’attente d’une réponse du serveur.
REQUEST_TIMEOUT = 60
# Ce code signale une méthode JSON-RPC inconnue.
METHOD_NOT_FOUND = -32601


# Cette erreur indique un échec de lancement ou de réponse du serveur.
class MCPError(Exception):
    pass


# Cette classe représente la connexion à un serveur MCP lancé dans un processus séparé.
class MCPClient:
    # On lance le serveur et on initialise le protocole. La commande python utilise le même interpréteur que Sensai.
    def __init__(self, name, command, args=None, env=None):
        # Ce nom identifie le serveur.
        self.name = name
        # Ces réponses attendent d’être récupérées par leur identifiant de requête.
        self._pending = {}
        # Ce compteur fournit le prochain identifiant de requête.
        self._next_id = 1
        # Ce verrou protège les requêtes partagées entre plusieurs tâches.
        self._lock = threading.Lock()

        executable = sys.executable if command in ("python", "python3") else shutil.which(command)
        if executable is None:
            raise MCPError(f"commande « {command} » introuvable")

        LOG_DIR.mkdir(exist_ok=True)
        # Ce fichier reçoit les erreurs du serveur.
        self._log = open(LOG_DIR / f"mcp_{name}.log", "w", encoding="utf-8")
        try:
            # Cette variable contient le processus du serveur.
            self.process = subprocess.Popen(
                [executable, *(args or [])],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._log,
                cwd=PROJECT_ROOT,
                env=os.environ | (env or {}),
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as error:
            raise MCPError(f"impossible de lancer « {command} » : {error}") from error

        threading.Thread(target=self._read_loop, name=f"mcp-{name}", daemon=True).start()

        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "sensai", "version": "1.0"},
        })
        # Ces informations décrivent le nom et la version annoncés par le serveur.
        self.server_info = result.get("serverInfo", {})
        self.notify("notifications/initialized")

    # Cette méthode lit les messages du serveur, distribue les réponses et traite ses demandes comme les PING.
    def _read_loop(self):
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "id" in message and ("result" in message or "error" in message):
                with self._lock:
                    waiting = self._pending.get(message["id"])
                if waiting is not None:
                    waiting.put(message)
            elif "id" in message and "method" in message:
                if message["method"] == "ping":
                    self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                else:
                    self._send({"jsonrpc": "2.0", "id": message["id"], "error": {
                        "code": METHOD_NOT_FOUND, "message": "not supported by sensai"}})

        # Le serveur s’est arrêté : on débloque les requêtes qui attendaient encore une réponse.
        with self._lock:
            for waiting in self._pending.values():
                waiting.put({"error": {"message": "le serveur MCP s'est arrêté"}})

    # Cette méthode écrit un message JSON-RPC vers le serveur.
    def _send(self, message):
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise MCPError(f"serveur « {self.name} » injoignable : {error}") from error

    # Cette méthode envoie une requête et attend sa réponse, avec gestion des erreurs et du délai.
    def request(self, method, params=None):
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            waiting = queue.Queue(maxsize=1)
            self._pending[request_id] = waiting

        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            self._send(message)
            answer = waiting.get(timeout=REQUEST_TIMEOUT)
        except queue.Empty:
            raise MCPError(f"« {self.name} » n'a pas répondu à {method} "
                           f"en {REQUEST_TIMEOUT} s") from None
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

        if "error" in answer:
            raise MCPError(answer["error"].get("message", "erreur inconnue"))
        return answer.get("result", {})

    # Cette méthode envoie une notification qui n’attend pas de réponse.
    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    # Cette méthode récupère tous les outils du serveur, page après page.
    def list_tools(self):
        tools = []
        cursor = None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else None)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    # Cette méthode appelle un outil et renvoie son texte ainsi qu’un indicateur d’erreur.
    def call_tool(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        parts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(f"[contenu {item.get('type')} non affiché]")
        return "\n".join(parts), bool(result.get("isError"))

    # Cette méthode arrête le serveur.
    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.process.kill()
        self._log.close()
