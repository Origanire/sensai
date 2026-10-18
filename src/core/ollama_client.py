# Ce module communique avec Ollama pour les réponses, les outils, le JSON et les vecteurs de recherche.

import json
import os

import requests
import yaml

# Ce fichier est utilisé si aucun autre réglage n’est fourni.
DEFAULT_CONFIG_PATH = "config.yaml"
# Cette variable d’environnement permet aux modules de partager le fichier choisi avec --config.
CONFIG_ENV = "SENSAI_CONFIG"
# Ce modèle sert aux recherches si aucun autre n’est configuré.
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
# Cette valeur limite le contexte du modèle de recherche en tokens.
EMBEDDING_CONTEXT = 512


# Cette fonction charge les réglages YAML du projet, depuis le chemin donné ou celui de l’environnement.
def load_config(path=None):
    path = path or os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Cette classe gère les appels HTTP à Ollama.
class OllamaClient:
    # On prépare le client avec les réglages fournis ou ceux du fichier par défaut.
    def __init__(self, config=None):
        config = config or load_config()
        # Ce nom indique le modèle Ollama utilisé.
        self.model = os.environ.get("SENSAI_MODEL") or config["model"]
        # Cette adresse permet de joindre Ollama en local.
        self.url = config["ollama_url"]
        # La température règle la variation des réponses du modèle.
        self.temperature = config.get("temperature", 0.7)
        # Cette valeur limite le nombre de tokens générés par réponse.
        self.max_tokens = config.get("max_tokens")
        self.think = config.get("think")
        self.context_window = config.get("context_window")
        # Ce modèle calcule les vecteurs utilisés pour rechercher dans les documents.
        self.embedding_model = config.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
        # On conserve le nombre de tokens du dernier contexte envoyé.
        self.last_prompt_tokens = None
        # On conserve le nombre de tokens générés lors du dernier appel.
        self.last_response_tokens = None

    # Cette fonction prépare les options envoyées au modèle pour chaque réponse.
    def _options(self, temperature=None):
        options = {"temperature": self.temperature if temperature is None else temperature}
        if self.context_window:
            options["num_ctx"] = self.context_window
        if self.max_tokens:
            options["num_predict"] = self.max_tokens
        return options

    # Cette fonction envoie la requête à Ollama et transforme les erreurs réseau ou de modèle absent en messages lisibles.
    def _post_chat(self, payload, stream):
        if self.think is not None:
            payload["think"] = self.think
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

    # Cette fonction vérifie au démarrage qu’Ollama répond et que le modèle demandé est installé.
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

    # Cette fonction affiche les morceaux de réponse dès leur arrivée, puis renvoie la réponse complète.
    def chat(self, messages):
        content, _ = self.chat_with_tools(messages, tools=None)
        return content

    # Cette fonction laisse le modèle répondre ou demander des outils. Les appels demandés sont renvoyés pour être exécutés.
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

    # Cette fonction récupère une réponse sans l’afficher, pour les traitements internes du bot.
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

    # Cette fonction demande un JSON conforme au schéma et le lit. Les valeurs doivent encore être vérifiées par l’appelant.
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

    # Cette fonction transforme un texte en vecteur pour les recherches.
    def embed(self, text):
        # Un petit contexte limite la mémoire utilisée par le modèle de recherche pour le garder chargé avec le modèle de conversation.
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
