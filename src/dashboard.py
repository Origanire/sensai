"""Local dashboard: python -m src.dashboard (macOS/Linux, loopback only)."""

import argparse
import atexit
from collections import deque
import html
import io
import json
import os
import re
from pathlib import Path
import secrets
import signal
import statistics
import subprocess
import sys
import threading
import time

from dotenv import dotenv_values, load_dotenv
from flask import Flask, Response, jsonify, request, send_file
import requests
import yaml

from src.core.bot_settings import ROOT, load_bot_settings, public_settings, save_bot_settings, validate_settings, bot_persona, channel_settings
from src.core.bot_runtime import bot_is_running
from src.core.guardrails import load_guardrails
from src.core.ollama_client import OllamaClient
from src.core.prompts import load_prompt
from src.core.channel_knowledge import load_faq, save_faq, faq_prompt, memory_status, load_profile, save_profile, PROFILE_QUESTIONS
from src.core.chat_text import fit_chat_text, PING_REPLY
from src.agents.router import route, explicit_search
from src.tools.web_search import ask_internet, load_internet_settings
from src.tools.live_audio import dependencies_ready
from src.tools.report import SECTION_TITLES, DEFAULT_SECTIONS, render_report
from src.tools.twitch_auth import AuthError, validate_token, authorize, ExpiredToken, refresh_authorization

UI = ROOT / "src/dashboard_ui"


class DashboardError(Exception):
    pass


