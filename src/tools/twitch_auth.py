"""Ce module connecte le compte bot avec l’autorisation officielle Twitch. Il valide les jetons et les sauvegarde dans .env sans les afficher."""

import argparse
import os
from pathlib import Path
import re
import tempfile
import time

from dotenv import dotenv_values
import requests

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
OAUTH_URL = "https://id.twitch.tv/oauth2"
SCOPES = {"chat:read", "chat:edit"}


class AuthError(Exception):
    """Cette erreur peut être affichée sans révéler les identifiants de connexion."""


class ExpiredToken(AuthError):
    """Seuls les identifiants expirés ou invalides peuvent être renouvelés ici."""


def request_json(method, endpoint, **kwargs):
    """On ne place jamais le contenu des requêtes ni leurs en-têtes dans les erreurs."""
    try:
        response = requests.request(
            method, f"{OAUTH_URL}/{endpoint}", timeout=20,
            allow_redirects=False, **kwargs,
        )
        body = response.json()
    except (requests.RequestException, ValueError):
        raise AuthError("Twitch est injoignable ou sa réponse est illisible. Réessaie.") from None
    if not isinstance(body, dict):
        raise AuthError("Réponse Twitch inattendue. Réessaie.")
    return response.status_code, body


def validate_token(token, client_id, bot):
    """On vérifie le compte bot, l’application et les autorisations demandées."""
    status, identity = request_json(
        "GET", "validate", headers={"Authorization": f"OAuth {token}"},
    )
    if status == 401:
        raise ExpiredToken("Le jeton est expiré ou refusé. Relance la connexion Twitch.")
    if status != 200:
        raise AuthError("La vérification Twitch a échoué. Réessaie.")
    if identity.get("client_id") != client_id:
        raise AuthError("Ce jeton appartient à une autre application Twitch.")
    if identity.get("login", "").lower() != bot.lower():
        raise AuthError(
            "Le compte autorisé n'est pas le compte bot attendu. "
            "Reconnecte-toi avec le compte bot dans ton navigateur, puis réessaie."
        )
    if not SCOPES.issubset(identity.get("scopes") or []):
        raise AuthError("Les permissions de lecture et d'écriture du chat sont nécessaires.")
    if identity.get("expires_in", 0) <= 0:
        raise ExpiredToken("Le jeton Twitch a expiré. Relance la connexion.")
    return identity


