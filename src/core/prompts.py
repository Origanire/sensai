## @file prompts.py
# @brief Loading of prompts from the prompts/ directory.

import sys
from pathlib import Path

## @brief Directory containing the prompt files (.txt), at the project root.
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


## @brief Load a prompt from prompts/NAME.txt.
#
# Instructions meant for the model live in files rather than in the code:
# they can be adjusted or translated without touching the Python.
#
# @param name Name of the prompt, without the .txt extension.
# @return Contents of the file, stripped of leading and trailing whitespace.
# @exception SystemExit If the file is not found.
def load_prompt(name):
    path = PROMPTS_DIR / f"{name}.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print(f"[Erreur] prompt introuvable : {path}")
        sys.exit(1)
