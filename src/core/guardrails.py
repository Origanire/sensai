## @file guardrails.py
# @brief Content and privacy guardrails (EV2): input and output interceptors.
#
# On input, a message is refused before it reaches the model when it tries
# to take control of it (prompt injection, jailbreak) or is out of scope
# (doxxing, harassment, illegal requests). Personal data (e-mail, phone,
# IP, card, IBAN) is masked, so it is never sent to the model nor stored in
# the viewer memory. On output, the same data and banned words are masked
# before anything is posted in a public chat.
#
# Every rule lives in config/guardrails.yaml: the code only applies them.

import re
import unicodedata
from dataclasses import dataclass, field

from src.core.ollama_client import load_config

## @brief Configuration file of the guardrails.
GUARDRAILS_CONFIG = "config/guardrails.yaml"

## @brief Invisible characters used to split a word without changing its look.
ZERO_WIDTH = re.compile("[​-‏⁠⁦-⁩﻿­]")
## @brief Control characters and bidirectional overrides: invisible in the
# chat, they can hide text or reverse its display.
CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e]")
## @brief Cyrillic and Greek letters that look like Latin ones.
HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "ѕ": "s", "к": "k", "м": "m", "т": "t", "н": "h",
    "α": "a", "ε": "e", "ο": "o", "ρ": "p", "ι": "i", "κ": "k", "ν": "v",
})
## @brief Leetspeak digits and symbols, decoded only in the compact form.
LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "@": "a", "$": "s", "!": "i",
})

## @brief Personal data detectors, by kind.
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
## @brief Order in which the detectors run: the most specific first, so a
# card number is not reported as a phone number.
PII_ORDER = ("email", "iban", "card", "phone", "ip")
## @brief Display names of the kinds of personal data.
PII_LABELS = {
    "email": "email", "iban": "IBAN", "card": "carte", "phone": "téléphone", "ip": "IP",
}


## @brief Decision taken on a message.
@dataclass
class Verdict:
    ## @brief True if the message may go on.
    allowed: bool
    ## @brief Text to use downstream (personal data masked).
    text: str
    ## @brief Rule that refused the message ("injection", "doxxing"...), or None.
    category: str | None = None
    ## @brief Message to show the author when the message is refused.
    message: str | None = None
    ## @brief Kinds of personal data masked in the text.
    redacted: list = field(default_factory=list)


## @brief Remove what makes two identical-looking texts differ.
#
# NFKC folds full-width and stylized letters ("ｉｇｎｏｒｅ"), invisible
# characters are dropped, look-alike Cyrillic/Greek letters become Latin,
# and accents are removed so a rule written without them matches both.
#
# @param text Raw text.
# @return Lowercase, accent-free text with single spaces.
def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    text = ZERO_WIDTH.sub("", text).lower().translate(HOMOGLYPHS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("'", " ").replace("’", " ")
    return " ".join(text.split())


## @brief Letters and digits only, leetspeak decoded.
#
# "j.a.i.l b-r-e-a-k" and "j41lbr34k" both become "jailbreak": keywords are
# searched in this form, which defeats separators and digit swaps.
#
# @param normalized Text returned by normalize().
# @return Compact text.
def compact(normalized):
    return re.sub(r"[^a-z]", "", normalized.translate(LEET))


## @brief Luhn checksum, used to tell a card number from any long number.
#
# @param digits String of digits.
# @return True if the checksum is valid.
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


## @brief Input and output interceptors driven by config/guardrails.yaml.
class Guardrails:
    ## @brief Build the guardrails from their configuration.
    #
    # @param config Dictionary of config/guardrails.yaml; if None, the file
    #               is loaded.
    def __init__(self, config=None):
        config = config if config is not None else load_config(GUARDRAILS_CONFIG)
        ## @brief False to let everything through (comparisons, debugging).
        self.enabled = config.get("enabled", True)
        ## @brief Maximum length of an incoming message.
        self.max_input_chars = config.get("max_input_chars", 500)
        ## @brief Answer to a message that is too long.
        self.too_long_message = config.get("too_long_message", "message trop long.")

        injection = config.get("injection") or {}
        ## @brief Rules as (category, message, compiled patterns, keywords).
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
        ## @brief Kinds of personal data to mask.
        self.pii_kinds = [kind for kind in PII_ORDER if pii.get(kind, True)]
        ## @brief Replacement text, "{kind}" is the kind of data.
        self.pii_replacement = pii.get("replacement", "[{kind} masqué]")

        ## @brief Banned words, normalized: matched as whole words, accents ignored.
        self.banned = {normalize(w) for w in config.get("banned_words") or []}

    ## @brief Mask the personal data of a text.
    #
    # @param text Text to clean.
    # @return A (cleaned text, kinds of data found) pair.
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

    ## @brief Find the first rule a message breaks.
    #
    # @param text Raw message.
    # @return A (category, message) pair, or None if no rule matches.
    def find_violation(self, text):
        normalized = normalize(text)
        squeezed = compact(normalized)
        for category, message, patterns, keywords in self.rules:
            if any(p.search(normalized) for p in patterns):
                return category, message
            if any(k in squeezed for k in keywords):
                return category, message
        return None

    ## @brief Check a message before it reaches the model.
    #
    # @param text Message typed by a user or a viewer.
    # @return A Verdict; when allowed, its text has personal data masked.
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

    ## @brief Clean an answer before it is shown or posted.
    #
    # Nothing is refused here: the answer is repaired (personal data and
    # banned words masked), since the viewer is waiting for a reply.
    #
    # @param text Answer of the model.
    # @return A Verdict, always allowed, with the cleaned text.
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


## @brief Load the guardrails from config/guardrails.yaml.
#
# A missing file disables them instead of stopping the program: the
# assistant keeps working, and the startup message says so.
#
# @return A Guardrails instance.
def load_guardrails():
    try:
        return Guardrails()
    except FileNotFoundError:
        print(f"[Guardrails] {GUARDRAILS_CONFIG} introuvable, garde-fous désactivés.")
        return Guardrails({"enabled": False})
