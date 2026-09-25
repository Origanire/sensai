import requests
import json
import yaml


def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


class OllamaClient:
    def __init__(self, config=None):
        config = config or load_config()
        self.model = config["model"]
        self.url = config["ollama_url"]
        self.temperature = config.get("temperature", 0.7)

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
                        break
        except requests.exceptions.ChunkedEncodingError:
            print("\n[Erreur] La connexion a été coupée pendant la réponse.")
            return full_response if full_response else None
        except json.JSONDecodeError:
            print("\n[Erreur] Réponse invalide reçue d'Ollama.")
            return full_response if full_response else None

        print()
        return full_response
