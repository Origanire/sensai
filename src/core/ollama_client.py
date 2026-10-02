## @file ollama_client.py
# @brief HTTP client for the Ollama API (streaming chat, embeddings, errors).

import requests
import json
import yaml


## @brief Load the project configuration from a YAML file.
#
# @param path Path of the configuration file.
# @return Configuration dictionary (model, URL, temperature...).
def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


## @brief HTTP client for the Ollama API (streaming chat, embeddings).
class OllamaClient:
    ## @brief Initialize the client from the configuration.
    #
    # @param config Configuration dictionary; if None, the default
    #                configuration is loaded automatically.
    def __init__(self, config=None):
        config = config or load_config()
        ## @brief Name of the Ollama model in use.
        self.model = config["model"]
        ## @brief Local URL of the Ollama API.
        self.url = config["ollama_url"]
        ## @brief Model temperature (0 = deterministic, 1 = creative).
        self.temperature = config.get("temperature", 0.7)
        ## @brief Tokens of the prompt sent on the last call (None before the first).
        self.last_prompt_tokens = None
        ## @brief Tokens generated on the last call (None before the first).
        self.last_response_tokens = None

    ## @brief Send a conversation to the model and print the response as it streams.
    #
    # Tokens are printed as they arrive, then the full response is
    # returned. Errors (Ollama unreachable, timeout, HTTP, dropped
    # connection, invalid JSON) are handled and printed to stderr.
    #
    # @param messages Conversation history (list of "role"/"content" dicts).
    # @return The model's full response, or None on error.
    def chat(self, messages):
        if not messages:
            print("[Erreur] Aucun message à envoyer.")
            return None

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.temperature
            }
        }

        try:
            response = requests.post(
                f"{self.url}/api/chat",
                json=payload,
                stream=True,
                timeout=60
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            print("\n[Erreur] Impossible de joindre Ollama. Vérifie qu'il est bien lancé (ai-start).")
            return None
        except requests.exceptions.Timeout:
            print("\n[Erreur] Ollama met trop de temps à répondre.")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"\n[Erreur] Ollama a renvoyé une erreur : {e}")
            return None

        full_response = ""

        try:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    token = chunk["message"]["content"]
                    print(token, end="", flush=True)
                    full_response += token

                    if chunk.get("done", False):
                        self.last_prompt_tokens = chunk.get("prompt_eval_count")
                        self.last_response_tokens = chunk.get("eval_count")
                        break
        except requests.exceptions.ChunkedEncodingError:
            print("\n[Erreur] La connexion a été coupée pendant la réponse.")
            return full_response if full_response else None
        except json.JSONDecodeError:
            print("\n[Erreur] Réponse invalide reçue d'Ollama.")
            return full_response if full_response else None

        print()
        return full_response

    ## @brief Send a conversation to the model and return the response without printing it.
    #
    # Unlike chat(), the call is not streamed and nothing is written to
    # stdout. Meant for internal agent calls (extraction, rephrasing,
    # classification) whose result must not appear in the user interface.
    #
    # @param messages Conversation history (list of "role"/"content" dicts).
    # @param temperature Temperature to use; if None, the one from the config.
    # @return The model's full response, or None on error.
    def chat_silent(self, messages, temperature=None):
        if not messages:
            print("[Erreur] Aucun message à envoyer.")
            return None

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature if temperature is None else temperature
            }
        }

        try:
            response = requests.post(
                f"{self.url}/api/chat",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            print("\n[Erreur] Impossible de joindre Ollama. Vérifie qu'il est bien lancé (ai-start).")
            return None
        except requests.exceptions.Timeout:
            print("\n[Erreur] Ollama met trop de temps à répondre.")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"\n[Erreur] Ollama a renvoyé une erreur : {e}")
            return None

        try:
            data = response.json()
            self.last_prompt_tokens = data.get("prompt_eval_count")
            self.last_response_tokens = data.get("eval_count")
            return data["message"]["content"]
        except (json.JSONDecodeError, KeyError):
            print("\n[Erreur] Réponse invalide reçue d'Ollama.")
            return None


    ## @brief Generate the embedding of a text via the nomic-embed-text model.
    #
    # @param text Text to vectorize.
    # @return The embedding vector, or None on error.
    def embed(self, text):
        payload = {
            "model": "nomic-embed-text",
            "prompt": text
        }

        try:
            response = requests.post(
                f"{self.url}/api/embeddings",
                json=payload,
                timeout=30
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"[Erreur] Impossible de générer l'embedding : {e}")
            return None

        data = response.json()
        return data["embedding"]