class BotController:
    """Own exactly one child. No user-supplied commands or PID-based killing."""

    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.preview_lock = threading.Lock()
        self.check_lock = threading.Lock()
        self.process = None
        self.phase = "stopped"
        self.auth = {"phase": "idle"}
        self.active_channel = None
        self.audio_stage = "stopped"
        self.events = deque(maxlen=60)
        self.health = {"twitch": "unchecked", "ollama": "unchecked", "model": None, "embedding_ready": False}
        self.metrics = self.empty_metrics()
        self.viewers = set()
        self.latencies = deque(maxlen=5000)

    @staticmethod
    def empty_metrics():
        return {"started_at": None, "ended_at": None, "received": 0, "replies": 0,
                "cooldown_skipped": 0, "blocked": 0, "routes": {"chat": 0, "docs": 0, "web": 0}}

    def credentials(self):
        values = {**os.environ, **dotenv_values(self.root / ".env")}
        return {key: values.get(key) or "" for key in
                ("TWITCH_CLIENT_ID", "TWITCH_BOT_USERNAME", "TWITCH_OAUTH_TOKEN")}

    def model_config(self):
        with (self.root / "config.yaml").open() as source:
            config = yaml.safe_load(source)
        local = {**os.environ, **dotenv_values(self.root / ".env")}
        config["model"] = local.get("SENSAI_MODEL") or config["model"]
        return config

    def check(self):
        with self.check_lock:
            return self._check()

    def _check(self):
        credentials = self.credentials()
        health = {"checked_at": time.time(), "twitch": "error", "ollama": "error", "embedding_ready": False}
        try:
            if not all(credentials.values()):
                raise AuthError("Compte Twitch incomplet. Lance l'assistant de connexion.")
            try:
                identity = validate_token(credentials["TWITCH_OAUTH_TOKEN"].removeprefix("oauth:"),
                                          credentials["TWITCH_CLIENT_ID"], credentials["TWITCH_BOT_USERNAME"])
            except ExpiredToken:
                local = {**os.environ, **dotenv_values(self.root / ".env")}
                identity = refresh_authorization(credentials["TWITCH_CLIENT_ID"], credentials["TWITCH_BOT_USERNAME"],
                                                 local.get("TWITCH_REFRESH_TOKEN"), self.root / ".env")
            health.update(twitch="ready", bot=identity["login"], expires_at=time.time() + identity["expires_in"])
        except AuthError as error:
            health["twitch_error"] = str(error)
        config = self.model_config()
        health["model"] = config["model"]
        try:
            response = requests.get(config["ollama_url"].rstrip("/") + "/api/tags", timeout=5)
            response.raise_for_status()
            models = {model["name"] for model in response.json().get("models", [])}
            if config["model"] not in models and config["model"] + ":latest" not in models:
                health["ollama_error"] = "Le modèle configuré n'est pas installé dans Ollama."
            else:
                health["ollama"] = "ready"
            embedding = config.get("embedding_model", "nomic-embed-text")
            health["embedding_ready"] = embedding in models or embedding + ":latest" in models
        except (requests.RequestException, ValueError, KeyError):
            health["ollama_error"] = "Ollama est indisponible. Ouvre l'application Ollama puis réessaie."
        with self.lock:
            self.health = health
        return health

    def log(self, message, kind="info"):
        self.events.append({"at": time.time(), "kind": kind, "message": message})

    def begin_auth(self):
        with self.lock:
            if self.phase in {"checking", "starting", "running", "stopping"} or bot_is_running(self.root / ".bot.lock"):
                raise DashboardError("Arrête le bot avant de reconnecter son compte.")
            if self.auth["phase"] == "pending":
                raise DashboardError("Une connexion est déjà en cours.")
            credentials = self.credentials()
            if not credentials["TWITCH_CLIENT_ID"] or not credentials["TWITCH_BOT_USERNAME"]:
                raise DashboardError("Renseigne d'abord TWITCH_CLIENT_ID et TWITCH_BOT_USERNAME dans .env.")
            self.auth = {"phase": "pending", "message": "Préparation de la connexion Twitch…"}
        def on_device(device):
            with self.lock:
                self.auth = {"phase": "pending", "code": device["user_code"],
                             "expires_at": time.time() + device["expires_in"],
                             "message": "Connecte-toi avec " + credentials["TWITCH_BOT_USERNAME"] + " puis saisis ce code sur Twitch."}
        def connect():
            try:
                authorize(credentials["TWITCH_CLIENT_ID"], credentials["TWITCH_BOT_USERNAME"],
                          path=self.root / ".env", on_device=on_device)
                self.check()
                with self.lock:
                    self.auth = {"phase": "ready"}
                    self.log("Compte Twitch reconnecté.")
            except Exception as error:
                with self.lock:
                    self.auth = {"phase": "error", "message": str(error) if isinstance(error, AuthError) else "Connexion impossible. Réessaie."}
        threading.Thread(target=connect, daemon=True).start()

    def start(self):
        with self.lock:
            if self.auth["phase"] == "pending":
                raise DashboardError("Termine la connexion Twitch avant de démarrer le bot.")
            if self.process is not None and self.process.poll() is None or self.phase in {"checking", "starting", "stopping"}:
                raise DashboardError("Le bot est déjà lancé ou change d'état.")
            if bot_is_running(self.root / ".bot.lock"):
                raise DashboardError("Un bot lancé depuis un autre terminal fonctionne déjà. Arrête-le d'abord.")
            self.phase = "checking"
        try:
            health = self.check()
            if health["twitch"] != "ready" or health["ollama"] != "ready":
                raise DashboardError(health.get("twitch_error") or health.get("ollama_error"))
            settings = load_bot_settings(self.root)
            if settings["channel"].lower() == health["bot"].lower():
                raise DashboardError("Choisis une chaîne différente du compte bot dédié.")
            with self.lock:
                self.metrics = self.empty_metrics()
                self.viewers.clear()
                self.latencies.clear()
                self.events.clear()
                self.active_channel = settings["channel"]
                read_fd, write_fd = os.pipe()
                environment = os.environ.copy()
                environment.update({key: value for key, value in dotenv_values(self.root / ".env").items() if value is not None})
                environment.update({"SENSAI_DASHBOARD": "1", "SENSAI_EVENT_FD": str(write_fd),
                                    "SENSAI_MODEL": health["model"]})
                try:
                    process = subprocess.Popen(
                        [sys.executable, "-u", "-m", "src.agents.chat_agent"], cwd=self.root,
                        env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, pass_fds=(write_fd,),
                    )
                except Exception:
                    os.close(read_fd)
                    raise
                finally:
                    os.close(write_fd)
                self.process = process
                self.phase = "starting"
                self.log("Connexion au chat Twitch en cours.")
                threading.Thread(target=self.monitor, args=(process, read_fd), daemon=True).start()
        except Exception:
            with self.lock:
                self.phase = "stopped"
            raise

    def stop(self):
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                if self.phase == "checking":
                    raise DashboardError("La vérification est en cours. Réessaie dans quelques secondes.")
                return
            if self.phase == "stopping":
                return
            self.phase = "stopping"
            self.log("Arrêt demandé ; sauvegarde de la mémoire et du compte-rendu.")
            process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
            with self.lock:
                self.log("Arrêt forcé : les dernières statistiques peuvent être incomplètes.", "warning")

    def monitor(self, process, read_fd):
        with os.fdopen(read_fd) as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                with self.lock:
                    self.consume(event)
        code = process.wait()
        with self.lock:
            if self.process is process:
                self.phase = "stopped" if code == 0 or self.phase == "stopping" else "error"
                self.metrics["ended_at"] = time.time()
                self.log("Bot arrêté." if self.phase == "stopped" else "Le bot s'est interrompu. Vérifie les connexions.",
                         "info" if self.phase == "stopped" else "error")
                self.save_session()

    def consume(self, event):
        kind = event.get("kind")
        if kind == "connected":
            self.phase = "running"
            self.metrics["started_at"] = event["at"]
            self.log("Connecté au chat de " + self.active_channel + ".")
        elif kind == "message":
            self.metrics["received"] += 1
            self.viewers.add(event.get("viewer"))
        elif kind == "reply":
            self.metrics["replies"] += 1
            latency = event.get("latency")
            if isinstance(latency, (int, float)) and latency >= 0:
                self.latencies.append(latency)
            self.log("Réponse envoyée" + (f" · traitement {latency:.1f} s" if latency is not None else "") + ".")
        elif kind == "research":
            self.log({"started": "Lumi consulte l’agent de recherche web.",
                      "completed": "Recherche terminée ; réponse vérifiée sur des extraits, sans lien dans le chat.",
                      "unavailable": "Recherche indisponible ; Lumi le signalera dans le chat."}.get(event.get("stage"), "Recherche web."))
        elif kind == "audio":
            stage = event.get("stage")
            labels = {"starting": "Connexion au son du live…", "loading": "Chargement du modèle vocal local…",
                      "listening": "Écoute du live active · transcription locale.", "missing": "Dépendances vocales absentes : installe requirements-audio.txt.",
                      "unavailable": "Son du live indisponible (hors ligne, accès refusé ou erreur de transcription). Nouvel essai dans 60 s.",
                      "stopped": "Écoute vocale arrêtée.", "answered": "Demande vocale traitée dans le chat.",
                      "cooldown": "Demande vocale ignorée pendant la pause."}
            if stage in labels:
                if stage != self.audio_stage:
                    self.log(labels[stage], "warning" if stage in {"missing", "unavailable"} else "info")
                if stage not in {"answered", "cooldown"}:
                    self.audio_stage = stage
        elif kind == "memory":
            self.log("Une préférence de jeu explicite a été mémorisée pour son auteur.")
        elif kind == "mascot":
            self.log("Lumi a réagi spontanément au chat.")
        elif kind == "cooldown":
            self.metrics["cooldown_skipped"] += 1
            self.log("Sollicitation ignorée pendant la pause entre réponses.", "warning")
        elif kind == "activity":
            self.metrics["blocked"] = event["blocked"]
            self.metrics["routes"] = event["routes"]
        elif kind in {"warning", "error"}:
            self.log(event.get("message", "Une erreur est survenue."), kind)

    def metrics_snapshot(self):
        result = dict(self.metrics)
        elapsed = max(0, (result["ended_at"] or time.time()) - result["started_at"]) if result["started_at"] else 0
        result.update(duration_seconds=int(elapsed), viewers=len(self.viewers),
                      received_per_minute=round(result["received"] / (elapsed / 60), 1) if elapsed >= 60 else None,
                      median_latency=round(statistics.median(self.latencies), 1) if self.latencies else None,
                      latency_samples=len(self.latencies))
        return result

    def save_session(self):
        if not self.metrics["started_at"]:
            return
        path = self.root / "logs/dashboard-sessions.json"
        try:
            previous = json.loads(path.read_text()) if path.exists() else []
            previous.append({"channel": self.active_channel, **self.metrics_snapshot()})
            path.parent.mkdir(exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(previous[-200:], ensure_ascii=False, indent=2))
            temporary.replace(path)
        except (OSError, ValueError, AttributeError):
            self.log("L'historique des sessions n'a pas pu être enregistré.", "warning")

    def snapshot(self):
        with self.lock:
            settings = public_settings(load_bot_settings(self.root))
            return {"phase": self.phase, "active_channel": self.active_channel, "settings": settings,
                    "audio": {"stage": self.audio_stage if self.phase in {"starting", "running"} else "stopped", "dependencies_ready": dependencies_ready()},
                    "memory": memory_status(settings["channel"], self.root),
                    "health": self.health, "auth": dict(self.auth), "metrics": self.metrics_snapshot(), "events": list(self.events),
                    "account": self.credentials()["TWITCH_BOT_USERNAME"],
                    "external_bot": self.process is None and bot_is_running(self.root / ".bot.lock")}

    def save(self, values):
        with self.lock:
            settings = public_settings(load_bot_settings(self.root))
            changes = validate_settings(values)
            if self.phase in {"checking", "starting", "running", "stopping"} and changes.get("channel", settings["channel"]) != settings["channel"]:
                raise DashboardError("Arrête le bot avant de changer de chaîne.")
            changes = channel_settings(settings, changes, self.root)
            settings.update(changes)
            save_bot_settings(settings, self.root)
            self.log("Réglages enregistrés. Ils s'appliquent aux prochains messages.")

    def preview(self, data):
        question = data.get("message")
        if not isinstance(question, str) or not question.strip() or len(question) > 500:
            raise ValueError("Saisis un message de 1 à 500 caractères.")
        settings = load_bot_settings(self.root)
        settings.update(validate_settings(data.get("settings", {})))
        if not self.preview_lock.acquire(blocking=False):
            raise DashboardError("Un essai est déjà en cours.")
        try:
            guardrails = load_guardrails()
            verdict = guardrails.check_input(question)
            if not verdict.allowed:
                return {"reply": verdict.message, "seconds": 0, "blocked": True}
            client = OllamaClient(self.model_config())
            started = time.monotonic()
            # Strip only the configured mention, as the Twitch caller does.
            from src.agents.chat_agent import match_trigger
            addressed = match_trigger(verdict.text, settings["trigger"])
            query = addressed if addressed is not None else verdict.text
            if not query:
                return {"reply": PING_REPLY, "seconds": 0, "blocked": False, "route": "chat"}
            search_request = explicit_search(query)
            if search_request is not None:
                query = search_request
                if not query:
                    raise ValueError("Usage : !search ta question")
            choice = "web" if search_request is not None else route(query, client, topic=settings["stream_topic"])
            persona = bot_persona(load_prompt("persona"), settings) + faq_prompt(settings, self.root)
            if choice == "web":
                response = ask_internet(query, client, load_internet_settings(self.model_config())["max_results"], persona=persona, topic=settings["stream_topic"])
            else:
                response = client.chat_silent([
                    {"role": "system", "content": persona},
                    {"role": "user", "content": query},
                ])
            if not response or not response.strip():
                raise DashboardError("Le modèle n'a pas répondu. Vérifie Ollama et réessaie.")
            return {"reply": fit_chat_text(guardrails.check_output(response).text, 500 - len("@Viewer ")), "seconds": round(time.monotonic()-started, 1), "blocked": False, "route": "web" if choice == "web" else "chat"}
        finally:
            self.preview_lock.release()

    def report(self):
        path = self.root / "stream_report.json"
        if not path.exists():
            return None
        report = json.loads(path.read_text())
        return {key: str(report.get(key, default)) for key, default in DEFAULT_SECTIONS.items()}


