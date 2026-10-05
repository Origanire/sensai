## @file obs.py
# @brief OBS connector: updates a text source through obs-websocket (v5).
#
# Every call opens its own short connection: OBS may be started or closed
# during the stream, and a failure only costs the call that hit it. No
# function of this module raises: errors are printed and reported through
# the return value, so OBS can never crash the calling agent.

import logging
import os
import socket

import obsws_python as obs
from obsws_python.error import OBSSDKError, OBSSDKRequestError
from websocket import WebSocketConnectionClosedException

## @brief Settings used when config.yaml has no "obs" section.
DEFAULT_SETTINGS = {
    "enabled": False,
    "host": "localhost",
    "port": 4455,
    "password": "",
    "source_name": "SensaiOverlay",
}
## @brief Time allowed to reach OBS, in seconds.
TIMEOUT = 3
## @brief obs-websocket error code when the input does not exist.
RESOURCE_NOT_FOUND = 600

# obsws-python prints a full traceback when OBS is closed, and logs the
# password in clear text: its messages are replaced by ours. Its loggers
# are children of "obsws_python", so they are silenced at that level.
_obsws_logger = logging.getLogger("obsws_python")
_obsws_logger.addHandler(logging.NullHandler())
_obsws_logger.propagate = False


## @brief Read the "obs" section of the configuration.
#
# The OBS_WEBSOCKET_PASSWORD environment variable (e.g. from .env), when
# set, overrides the password of config.yaml, so it does not have to be
# committed.
#
# @param config Configuration dictionary loaded from config.yaml.
# @return Dict "enabled", "host", "port", "password", "source_name",
#         completed with DEFAULT_SETTINGS for any missing key.
def load_obs_settings(config):
    section = (config or {}).get("obs") or {}
    settings = DEFAULT_SETTINGS | {k: v for k, v in section.items() if v is not None}
    settings["password"] = os.environ.get("OBS_WEBSOCKET_PASSWORD", settings["password"])
    return settings


## @brief Tell quickly whether something listens on OBS's websocket port.
#
# A plain TCP connection, much cheaper than the websocket handshake: used
# to skip work (web search, model) whose result could not be displayed.
#
# @param host Host of obs-websocket.
# @param port Port of obs-websocket.
# @return True if the port accepts connections.
def obs_reachable(host="localhost", port=4455):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


## @brief Replace the text of an existing OBS text source.
#
# Works with "Text (GDI+)" and "Text (FreeType 2)" sources, which both
# store their content in the "text" setting. In OBS, inputs are global:
# the source is found by name, whatever the current scene.
#
# @param source_name Name of the text source, as shown in OBS.
# @param text New text.
# @param host Host of obs-websocket.
# @param port Port of obs-websocket.
# @param password obs-websocket password, empty if authentication is off.
# @return True if OBS applied the text, False otherwise (error printed).
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
        # OBS closes the websocket on a wrong password
        print("[OBS] OBS a fermé la connexion : mot de passe WebSocket incorrect ?")
    except Exception as error:
        print(f"[OBS] OBS injoignable sur {host}:{port} (OBS lancé, serveur WebSocket "
              f"activé ?) : {type(error).__name__}")
    return False
