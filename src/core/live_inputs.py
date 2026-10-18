"""Ce module continue de lire le chat pendant les réponses du modèle et limite les messages en attente."""
import queue
import threading
import time


def live_inputs(incoming):
    inbox = queue.Queue(maxsize=200)
    def read():
        try:
            for message in incoming:
                try:
                    inbox.put_nowait((time.monotonic(), message))
                except queue.Full:
                    pass
        except Exception as error:
            inbox.put(error)
        finally:
            inbox.put(None)
    threading.Thread(target=read, daemon=True).start()
    while True:
        try:
            item = inbox.get(timeout=1)
        except queue.Empty:
            yield None  # On applique aussi les réglages et l’écoute quand aucun message n’arrive dans le chat.
            continue
        if item is None:
            return
        if isinstance(item, Exception):
            raise item
        at, message = item
        if time.monotonic() - at <= 45:
            yield message
