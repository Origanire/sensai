"""Validated dashboard settings layered over the existing chat configuration."""

import os
from pathlib import Path
import re
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_CONFIG = ROOT / "config/dashboard.yaml"
DEFAULTS = {
    "reply_cooldown": 15,
    "mentions_only": True,
    "stream_topic": "",
    "stream_context": "",
    "tone": "friendly",
    "reply_length": "short",
    "avoid_spoilers": True,
}
TONES = {"friendly": "amical et naturel", "calm": "calme et discret", "energetic": "enthousiaste"}


def load_bot_settings(root=ROOT):
    root = Path(root)
    with (root / "config/chat_agent.yaml").open() as source:
        settings = {**DEFAULTS, **(yaml.safe_load(source) or {})}
    path = root / "config/dashboard.yaml"
    if path.exists():
        settings.update(validate_settings(yaml.safe_load(path.read_text()) or {}))
    return settings


def validate_settings(values):
    if not isinstance(values, dict):
        raise ValueError("Les réglages doivent être un objet.")
    allowed = set(DEFAULTS) | {"channel", "trigger", "bot_name"}
    if set(values) - allowed:
        raise ValueError("Un réglage non reconnu a été envoyé.")
    result = dict(values)
    for key, value in result.items():
        if key in {"mentions_only", "avoid_spoilers"}:
            if type(value) is not bool:
                raise ValueError("Le choix doit être activé ou désactivé.")
        elif key == "reply_cooldown":
            if type(value) is not int or not 0 <= value <= 120:
                raise ValueError("La pause doit être comprise entre 0 et 120 secondes.")
        else:
            limit = 3000 if key == "stream_context" else 120
            if not isinstance(value, str) or len(value) > limit or "\x00" in value:
                raise ValueError(f"Valeur invalide pour {key}.")
            result[key] = value.strip()
    if "channel" in result:
        result["channel"] = result["channel"].removeprefix("#").lower()
        if not re.fullmatch(r"[a-z0-9_]{3,25}", result["channel"]):
            raise ValueError("Saisis le pseudo de la chaîne, sans URL.")
    if "trigger" in result and not re.fullmatch(r"@[a-zA-Z0-9_]{3,25}", result["trigger"]):
        raise ValueError("La mention doit ressembler à @LumiTheBoat.")
    if "bot_name" in result and not re.fullmatch(r"[a-zA-Z0-9_]{3,25}", result["bot_name"]):
        raise ValueError("Nom du bot invalide.")
    if "tone" in result and result["tone"] not in TONES:
        raise ValueError("Ton de conversation inconnu.")
    if "reply_length" in result and result["reply_length"] not in {"short", "brief"}:
        raise ValueError("Longueur de réponse inconnue.")
    return result


def public_settings(settings):
    return {key: settings[key] for key in (*DEFAULTS, "channel", "trigger", "bot_name") if key in settings}


def save_bot_settings(values, root=ROOT):
    values = validate_settings(values)
    path = Path(root) / "config/dashboard.yaml"
    fd, temporary = tempfile.mkstemp(prefix=".dashboard-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write("# Réglages du dashboard local. Appliqués aux prochains messages.\n")
            yaml.safe_dump(values, output, allow_unicode=True, sort_keys=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bot_persona(base, settings):
    """The dashboard adds context without replacing the existing safety rules."""
    text = base.replace("{bot_name}", settings.get("bot_name", "Sensai"))
    text += f"\nTon : {TONES[settings['tone']]}."
    text += "\nRéponds en une phrase courte." if settings["reply_length"] == "brief" else "\nRéponds en une ou deux phrases courtes."
    if settings["avoid_spoilers"]:
        text += "\nNe révèle pas de spoilers sur les jeux, films ou séries."
    if settings["stream_topic"]:
        text += "\nSujet du live indiqué par le streamer : " + settings["stream_topic"]
    if settings["stream_context"]:
        text += "\nInformations fournies par le streamer :\n" + settings["stream_context"]
    return text
