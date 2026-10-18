# Ce module charge les consignes enregistrées dans le dossier prompts.

import sys
from pathlib import Path

# Ce dossier contient les fichiers de consignes du projet.
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


# Cette fonction lit un fichier de consignes pour pouvoir les modifier sans changer le code Python.
def load_prompt(name):
    path = PROMPTS_DIR / f"{name}.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print(f"[Erreur] prompt introuvable : {path}")
        sys.exit(1)
