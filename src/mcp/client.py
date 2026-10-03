## @file client.py
# @brief Minimal MCP client (Model Context Protocol) over stdio.
#
# An MCP server is a subprocess that speaks JSON-RPC 2.0, one message per
# line, on its stdin/stdout. The client starts it, runs the handshake
# (initialize, then notifications/initialized), lists its tools
# (tools/list) and calls them (tools/call). Written by hand on purpose:
# no LLM framework is allowed, and the protocol is small.

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

## @brief Root of the repository: servers are started from there.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
## @brief Folder holding the stderr of each server, for debugging.
LOG_DIR = PROJECT_ROOT / "logs"
## @brief MCP protocol version announced by the client.
PROTOCOL_VERSION = "2025-06-18"
## @brief Time allowed for a server to answer a request, in seconds.
REQUEST_TIMEOUT = 60
## @brief JSON-RPC error code for an unknown method.
METHOD_NOT_FOUND = -32601


## @brief Raised when a server cannot be started or answers with an error.
class MCPError(Exception):
    pass


## @brief Connection to one MCP server running as a subprocess.
class MCPClient:
    ## @brief Start the server and run the MCP handshake.
    #
    # "python" as command means the interpreter running Sensai, so our own
    # server uses the same virtual environment.
    #
    # @param name Name of the server, as written in config.yaml.
    # @param command Executable to run (python, npx, uvx...).
    # @param args Arguments of the command.
    # @param env Extra environment variables for the server.
    # @exception MCPError If the server cannot be started or initialized.
    def __init__(self, name, command, args=None, env=None):
        ## @brief Name of the server.
        self.name = name
        ## @brief Answers waiting to be read, by request id.
        self._pending = {}
        ## @brief Next request id.
        self._next_id = 1
        ## @brief Protects _next_id and _pending between threads.
        self._lock = threading.Lock()

        executable = sys.executable if command in ("python", "python3") else shutil.which(command)
        if executable is None:
            raise MCPError(f"commande « {command} » introuvable")

        LOG_DIR.mkdir(exist_ok=True)
        ## @brief File receiving the server's stderr.
        self._log = open(LOG_DIR / f"mcp_{name}.log", "w", encoding="utf-8")
        try:
            ## @brief The server's process.
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
        ## @brief Name and version announced by the server.
        self.server_info = result.get("serverInfo", {})
        self.notify("notifications/initialized")

    ## @brief Read the server's messages and route the answers.
    #
    # Runs in a thread. Answers are handed to the request waiting for their
    # id; requests from the server (ping...) are answered here; other
    # notifications (logs, progress) are ignored.
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

        # The server exited: wake up every request still waiting
        with self._lock:
            for waiting in self._pending.values():
                waiting.put({"error": {"message": "le serveur MCP s'est arrêté"}})

    ## @brief Write one JSON-RPC message on the server's stdin.
    #
    # @param message Message to send.
    def _send(self, message):
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise MCPError(f"serveur « {self.name} » injoignable : {error}") from error

    ## @brief Send a request and wait for its answer.
    #
    # @param method JSON-RPC method.
    # @param params Parameters of the method.
    # @return The "result" of the answer.
    # @exception MCPError On a JSON-RPC error, a timeout or a dead server.
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

    ## @brief Send a notification (a message that gets no answer).
    #
    # @param method JSON-RPC method.
    # @param params Parameters of the method.
    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    ## @brief List the server's tools, following the pagination.
    #
    # @return List of MCP tool definitions ("name", "description",
    #         "inputSchema", "annotations").
    def list_tools(self):
        tools = []
        cursor = None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else None)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    ## @brief Call a tool and return its result as text.
    #
    # @param name Name of the tool.
    # @param arguments Arguments, matching the tool's inputSchema.
    # @return A (text, is_error) pair.
    # @exception MCPError If the call itself fails (protocol, server down).
    def call_tool(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        parts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(f"[contenu {item.get('type')} non affiché]")
        return "\n".join(parts), bool(result.get("isError"))

    ## @brief Stop the server.
    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.process.kill()
        self._log.close()
