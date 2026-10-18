# Ce module détecte les pics d’activité du chat. Le seuil dépend du nombre de personnes qui écrivent, pas du nombre total de spectateurs.

import math
from collections import deque


# Cette classe suit les messages récents pour repérer les pics d’activité.
class BurstDetector:
    # On règle la durée d’observation, le seuil de messages et la pause entre deux pics signalés.
    def __init__(self, window, audience_window, ratio, min_messages, cooldown):
        # Cette durée définit la période utilisée pour détecter un pic.
        self.window = window
        # Cette durée sert à compter les personnes actives dans le chat.
        self.audience_window = audience_window
        # Ce nombre indique combien de messages sont attendus par personne active.
        self.ratio = ratio
        # Ce seuil minimum évite de signaler un pic dans un chat presque vide.
        self.min_messages = min_messages
        # Cette pause évite de signaler plusieurs fois le même pic.
        self.cooldown = cooldown
        # On garde ici les dates des messages encore dans la période observée.
        self.recent = deque()
        # On conserve la date du dernier message de chaque personne.
        self.last_seen = {}
        # Cette valeur indique la date du dernier pic signalé.
        self.last_burst = None
        # Cette valeur indique quand le premier message a été reçu.
        self.started = None

    # Cette fonction compte les personnes récemment actives et retire celles qui ne le sont plus.
    def audience(self, now):
        limit = now - self.audience_window
        for viewer_id in [v for v, seen in self.last_seen.items() if seen < limit]:
            del self.last_seen[viewer_id]
        return len(self.last_seen)

    # Cette fonction calcule le seuil de messages adapté à l’activité actuelle du chat.
    def threshold(self, now):
        return max(self.min_messages, math.ceil(self.audience(now) * self.ratio))

    # Cette fonction ajoute un message et vérifie s’il forme un pic. Elle attend assez de données avant de signaler le premier.
    def add(self, viewer_id, sent_at):
        if self.started is None:
            self.started = sent_at
        self.last_seen[viewer_id] = sent_at
        self.recent.append(sent_at)
        while self.recent and self.recent[0] <= sent_at - self.window:
            self.recent.popleft()

        if sent_at - self.started < self.audience_window:
            return None
        if self.last_burst is not None and sent_at - self.last_burst < self.cooldown:
            return None

        threshold = self.threshold(sent_at)
        if len(self.recent) < threshold:
            return None

        self.last_burst = sent_at
        return len(self.recent), threshold, len(self.last_seen)
