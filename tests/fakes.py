# Ce module simule Ollama avec des réponses prévues pour rendre les tests reproductibles et indépendants du modèle.


# Cette classe fournit les réponses préparées pour les tests.
class FakeClient:
    # On prépare les réponses texte, JSON, outils et vecteurs qui seront renvoyés dans l’ordre.
    def __init__(self, json_answers=None, texts=None, tool_calls=None, vectors=None):
        self.json_answers = list(json_answers or [])
        self.texts = list(texts or [])
        self.tool_calls = list(tool_calls or [])
        self.vectors = vectors or {}
        self.embedding_model = "fake-embed"
        self.last_prompt_tokens = 0
        # On garde les messages reçus pour vérifier les consignes envoyées au modèle.
        self.requests = []

    def chat_json(self, messages, schema):
        self.requests.append(messages)
        return self.json_answers.pop(0) if self.json_answers else None

    def chat_silent(self, messages, temperature=None, format=None):
        self.requests.append(messages)
        return self.texts.pop(0) if self.texts else None

    def chat(self, messages):
        return self.chat_silent(messages)

    def chat_with_tools(self, messages, tools=None, echo=True):
        self.requests.append(list(messages))
        calls = self.tool_calls.pop(0) if (tools and self.tool_calls) else []
        text = "" if calls else (self.texts.pop(0) if self.texts else None)
        return text, calls

    def embed(self, text):
        for key, vector in self.vectors.items():
            if key in text:
                return vector
        return [0.0, 0.0, 1.0]
