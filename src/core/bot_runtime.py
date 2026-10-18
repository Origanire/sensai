"""Ce module transmet les événements du bot sans leur contenu et empêche de lancer deux bots en même temps."""

import fcntl
import json
import os
from pathlib import Path
import time

PREFIX = "SENSAI_EVENT "
LOCK_PATH = Path(__file__).resolve().parents[2] / ".bot.lock"


def emit(kind, **data):
    if os.environ.get("SENSAI_DASHBOARD") == "1":
        if os.environ.get("SENSAI_EVENT_FD"):
            try:
                os.write(int(os.environ["SENSAI_EVENT_FD"]),
                         (json.dumps({"kind": kind, "at": time.time(), **data}) + "\n").encode())
            except OSError:
                pass
            return
        # On ajoute un saut de ligne pour séparer cet événement du texte généré par le modèle.
        print("\n" + PREFIX + json.dumps({"kind": kind, "at": time.time(), **data}), flush=True)


def acquire_bot_lock(path=LOCK_PATH):
    handle = open(path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Un bot SENSAI fonctionne déjà. Arrête-le avant de le relancer.") from None
    return handle


def bot_is_running(path=LOCK_PATH):
    try:
        handle = acquire_bot_lock(path)
    except RuntimeError:
        return True
    handle.close()
    return False
