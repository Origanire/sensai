## @file ollama_client.py
# @brief HTTP client for the Ollama API (streaming chat, tool calls,
# structured output, embeddings, errors).

import json
import os

import requests
import yaml

## @brief Configuration file used when none is given.
DEFAULT_CONFIG_PATH = "config.yaml"
## @brief Environment variable overriding the configuration path; set by
# the CLI's --config option so every module reads the same file.
CONFIG_ENV = "SENSAI_CONFIG"
## @brief Embedding model used when the config does not name one.
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
## @brief Context size of the embedding model, in tokens.
EMBEDDING_CONTEXT = 512


## @brief Load the project configuration from a YAML file.
#
# @param path Path of the configuration file; if None, SENSAI_CONFIG or
#             config.yaml.
# @return Configuration dictionary (model, URL, temperature...).
def load_config(path=None):
    path = path or os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


## @brief HTTP client for the Ollama API (streaming chat, embeddings).
class OllamaClient:
    ## @brief Initialize the client from the configuration.
    #
    # @param config Configuration dictionary; if None, the default
    #                configuration is loaded automatically.
    def __init__(self, config=None):
        config = config or load_config()
        ## @brief Name of the Ollama model in use.
        self.model = os.environ.get("SENSAI_MODEL") or config["model"]
        ## @brief Local URL of the Ollama API.
        self.url = config["ollama_url"]
        ## @brief Model temperature (0 = deterministic, 1 = creative).
        self.temperature = config.get("temperature", 0.7)
        ## @brief Maximum number of tokens generated per answer.
        self.max_tokens = config.get("max_tokens")
        ## @brief Model used for the embeddings (RAG, semantic search).
        self.embedding_model = config.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
        ## @brief Tokens of the prompt sent on the last call (None before the first).
        self.last_prompt_tokens = None
        ## @brief Tokens generated on the last call (None before the first).
        self.last_response_tokens = None

    ## @brief Generation options sent with every chat request.
    #
    # @param temperature Temperature to use; if None, the one from the config.
    # @return The "options" dictionary of the Ollama API.
    def _options(self, temperature=None):
        options = {"temperature": self.temperature if temperature is None else temperature}
        if self.max_tokens:
            options["num_predict"] = self.max_tokens
        return options

    ## @brief Send a chat request, turning network errors into a message.
    #
    # A 404 from /api/chat means the model was never pulled: that case gets
    # its own message, with the command that fixes it.
    #
    # @param payload JSON body of the request.
    # @param stream True to read the answer as it is generated.
    # @return The HTTP response, or None on error (already printed).
    def _post_chat(self, payload, stream):
        try:
            response = requests.post(
                f"{self.url}/api/chat",
                json=payload,
                stream=stream,
                timeout=120
            )
            response.raise_for_status()
            return response
        except requests.exceptions.ConnectionError:
            print("\n[Erreur] Impossible de joindre Ollama. Vérifie qu'il est bien lancé (ollama serve).")
        except requests.exceptions.Timeout:
            print("\n[Erreur] Ollama met trop de temps à répondre.")
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                print(f"\n[Erreur] Modèle « {self.model} » introuvable. "
                      f"Télécharge-le avec : ollama pull {self.model}")
            else:
                print(f"\n[Erreur] Ollama a renvoyé une erreur : {e}")
        return None

    ## @brief Tell whether Ollama answers and the configured model is pulled.
    #
    # Called once at startup, so the user learns about a missing model
    # before typing a first message.
    #
    # @return None if everything is fine, otherwise the problem to display.
    def check_model(self):
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=5)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            return (f"Ollama injoignable sur {self.url}. "
                    f"Lance-le avec : ollama serve")

        names = {model["name"] for model in response.json().get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            return (f"Modèle « {self.model} » absent. "
                    f"Télécharge-le avec : ollama pull {self.model}")
        return None

    ## @brief Send a conversation to the model and print the response as it streams.
    #
    # Tokens are printed as they arrive, then the full response is
    # returned. Errors (Ollama unreachable, timeout, HTTP, dropped
    # connection, invalid JSON) are handled and printed to stderr.
    #
    # @param messages Conversation history (list of "role"/"content" dicts).
    # @return The model's full response, or None on error.
    def chat(self, messages):
        content, _ = self.chat_with_tools(messages, tools=None)
        return content

    ## @brief Stream a conversation that may end with tool calls.
    #
    # The model either answers in text (printed as it streams) or asks for
    # one or several tools: those calls are returned for the caller to run.
    #
    # @param messages Conversation history (list of "role"/"content" dicts).
    # @param tools Tool definitions in the Ollama format, or None.
    # @param echo False to collect the answer without printing it.
    # @return A (text, tool calls) pair; text is None on error, tool calls
    #         is a list of {"name", "arguments"} dicts, possibly empty.
    def chat_with_tools(self, messages, tools=None, echo=True):
        if not messages:
            print("[Erreur] Aucun message à envoyer.")
            return None, []

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": self._options()
        }
        if tools:
            payload["tools"] = tools

        response = self._post_chat(payload, stream=True)
        if response is None:
            return None, []

        full_response = ""
        tool_calls = []

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                message = chunk.get("message", {})
                token = message.get("content", "")
                if echo and token:
                    print(token, end="", flush=True)
                full_response += token

                for call in message.get("tool_calls") or []:
                    function = call.get("function", {})
                    tool_calls.append({
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments") or {},
                    })

                if chunk.get("done", False):
                    self.last_prompt_tokens = chunk.get("prompt_eval_count")
                    self.last_response_tokens = chunk.get("eval_count")
                    break
        except requests.exceptions.ChunkedEncodingError:
            print("\n[Erreur] La connexion a été coupée pendant la réponse.")
            return (full_response or None), tool_calls
        except json.JSONDecodeError:
            print("\n[Erreur] Réponse invalide reçue d'Ollama.")
            return (full_response or None), tool_calls

        if echo and full_response:
            print()
        return full_response, tool_calls

    ## @brief Send a conversation to the model and return the response without printing it.
    #
    # Unlike chat(), the call is not streamed and nothing is written to
    # stdout. Meant for internal agent calls (extraction, rephrasing,
    # classification) whose result must not appear in the user interface.
    #
    # @param messages Conversation history (list of "role"/"content" dicts).
    # @param temperature Temperature to use; if None, the one from the config.
    # @param format JSON schema the answer must follow (structured output),
    #               or None for free text.
    # @return The model's full response, or None on error.
    def chat_silent(self, messages, temperature=None, format=None):
        if not messages:
            print("[Erreur] Aucun message à envoyer.")
            return None

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self._options(temperature)
        }
        if format is not None:
            payload["format"] = format

        response = self._post_chat(payload, stream=False)
        if response is None:
            return None

        try:
            data = response.json()
            self.last_prompt_tokens = data.get("prompt_eval_count")
            self.last_response_tokens = data.get("eval_count")
            return data["message"]["content"]
        except (json.JSONDecodeError, KeyError):
            print("\n[Erreur] Réponse invalide reçue d'Ollama.")
            return None

    ## @brief Ask for a JSON object that follows a schema, and parse it.
    #
    # Ollama constrains the generation to the schema (structured output),
    # so the answer is valid JSON; the caller still checks the values.
    #
    # @param messages Conversation (list of "role"/"content" dicts).
    # @param schema JSON schema of the expected object.
    # @return The parsed object, or None on error.
    def chat_json(self, messages, schema):
        text = self.chat_silent(messages, temperature=0, format=schema)
        if text is None:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print("[Erreur] Le modèle n'a pas renvoyé un JSON valide.")
            return None
        return data if isinstance(data, dict) else None

    ## @brief Generate the embedding of a text.
    #
    # @param text Text to vectorize.
    # @return The embedding vector, or None on error.
    def embed(self, text):
        # A chunk is ~150 tokens: a small context keeps the embedding model
        # light enough to stay loaded next to the chat model, instead of
        # Ollama swapping both in and out of memory on every message
        payload = {
            "model": self.embedding_model,
            "prompt": text,
            "options": {"num_ctx": EMBEDDING_CONTEXT},
        }

        try:
            response = requests.post(
                f"{self.url}/api/embeddings",
                json=payload,
                timeout=90
            )
            response.raise_for_status()
            return response.json()["embedding"]
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                print(f"[Erreur] Modèle d'embedding « {self.embedding_model} » absent : "
                      f"ollama pull {self.embedding_model}")
            else:
                print(f"[Erreur] Impossible de générer l'embedding : {e}")
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            print(f"[Erreur] Impossible de générer l'embedding : {e}")
        return None
