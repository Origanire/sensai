## @file ollama_client.py
# @brief Client HTTP vers l'API Ollama (chat en streaming, embeddings, erreurs).

import requests
import json
import yaml


## @brief Charge la configuration du projet depuis un fichier YAML.
#
# @param path Chemin du fichier de configuration.
# @return Dictionnaire de configuration (modèle, URL, température...).
def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


## @brief Client HTTP pour l'API Ollama (chat en streaming, embeddings).
class OllamaClient:
    ## @brief Initialise le client à partir de la configuration.
    #
    # @param config Dictionnaire de configuration ; s'il est None, la
    #                configuration par défaut est chargée automatiquement.
    def __init__(self, config=None):
        config = config or load_config()
        ## @brief Nom du modèle Ollama utilisé.
        self.model = config["model"]
        ## @brief URL locale de l'API Ollama.
        self.url = config["ollama_url"]
        ## @brief Température du modèle (0 = déterministe, 1 = créatif).
        self.temperature = config.get("temperature", 0.7)
        ## @brief Tokens du prompt envoyé lors du dernier appel (None avant le premier).
        self.last_prompt_tokens = None
        ## @brief Tokens générés lors du dernier appel (None avant le premier).
        self.last_response_tokens = None

    ## @brief Envoie une conversation au modèle et affiche la réponse en streaming.
    #
    # Les tokens sont affichés au fur et à mesure de leur réception, puis
    # la réponse complète est renvoyée. Les erreurs (Ollama injoignable,
    # timeout, HTTP, connexion coupée, JSON invalide) sont gérées et
    # affichées sur la sortie d'erreur.
    #
    # @param messages Historique de conversation (liste de dicts "role"/"content").
    # @return Réponse complète du modèle, ou None en cas d'erreur.
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

    ## @brief Envoie une conversation au modèle et renvoie la réponse sans l'afficher.
    #
    # Contrairement à chat(), l'appel n'est pas en streaming et rien n'est
    # écrit sur la sortie standard. Destiné aux appels internes des agents
    # (extraction, reformulation, classification) dont le résultat ne doit
    # pas apparaître dans l'interface utilisateur.
    #
    # @param messages Historique de conversation (liste de dicts "role"/"content").
    # @param temperature Température à utiliser ; si None, celle de la config.
    # @return Réponse complète du modèle, ou None en cas d'erreur.
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


    ## @brief Génère l'embedding d'un texte via le modèle nomic-embed-text.
    #
    # @param text Texte à vectoriser.
    # @return Vecteur d'embedding, ou None en cas d'erreur.
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