def create_app(controller=None):
    controller = controller or BotController()
    app = Flask(__name__, static_folder=str(UI), static_url_path="/assets")
    app.json.sort_keys = False
    app.config.update(MAX_CONTENT_LENGTH=16_384, TRUSTED_HOSTS=["127.0.0.1", "localhost"])
    csrf = secrets.token_urlsafe(32)
    app.config["DASHBOARD_CSRF"] = csrf
    app.config["BOT_CONTROLLER"] = controller

    @app.before_request
    def protect_local_interface():
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            return jsonify(error="Origine refusée."), 403
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(error="Accès extérieur refusé."), 403
        if request.path.startswith("/api/") and not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), csrf):
            return jsonify(error="Recharge la page du dashboard pour continuer."), 403

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(DashboardError)
    def conflict(error):
        return jsonify(error=str(error)), 409

    @app.errorhandler(500)
    def unexpected(error):
        return jsonify(error="Une erreur interne est survenue. Réessaie ou redémarre le dashboard."), 500

    @app.get("/")
    def index():
        return Response((UI / "index.html").read_text().replace("__CSRF__", html.escape(csrf)), mimetype="text/html")

    @app.get("/api/state")
    def state():
        return jsonify(controller.snapshot())

    @app.post("/api/settings")
    def settings():
        controller.save(request.get_json())
        return jsonify(controller.snapshot())

    @app.post("/api/start")
    def start():
        controller.start()
        return jsonify(controller.snapshot())

    @app.post("/api/stop")
    def stop():
        controller.stop()
        return jsonify(controller.snapshot())

    @app.post("/api/auth")
    def auth():
        controller.begin_auth()
        return jsonify(controller.snapshot())

    @app.post("/api/check")
    def check():
        return jsonify(controller.check())

    @app.get("/api/streamer-profile")
    def get_profile():
        settings = load_bot_settings(controller.root)
        return jsonify(channel=settings["channel"], questions=PROFILE_QUESTIONS, answers=load_profile(settings, controller.root))

    @app.post("/api/streamer-profile")
    def put_profile():
        data = request.get_json()
        settings = load_bot_settings(controller.root)
        if not isinstance(data, dict) or data.get("channel") != settings["channel"]:
            raise ValueError("La chaîne a changé. Recharge le questionnaire.")
        answers = save_profile(settings, data.get("answers"), controller.root)
        return jsonify(channel=settings["channel"], answers=answers)

    @app.get("/api/faq")
    def get_faq():
        settings = load_bot_settings(controller.root)
        return jsonify(channel=settings["channel"], content=load_faq(settings, controller.root))

    @app.post("/api/faq")
    def put_faq():
        data = request.get_json()
        settings = load_bot_settings(controller.root)
        if not isinstance(data, dict) or data.get("channel") != settings["channel"]:
            raise ValueError("La chaîne a changé. Recharge la FAQ avant de l’enregistrer.")
        save_faq(settings, data.get("content"), controller.root)
        return jsonify(channel=settings["channel"], content=load_faq(settings, controller.root))

    @app.post("/api/preview")
    def preview():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("Message invalide.")
        return jsonify(controller.preview(data))

    @app.get("/api/report")
    def report():
        try:
            return jsonify(report=controller.report(), titles=SECTION_TITLES)
        except (OSError, ValueError):
            return jsonify(error="Le compte-rendu est en cours d'écriture. Réessaie."), 409

    @app.post("/api/export")
    def export():
        data = request.get_json()
        kind = data.get("format") if isinstance(data, dict) else None
        if kind not in {"md", "json", "html", "pdf"}:
            raise ValueError("Format d'export invalide.")
        report = controller.report()
        if report is None:
            raise DashboardError("Aucun compte-rendu pour le moment. Note un événement ou arrête le bot après une session.")
        if kind == "pdf":
            from src.core.export import write_pdf
            path = write_pdf("Compte-rendu de stream", [(title, report[key]) for key, title in SECTION_TITLES.items()], "StreamReport")
            return send_file(path, as_attachment=True)
        if kind == "json":
            text, mime = json.dumps(report, ensure_ascii=False, indent=2), "application/json"
        elif kind == "html":
            text = '<!doctype html><html lang="fr"><meta charset="utf-8"><title>Compte-rendu</title><body><pre>' + html.escape(render_report(report)) + '</pre></body></html>'
            mime = "text/html"
        else:
            text, mime = render_report(report), "text/markdown"
        return send_file(io.BytesIO(text.encode()), mimetype=mime, as_attachment=True, download_name="StreamReport." + kind)

    return app


def main():
    parser = argparse.ArgumentParser(description="Dashboard local SENSAI")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    controller = BotController()
    atexit.register(controller.stop)
    print(f"Dashboard SENSAI : http://127.0.0.1:{args.port}", flush=True)
    create_app(controller).run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
