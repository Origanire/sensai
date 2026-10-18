# Ce module met à jour une source texte OBS par WebSocket. Chaque appel utilise sa propre connexion et gère les échecs.

import logging
import os
import socket

import obsws_python as obs
from obsws_python.error import OBSSDKError, OBSSDKRequestError
from websocket import WebSocketConnectionClosedException

# Ces réglages sont utilisés si la section OBS est absente.
DEFAULT_SETTINGS = {
    "enabled": False,
    "host": "localhost",
    "port": 4455,
    "password": "",
    "source_name": "SensaiOverlay",
}
# Ce délai limite l’attente d’une connexion à OBS.
TIMEOUT = 3
# Ce code d’erreur indique que la source OBS n’existe pas.
RESOURCE_NOT_FOUND = 600

# On remplace les journaux de la bibliothèque OBS pour éviter d’afficher le mot de passe ou des traces inutiles.
_obsws_logger = logging.getLogger("obsws_python")
_obsws_logger.addHandler(logging.NullHandler())
_obsws_logger.propagate = False


# Cette fonction charge les réglages OBS. Le mot de passe de l’environnement est prioritaire sur celui du fichier.
def load_obs_settings(config):
    section = (config or {}).get("obs") or {}
    settings = DEFAULT_SETTINGS | {k: v for k, v in section.items() if v is not None}
    settings["password"] = os.environ.get("OBS_WEBSOCKET_PASSWORD", settings["password"])
    return settings


# Cette fonction vérifie rapidement si le port OBS répond avant de lancer un traitement inutile.
def obs_reachable(host="localhost", port=4455):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


# Cette fonction remplace le texte d’une source OBS existante, retrouvée grâce à son nom.
def update_text_source(source_name, text, host="localhost", port=4455, password=""):
    try:
        with obs.ReqClient(host=host, port=port, password=password, timeout=TIMEOUT) as client:
            client.set_input_settings(source_name, {"text": text}, True)
        return True
    except OBSSDKRequestError as error:
        if error.code == RESOURCE_NOT_FOUND:
            print(f"[OBS] Source « {source_name} » introuvable : crée une source Texte "
                  f"avec ce nom dans OBS.")
        else:
            print(f"[OBS] Requête refusée par OBS : {error}")
    except OBSSDKError as error:
        print(f"[OBS] Connexion refusée par OBS : {error}")
    except WebSocketConnectionClosedException:
        # OBS ferme la connexion si le mot de passe est incorrect.
        print("[OBS] OBS a fermé la connexion : mot de passe WebSocket incorrect ?")
    except Exception as error:
        print(f"[OBS] OBS injoignable sur {host}:{port} (OBS lancé, serveur WebSocket "
              f"activé ?) : {type(error).__name__}")
    return False
