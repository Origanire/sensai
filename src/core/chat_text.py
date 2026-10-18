"""Ce module applique la règle commune aux messages Twitch : aucun hyperlien dans le texte envoyé."""
import re
import textwrap

MAX_CHAT_CHARACTERS = 500
PING_REPLY = "Que me veux-tu ? 😄"
LINK = re.compile(r"(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>]+|(?<![\w@])(?:[\w-]+\.)+[a-zA-Z]{2,63}(?::\d+)?(?:/[^\s<>]*)?", re.I)


def strip_links(text):
    # On garde le titre lisible d’un lien Markdown, mais on retire son adresse.
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = LINK.sub("", text)
    text = re.sub(r"(?:[·|—-]\s*)?(?:Sources?|Résultat consulté)\s*:\s*$", "", text, flags=re.I)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\s+([.,])", r"\1", text)
    return " ".join(text.split()).strip(" ·|")


def fit_chat_text(text, limit=MAX_CHAT_CHARACTERS):
    text = strip_links(text)
    if not text:
        text = "Je n’ai pas de réponse utile à ajouter pour le moment."
    return text if len(text) <= limit else textwrap.shorten(text, limit, placeholder="…")
