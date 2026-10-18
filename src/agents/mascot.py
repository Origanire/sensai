"""Ce module permet des réactions discrètes de mascotte, sans inventer ce qui se passe dans la vidéo."""
import re
import time

from src.core.chat_context import context_message
from src.core.chat_text import fit_chat_text

SIGNAL = re.compile(r'\b(?:gg|bien jou[ée]|bravo|victoire|on a r[ée]ussi|encore mort|boss|rip|let.?s go)\b', re.I)
SCHEMA = {'type':'object','properties':{'react':{'type':'boolean'},'text':{'type':'string'}},'required':['react','text']}


class MascotPacer:
    def __init__(self, now=None):
        self.last_attempt = time.monotonic() if now is None else now
        self.messages = 0
        self.viewers = set()

    def observe(self, viewer):
        self.messages += 1
        if len(self.viewers) < 2:
            self.viewers.add(viewer)

    def claim(self, text, interval, last_reply=None, now=None):
        now = time.monotonic() if now is None else now
        if now - self.last_attempt < interval or (last_reply is not None and now - last_reply < interval):
            return False
        if self.messages < 6 or len(self.viewers) < 2 or not SIGNAL.search(text) or '?' in text:
            return False
        self.last_attempt = now
        self.messages = 0
        self.viewers.clear()
        return True


def mascot_reaction(client, guardrails, persona, recent):
    if not recent:
        return None
    result = client.chat_json([
        {'role':'system','content':persona + '\nTu envisages UNE intervention spontanée de mascotte. '
         'Le streamer et les viewers gardent la place principale. Retourne react=false si ce serait banal, '
         'intrusif, répétitif, moqueur ou si la discussion est sensible. Ne réponds pas à chaque message. '
         'Sinon, une réaction originale de 180 caractères maximum, sans question, sans mention, '
         'sans recherche web, sans prétendre avoir vu une action. Réagis aux paroles du chat, '
         'sans confirmer une victoire ou un nombre de morts. Pas de défi risqué, humiliant ou discriminatoire.'},
        context_message(recent),
    ], SCHEMA)
    if not isinstance(result, dict) or result.get('react') is not True:
        return None
    text = result.get('text')
    if not isinstance(text, str) or not text.strip() or '?' in text:
        return None
    verdict = guardrails.check_input(fit_chat_text(text, 180))
    if not verdict.allowed:
        return None
    return fit_chat_text(guardrails.check_output(verdict.text).text, 180)
