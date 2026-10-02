# SENSAI

Assistant IA construit de zéro (sans framework LLM), qui parle en local à un modèle via l'API HTTP d'[Ollama](https://ollama.com).

Projet réalisé dans le cadre du cursus Epitech (PGE3 — G-AIA-500-MAR-5-1).

---

## Sommaire

- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Internet agent — rapports automatiques](#internet-agent--rapports-automatiques)
- [Connecter Twitch et OBS](#connecter-twitch-et-obs)
- [Communication inter-agents](#communication-inter-agents)
- [Fonctionnalités implémentées](#fonctionnalités-implémentées)
- [Structure du projet](#structure-du-projet)
- [Gestion des ressources (Ollama)](#gestion-des-ressources-ollama)

---

## Prérequis

- Python 3.10 ou supérieur
- [Ollama](https://ollama.com) installé en local

---

## Installation

### 1. Installer Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

> Sous WSL, `zstd` est requis pour l'extraction :
> ```bash
> sudo apt-get update && sudo apt-get install -y zstd
> ```

### 2. Télécharger les modèles utilisés par le projet

```bash
ollama pull llama3.2          # modèle de conversation (chat)
ollama pull nomic-embed-text  # modèle d'embeddings (RAG)
```

### 3. Cloner le repo et créer l'environnement virtuel

```bash
git clone <url-du-repo>
cd sensai
python3 -m venv venv
source venv/bin/activate
```

### 4. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

---

## Configuration

Le modèle et les paramètres d'inférence se modifient dans `config.yaml`, **sans toucher au code** :

```yaml
model: llama3.2
ollama_url: http://localhost:11434
max_tokens: 1024
temperature: 0.7
```

| Clé | Description |
|---|---|
| `model` | Nom du modèle Ollama à utiliser (doit avoir été `pull` au préalable) |
| `ollama_url` | URL locale de l'API Ollama |
| `max_tokens` | Nombre maximum de tokens générés par réponse |
| `temperature` | Créativité du modèle (0 = déterministe, 1 = créatif) |

---

## Utilisation

### Démarrer Ollama

```bash
ollama serve
```
(ou via systemd, voir la section [Gestion des ressources](#gestion-des-ressources-ollama))

### Lancer le chatbot CLI

```bash
python3 -m src.cli
```

### Exemple de session

```
Sensai CLI — tape 'exit' ou 'quit' pour quitter.

Toi : Salut, je m'appelle Hatim
Sensai : Bonjour Hatim ! Ça fait plaisir de te parler. Comment puis-je t'aider aujourd'hui ?
Toi : Comment je m'appelle ?
Sensai : Tu t'appelles Hatim !
Toi : exit
À bientôt !
```

### Ingérer des documents (RAG)

Place tes fichiers (`.pdf`, `.docx`, `.txt`) dans un dossier (ex: `documents/`), puis :

```python
from src.ollama_client import OllamaClient
from src.ingestion import ingest_folder
from src.storage import init_db, save_chunks, count_chunks

client = OllamaClient()
conn = init_db()

results = ingest_folder("documents", client)

for filename, chunks in results.items():
    save_chunks(conn, filename, chunks)

print(count_chunks(conn))  # nombre total de chunks stockés
```

Chaque document est découpé en chunks, chacun transformé en embedding (vecteur de 768 dimensions via `nomic-embed-text`), puis stocké dans une base SQLite locale (`sensai.db`) aux côtés de son texte d'origine.

---

## Internet agent — rapports automatiques

Sensai peut faire de la veille tout seul : à intervalle régulier, il cherche
chaque sujet configuré sur le web (DuckDuckGo), puis le modèle résume les
résultats en un rapport Markdown. Les rapports sont générés en tâche de fond :
le chat reste utilisable pendant ce temps.

### Configurer les sujets et l'intervalle

Dans `config.yaml` :

```yaml
scheduled_reports:
  topics:
    - "actualités Elden Ring"
    - "nouveautés Twitch streamers"
  interval_minutes: 60
  folder: reports/
```

| Clé | Description | Défaut |
|---|---|---|
| `topics` | Sujets à surveiller, un rapport par sujet et par cycle | aucun |
| `interval_minutes` | Temps entre le début de deux cycles (décimales acceptées) | `60` |
| `folder` | Dossier des rapports, créé s'il n'existe pas | `reports/` |

Si la section est absente, les valeurs par défaut s'appliquent. Sans sujet,
`/reports start` refuse de démarrer. La config est relue à chaque
`/reports start`.

### Démarrer et arrêter

Dans la CLI (`python3 -m src.cli`) :

| Commande | Effet |
|---|---|
| `/reports start` | lance la boucle ; le premier cycle démarre immédiatement |
| `/reports status` | indique si la boucle tourne, le cycle en cours ou le prochain, le dernier rapport et la dernière erreur |
| `/reports stop` | arrête la boucle (le rapport en cours d'écriture est terminé d'abord) |

```
Toi : /reports start
Rapports automatiques lancés : 2 sujet(s), toutes les 60 min, dans reports/
Toi : quelle est la capitale de la France ?
Sensai : La capitale de la France est Paris.
Toi :
[Rapports] « actualités Elden Ring » -> reports/report_actualites-elden-ring_2026-10-02_12h53.md
Toi : /reports stop
Rapports automatiques arrêtés.
```

Quitter la CLI arrête aussi la boucle.

### Exemple de rapport

Un fichier par sujet et par cycle, `report_<sujet>_<AAAA-MM-JJ>_<HHhMM>.md` :

```markdown
# Rapport de veille : actualités Elden Ring

_Généré le 02/10/2026 à 12h53 — requête : « Elden Ring actualités »_

## Points clés

- Le jeu Elden Ring reçoit une mise à jour importante, la 1.17, avec de nouvelles classes, de l'armoire révisée et des ajustements de PvP, selon le site Lacremedugaming.fr [5].
- Des actualités récentes sur Elden Ring sont disponibles sur plusieurs sites, notamment VGTimes, ActuGaming.net, jeuxvideo.com et Bandai Namco Europe [1, 3, 4, 2].
- ...

## Sources

1. [Actualités Elden Ring — dernières news et mises à jour (octobre 2026)](https://fr.vgtimes.com/games/elden-ring/news/)
2. ...
5. [Elden Ring reçoit sa première grosse mise à jour depuis près de deux ...](https://www.lacremedugaming.fr/jeux/elden-ring/...)
```

Le titre, la date et les sources sont écrits par le code à partir des vrais
résultats de recherche ; le modèle ne rédige que les 3 à 5 points clés, chacun
renvoyant au numéro de sa source.

### En cas d'erreur

- **Pas de réseau / recherche vide** et **Ollama indisponible** : le sujet est
  sauté pour ce cycle, l'erreur est affichée et visible dans
  `/reports status`, et la boucle réessaie au cycle suivant.
- **Limite :** un modèle 3B résume parfois mal un extrait (date ou chiffre
  mal interprété). Les sources sont là pour vérifier avant d'en parler en
  stream.

Les user stories de la fonctionnalité sont dans
[`doc/user_stories.md`](doc/user_stories.md).

---

## Connecter Twitch et OBS

Les deux connexions sont **optionnelles** : sans rien configurer, l'agent chat
lit le chat en anonyme et répond seulement dans le terminal, et l'overlay OBS
est sauté. Les secrets se mettent dans un fichier `.env` (non versionné) :

```bash
cp .env.example .env
```

### Twitch : faire répondre Sensai dans le chat

1. **Choisir la chaîne** à écouter dans `config/chat_agent.yaml` :
   ```yaml
   channel: nom_de_ta_chaine
   ```
2. **Créer un compte Twitch pour le bot** (ex. `sensai_bot`). Un compte séparé
   évite que le bot parle sous le nom du streamer.
3. **Générer un token OAuth pour ce compte**, connecté en tant que bot, avec
   les scopes `chat:read` et `chat:edit` (par exemple via
   [twitchtokengenerator.com](https://twitchtokengenerator.com), « Bot Chat
   Token »). Copier l'*Access Token*.
4. **Remplir `.env`** :
   ```
   TWITCH_BOT_USERNAME=sensai_bot
   TWITCH_OAUTH_TOKEN=le_token_copié
   ```
   Le préfixe `oauth:` est facultatif. Ne jamais versionner ce fichier.
5. *(Conseillé)* **Nommer le bot modérateur** de la chaîne en tapant
   `/mod sensai_bot` dans le chat : Twitch le laisse alors envoyer plus de
   messages et ignorer le mode lent.
6. **Lancer l'agent** :
   ```bash
   python3 -m src.agents.chat_agent
   ```
   La première ligne doit être `Listening on #ta_chaine as sensai_bot`. Si elle
   indique `anonymously (read-only)`, les variables de `.env` ne sont pas lues.
7. **Tester** dans le chat : `@sensai salut`, puis `!search date de sortie de
   Elden Ring Nightreign`.

### OBS : afficher les résultats en overlay

Requiert **OBS 28 ou plus** (le serveur WebSocket est intégré).

1. **Activer le serveur WebSocket** : *Outils > Paramètres du serveur
   WebSocket* > cocher *Activer le serveur WebSocket*. Garder le port `4455`.
2. **Mot de passe** : si *Activer l'authentification* est coché, cliquer sur
   *Afficher les informations de connexion*, copier le mot de passe dans `.env` :
   ```
   OBS_WEBSOCKET_PASSWORD=le_mot_de_passe
   ```
3. **Créer la source** : dans la scène du stream, *+ > Texte (GDI+)* (ou
   *Texte (FreeType 2)* sous Linux/macOS), nommée exactement **`SensaiOverlay`**.
   Le texte de départ n'a pas d'importance, Sensai le remplacera.
4. **Vérifier `config.yaml`** :
   ```yaml
   obs:
     enabled: true
     host: localhost
     port: 4455
     source_name: SensaiOverlay
   ```
5. **Tester la connexion** sans passer par le chat, OBS ouvert :
   ```bash
   python3 -c "from dotenv import load_dotenv; load_dotenv(); \
   from src.core.ollama_client import load_config; \
   from src.tools.obs import load_obs_settings, update_text_source; \
   s = load_obs_settings(load_config()); \
   print(update_text_source(s['source_name'], 'Sensai est connecté', s['host'], s['port'], s['password']))"
   ```
   `True` et le texte « Sensai est connecté » à l'écran : c'est prêt. Ensuite,
   chaque `!search` dans le chat met l'overlay à jour.

> **Sensai dans WSL, OBS sous Windows :** `localhost` n'atteint Windows qu'avec
> le réseau WSL en mode *mirrored*. Sinon, mettre dans `obs.host` l'IP de
> Windows, donnée par `ip route show default | awk '{print $3}'`, et autoriser
> le port 4455 dans le pare-feu Windows.

### En cas de problème

| Message dans le terminal | Cause probable |
|---|---|
| `Twitch a refusé la connexion du bot` | token invalide ou expiré, ou nom du bot différent du compte du token |
| `Listening on ... anonymously (read-only)` | `.env` absent ou `TWITCH_BOT_USERNAME` / `TWITCH_OAUTH_TOKEN` vides |
| `[OBS] injoignable sur localhost:4455` | OBS fermé, serveur WebSocket désactivé, ou mauvais `obs.host` (WSL) |
| `[OBS] Source « SensaiOverlay » introuvable` | aucune source de ce nom dans OBS (attention aux majuscules) |
| `[OBS] OBS a fermé la connexion : mot de passe WebSocket incorrect ?` | `OBS_WEBSOCKET_PASSWORD` différent de celui d'OBS |
| `[OBS] Connexion refusée par OBS : authentication enabled but no password provided` | authentification activée dans OBS mais pas de mot de passe dans `.env` |

---

## Communication inter-agents

Les agents se parlent par **appels de fonctions directs** (pas de bus de
messages) : l'agent Chat importe l'interface de l'agent Internet
(`src/tools/web_search.py`) et le connecteur OBS (`src/tools/obs.py`).

```
viewer ──!search <question>──> Agent Chat ──ask_internet()──> Agent Internet ──DDGS──> web
                                   │   <──réponse + source (≤ 500 car.)──┘
                                   ├──> chat Twitch (@viewer réponse... https://source)
                                   └──get_quick_fact()──> Agent Internet
                                         └──fait court (≤ 160 car.)──> OBS : source Texte « SensaiOverlay »
```

- **`ask_internet(question, client)`** : question → requête → résultats → réponse
  avec sources. **`get_quick_fact(topic, client)`** : une ou deux phrases pour
  un overlay. Aucune ne lève d'exception : en cas de panne (réseau, DDGS,
  Ollama), elles renvoient `"Recherche indisponible pour le moment."`.
- L'overlay est mis à jour **à chaque `!search`** (pas de minuterie séparée) :
  c'est démontrable en direct, une question dans le chat s'affiche à l'écran.
  Si OBS ne répond pas, seul l'overlay est sauté, la réponse chat part quand même.
- Réglages : sections `internet_agent` (cooldown, nombre de résultats) et `obs`
  (hôte, port, nom de la source) de `config.yaml`. Les secrets (compte bot
  Twitch, mot de passe OBS) vont dans `.env`, voir `.env.example`.
- Mise en place : [Connecter Twitch et OBS](#connecter-twitch-et-obs). Détails
  et limites : [`doc/chat_agent.md`](doc/chat_agent.md).

---

## Fonctionnalités implémentées

### Base Loop (obligatoire)

- [x] Chatbot en ligne de commande connecté à Ollama
- [x] Réponses en streaming (affichage progressif token par token)
- [x] Historique de conversation conservé pendant la session
- [x] Gestion d'erreurs (modèle indisponible, timeout, connexion coupée, input vide)
- [x] Modèle sélectionnable via `config.yaml`, sans modification du code

### RAG — Document ingestion pipeline

- [x] Chargement multi-format (`.txt`, `.pdf`, `.docx`)
- [x] Découpage en chunks avec chevauchement (`chunk_size` / `overlap` configurables)
- [x] Génération des embeddings via Ollama (`nomic-embed-text`)
- [x] Stockage persistant dans une base vectorielle locale (SQLite)
- [x] Ingestion d'un dossier complet avec gestion d'erreur par fichier

### Fonctionnalités additionnelles

- [x] Internet agent : rapports de veille web automatiques et planifiés (#41)
- [x] Communication Chat <-> Internet : commande `!search` dans le chat Twitch (#43)
- [x] Communication OBS <-> Internet : overlay texte mis à jour à chaque recherche (#44)

_Le reste à venir — voir les [Issues](../../issues) et le [Project board](../../projects) du repo._

---

## Structure du projet

```
sensai/
├── src/
│   ├── __init__.py
│   ├── ollama_client.py   # Client HTTP vers l'API Ollama (chat streaming, embeddings, erreurs)
│   ├── cli.py               # Chatbot CLI (Base Loop)
│   ├── ingestion.py         # Chargement (txt/pdf/docx), chunking, génération des embeddings
│   └── storage.py           # Stockage/lecture des chunks embeddés en SQLite
├── documents/                # Documents à ingérer (non versionné)
├── sensai.db                 # Base SQLite locale (non versionné)
├── config.yaml                # Configuration (modèle, url, température...)
├── requirements.txt           # Dépendances Python
├── .gitignore
└── README.md
```

---

## Documentation (Doxygen)

La documentation technique est générée avec [Doxygen](https://www.doxygen.nl) à partir des commentaires du code source (`## @brief`, `@param`, `@return`...).

### Générer la documentation

```bash
# Depuis la racine du projet
sudo apt-get install doxygen   # si nécessaire
doxygen doc/Doxyfile
```

La documentation HTML est ensuite disponible dans `doc/html/index.html`.

| Élément | Rôle |
|---|---|
| `doc/Doxyfile` | Configuration Doxygen (versionnée) |
| `doc/README.md` | Mode d'emploi de la génération de la documentation |
| `doc/html/` | Documentation générée (non versionnée) |

### Régénérer proprement

```bash
rm -rf doc/html
doxygen doc/Doxyfile
```

---

## Gestion des ressources (Ollama)

Ollama peut consommer plusieurs Go de RAM/VRAM pendant qu'un modèle est chargé. Pour éviter qu'il tourne en permanence :

```bash
# Désactiver le démarrage automatique au boot
sudo systemctl disable ollama

# Démarrer manuellement avant de travailler sur le projet
sudo systemctl start ollama

# Arrêter une fois terminé
sudo systemctl stop ollama

# Vérifier l'état
systemctl status ollama
```

---

## Auteurs

- ColoMiel
- Origanire
- Hexoneer