def save_settings(values, path=ENV_PATH):
    """Cette fonction remplace uniquement nos clés dans .env. Elle protège le fichier et refuse les caractères qui pourraient casser son format."""
    path = Path(path)
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z_]+", key) or not re.fullmatch(r"[a-zA-Z0-9:._~%/+=-]+", str(value)):
            raise AuthError("Valeur de configuration Twitch invalide.")
    remaining = dict(values)
    lines = []
    for line in path.read_text().splitlines() if path.exists() else []:
        match = re.match(r"\s*(?:export\s+)?([A-Z_]+)\s*=", line)
        key = match.group(1) if match else None
        if key in values:
            if key in remaining:
                lines.append(f"{key}={remaining.pop(key)}")
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    fd, name = tempfile.mkstemp(prefix=".twitch-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write("\n".join(lines) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def refresh_authorization(client_id, bot, refresh_token, path=ENV_PATH):
    """Cette fonction renouvelle une autorisation existante sans demander de nouveaux droits."""
    if not refresh_token:
        raise AuthError("Reconnecte le compte Twitch depuis le dashboard.")
    status, result = request_json("POST", "token", data={
        "client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh_token,
    })
    if status != 200 or not result.get("access_token") or not result.get("refresh_token"):
        raise AuthError("L'autorisation Twitch doit être renouvelée. Utilise Reconnecter Twitch.")
    identity = validate_token(result["access_token"], client_id, bot)
    save_settings({"TWITCH_OAUTH_TOKEN": result["access_token"],
                   "TWITCH_REFRESH_TOKEN": result["refresh_token"]}, path)
    return identity


def authorize(client_id, bot, path=ENV_PATH, on_device=None):
    """Cette fonction attend l’autorisation dans le navigateur, puis valide et sauvegarde les jetons."""
    status, device = request_json("POST", "device", data={
        "client_id": client_id, "scopes": " ".join(sorted(SCOPES)),
    })
    if status != 200:
        raise AuthError("Demande refusée par Twitch. Vérifie le Client ID et le type Public de l'application.")
    if not all(device.get(key) for key in ("device_code", "user_code", "expires_in")):
        raise AuthError("La réponse d'activation Twitch est incomplète.")
    interval = max(5, int(device.get("interval", 5)))
    deadline = time.monotonic() + int(device["expires_in"])
    if on_device:
        on_device({"user_code": device["user_code"], "expires_in": int(device["expires_in"])})
    else:
        print(f"Connecte-toi avec {bot} dans ton navigateur habituel.", flush=True)
        print("Ouvre https://www.twitch.tv/activate", flush=True)
        print(f"Code à saisir : {device['user_code']}", flush=True)
        print(f"Valable {int(device['expires_in']) // 60} minutes. Autorise la lecture et l'envoi de messages.", flush=True)
        print("En attente de ton autorisation…", flush=True)
    while time.monotonic() < deadline:
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
        if time.monotonic() >= deadline:
            break
        status, result = request_json("POST", "token", data={
            "client_id": client_id,
            "device_code": device["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "scopes": " ".join(sorted(SCOPES)),
        })
        if status == 200:
            token = result.get("access_token")
            refresh = result.get("refresh_token")
            if not token or not refresh:
                raise AuthError("Twitch n'a pas renvoyé les identifiants attendus.")
            validate_token(token, client_id, bot)
            save_settings({
                "TWITCH_CLIENT_ID": client_id,
                "TWITCH_BOT_USERNAME": bot.lower(),
                "TWITCH_OAUTH_TOKEN": token,
                "TWITCH_REFRESH_TOKEN": refresh,
            }, path)
            print(f"Connexion validée pour {bot}. Identifiants enregistrés localement dans .env.", flush=True)
            return
        error = result.get("message") or result.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down" or status == 429:
            interval += 5
            continue
        if error == "access_denied":
            raise AuthError("Autorisation refusée. Aucun identifiant n'a été modifié.")
        raise AuthError("Connexion interrompue ou code expiré. Relance la commande.")
    raise AuthError("Le code d'activation a expiré. Relance la commande pour en obtenir un nouveau.")


def main():
    parser = argparse.ArgumentParser(description="Connecter le compte bot Twitch à SENSAI.")
    parser.add_argument("--client-id", help="Client ID public de l'application Twitch")
    parser.add_argument("--bot", help="Pseudo du compte bot (pas celui du streamer)")
    parser.add_argument("--check", action="store_true", help="Vérifier le jeton enregistré sans publier de message")
    args = parser.parse_args()
    settings = {**dotenv_values(ENV_PATH), **os.environ}
    client_id = args.client_id or settings.get("TWITCH_CLIENT_ID", "")
    bot = args.bot or settings.get("TWITCH_BOT_USERNAME", "")
    if not re.fullmatch(r"[a-zA-Z0-9]+", client_id or "") or not re.fullmatch(r"[a-zA-Z0-9_]+", bot or ""):
        parser.error("Indique --client-id et --bot, ou renseigne ces valeurs dans .env.")
    try:
        if args.check:
            token = (settings.get("TWITCH_OAUTH_TOKEN") or "").removeprefix("oauth:")
            if not token:
                raise AuthError("Aucun jeton enregistré. Lance la commande sans --check.")
            identity = validate_token(token, client_id, bot)
            print(f"Compte {bot} validé, lecture et écriture autorisées, validité restante : {identity['expires_in'] // 60} min.")
        else:
            authorize(client_id, bot)
    except AuthError as error:
        print(f"[Twitch] {error}")
        return 1
    except KeyboardInterrupt:
        print("\nConnexion annulée.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
