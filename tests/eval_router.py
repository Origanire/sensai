# Ce script mesure le choix du routeur avec des questions différentes de ses exemples. Il nécessite Ollama.

import sys
import time

from src.agents.router import route
from src.core.ollama_client import OllamaClient

# Ces messages sont associés à l’agent qui devrait leur répondre.
CASES = [
    ("coucou toi", "chat"),
    ("t'es un bot ou un humain ?", "chat"),
    ("raconte une blague", "chat"),
    ("tu te rappelles ce que je t'ai dit hier ?", "chat"),
    ("bien joué le boss !", "chat"),
    ("le stream finit à quelle heure ?", "docs"),
    ("c'est quoi ton micro ?", "docs"),
    ("on peut spoil ?", "docs"),
    ("il faut combien de subs pour le stream de 12h ?", "docs"),
    ("tu joues à quoi en ce moment ?", "docs"),
    ("y a un discord ?", "docs"),
    ("c'est quand la sortie de Silksong ?", "web"),
    ("qui a gagné la ligue des champions 2026 ?", "web"),
    ("quel temps il fait à Marseille ?", "web"),
    ("c'est quoi les nouveautés de la dernière maj de Fortnite ?", "web"),
    ("combien coûte une RTX 5090 ?", "web"),
]


if __name__ == "__main__":
    client = OllamaClient()
    if len(sys.argv) > 1:
        client.model = sys.argv[1]

    correct = 0
    start = time.time()
    for question, expected in CASES:
        chosen = route(question, client)
        correct += chosen == expected
        print(f"{'OK ' if chosen == expected else 'XX '} attendu {expected:4} obtenu {chosen:4} | {question}")
    print(f"\n{client.model} : {correct}/{len(CASES)} bien routés, "
          f"{(time.time() - start) / len(CASES):.2f} s par message")
