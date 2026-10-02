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