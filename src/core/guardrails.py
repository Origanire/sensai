# Ce module filtre les messages et masque certaines données personnelles avant les appels au modèle et l’envoi des réponses.

import re
import unicodedata
from dataclasses import dataclass, field

from src.core.ollama_client import load_config

# Ce fichier contient les réglages des filtres.
GUARDRAILS_CONFIG = "config/guardrails.yaml"

# Ces caractères invisibles peuvent servir à contourner les filtres.
ZERO_WIDTH = re.compile("[​-‏⁠⁦-⁩﻿­]")
# Ces caractères de contrôle peuvent masquer du texte ou inverser son affichage.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u202a\u202b\u202c\u202d\u202e]")
# Ces lettres grecques et cyrilliques ressemblent à des lettres latines.
HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "ѕ": "s", "к": "k", "м": "m", "т": "t", "н": "h",
    "α": "a", "ε": "e", "ο": "o", "ρ": "p", "ι": "i", "κ": "k", "ν": "v",
})
# Ces chiffres et symboles remplacent parfois des lettres pour contourner les filtres.
LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "@": "a", "$": "s", "!": "i",
})

# Ces expressions repèrent les différentes catégories de données personnelles.
PII_PATTERNS = {
    "email": re.compile(r"(?<![\w@])[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b"),
    "card": re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
    "phone": re.compile(
        r"(?<![\w+])(?:\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}"
        r"|0[1-9](?:[\s.-]?\d{2}){4})(?!\w)"
    ),
    "ip": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
}
# On commence par les détecteurs les plus précis pour éviter de confondre une carte avec un téléphone.
PII_ORDER = ("email", "iban", "card", "phone", "ip")
# Ces noms servent à indiquer les données masquées.
PII_LABELS = {
    "email": "email", "iban": "IBAN", "card": "carte", "phone": "téléphone", "ip": "IP",
}


# Cette classe décrit le résultat du contrôle d’un message.
@dataclass
class Verdict:
    # Cette valeur indique si le message est accepté.
    allowed: bool
    # Ce texte nettoyé sera utilisé pour la suite du traitement.
    text: str
    # Cette valeur indique la règle qui a bloqué le message, ou None.
    category: str | None = None
    # Ce message explique le refus à son auteur.
    message: str | None = None
    # Cette liste indique les catégories de données masquées.
    redacted: list = field(default_factory=list)


# Cette fonction uniformise le texte en retirant les accents, caractères invisibles et variantes de lettres pour faciliter les contrôles.
def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    text = ZERO_WIDTH.sub("", text).lower().translate(HOMOGLYPHS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("'", " ").replace("’", " ")
    return " ".join(text.split())


# Cette fonction garde les lettres et chiffres et décode leurs substitutions pour repérer les mots volontairement séparés.
def compact(normalized):
    return re.sub(r"[^a-z]", "", normalized.translate(LEET))


# Cette fonction vérifie la somme de contrôle de Luhn pour reconnaître certains numéros de carte.
def luhn_valid(digits):
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


# Cette classe applique les filtres d’entrée et de sortie définis dans la configuration.
class Guardrails:
    # On prépare les filtres à partir des réglages fournis ou du fichier de configuration.
    def __init__(self, config=None):
        config = config if config is not None else load_config(GUARDRAILS_CONFIG)
        # Cette option permet de désactiver les filtres pour les comparaisons et le débogage.
        self.enabled = config.get("enabled", True)
        # Cette valeur limite la longueur des messages reçus.
        self.max_input_chars = config.get("max_input_chars", 500)
        # Ce texte est renvoyé lorsqu’un message est trop long.
        self.too_long_message = config.get("too_long_message", "message trop long.")

        injection = config.get("injection") or {}
        # Ces règles associent une catégorie, un message et des motifs à détecter.
        self.rules = [(
            "injection",
            injection.get("message", "je ne peux pas changer mes consignes."),
            [re.compile(p) for p in injection.get("patterns", [])],
            [k.lower() for k in injection.get("keywords", [])],
        )]
        for topic in config.get("blocked_topics") or []:
            self.rules.append((
                topic["name"],
                topic.get("message", "je ne peux pas aider avec ça."),
                [re.compile(p) for p in topic.get("patterns", [])],
                [k.lower() for k in topic.get("keywords", [])],
            ))

        pii = config.get("pii") or {}
        # Cette liste indique les données personnelles à masquer.
        self.pii_kinds = [kind for kind in PII_ORDER if pii.get(kind, True)]
        # Ce texte remplace la donnée détectée en indiquant sa catégorie.
        self.pii_replacement = pii.get("replacement", "[{kind} masqué]")

        # Ces mots sont comparés sans tenir compte des accents et doivent correspondre à des mots entiers.
        self.banned = {normalize(w) for w in config.get("banned_words") or []}

    # Cette fonction masque les données personnelles détectées et indique leurs catégories.
    def redact_pii(self, text):
        found = []
        for kind in self.pii_kinds:
            def replace(match, kind=kind):
                value = match.group(0)
                if kind == "card" and not luhn_valid(re.sub(r"\D", "", value)):
                    return value
                found.append(kind)
                return self.pii_replacement.format(kind=PII_LABELS[kind])
            text = PII_PATTERNS[kind].sub(replace, text)
        return text, sorted(set(found), key=PII_ORDER.index)

    # Cette fonction cherche la première règle enfreinte par le message.
    def find_violation(self, text):
        normalized = normalize(text)
        squeezed = compact(normalized)
        for category, message, patterns, keywords in self.rules:
            if any(p.search(normalized) for p in patterns):
                return category, message
            if any(k in squeezed for k in keywords):
                return category, message
        return None

    # Cette fonction contrôle le message avant le modèle et masque les données personnelles lorsqu’il est accepté.
    def check_input(self, text):
        if not self.enabled:
            return Verdict(True, text)

        text = CONTROL.sub("", ZERO_WIDTH.sub("", text or "")).strip()
        if not text:
            return Verdict(False, text, "empty", "message vide.")
        if len(text) > self.max_input_chars:
            return Verdict(False, text, "too_long", self.too_long_message)

        violation = self.find_violation(text)
        if violation is not None:
            category, message = violation
            return Verdict(False, text, category, message)

        cleaned, found = self.redact_pii(text)
        return Verdict(True, cleaned, redacted=found)

    # Cette fonction nettoie la réponse avant son affichage, en masquant les données personnelles et les mots interdits.
    def check_output(self, text):
        if not self.enabled or not text:
            return Verdict(True, text or "")

        cleaned, found = self.redact_pii(text)
        if self.banned:
            masked = re.sub(
                r"\w+",
                lambda m: "*" * len(m.group(0)) if normalize(m.group(0)) in self.banned
                else m.group(0),
                cleaned,
            )
            if masked != cleaned:
                found.append("banned_word")
            cleaned = masked
        return Verdict(True, cleaned, redacted=found)


# Cette fonction charge les filtres. Si le fichier manque, le programme continue sans eux et le signale.
def load_guardrails():
    try:
        return Guardrails()
    except FileNotFoundError:
        print(f"[Guardrails] {GUARDRAILS_CONFIG} introuvable, garde-fous désactivés.")
        return Guardrails({"enabled": False})
