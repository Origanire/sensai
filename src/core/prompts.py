## @file prompts.py
# @brief Chargement des prompts depuis le dossier prompts/.

import sys
from pathlib import Path

## @brief Dossier contenant les fichiers de prompts (.txt), à la racine du projet.
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


## @brief Charge un prompt depuis prompts/NOM.txt.
#
# Les instructions destinées au modèle vivent dans des fichiers plutôt que
# dans le code : on peut les ajuster ou les traduire sans toucher au Python.
#
# @param name Nom du prompt, sans l'extension .txt.
# @return Contenu du fichier, débarrassé des espaces de début et de fin.
# @exception SystemExit Si le fichier est introuvable.
def load_prompt(name):
    path = PROMPTS_DIR / f"{name}.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print(f"[Erreur] prompt introuvable : {path}")
        sys.exit(1)
