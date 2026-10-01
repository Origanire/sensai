# Agent chat Twitch

Sensai lit le chat d'une chaîne Twitch et répond aux viewers qui le
mentionnent. Il se souvient de chaque viewer d'un stream à l'autre.

---

## Lancer l'agent

Aucun compte Twitch, aucun token : l'agent se connecte au chat **en lecture
seule et en anonyme**. Il ne peut pas écrire dans le chat.

```bash
ollama serve                       # dans un autre terminal
python3 -m src.agents.chat_agent
```

Pour ne tester que le connecteur, sans modèle ni mémoire :

```bash
python3 -m src.tools.twitch_chat NOM_DE_CHAINE
```

---

## Configuration

Les réglages de cet agent sont dans `config/chat_agent.yaml`, séparés du
`config.yaml` global pour éviter que chaque agent se marche dessus.

| Clé | Rôle |
|---|---|
| `channel` | chaîne Twitch à écouter |
| `trigger` | mention à laquelle Sensai répond (`@sensai`) |
| `command_prefix` | préfixe des commandes de modération (`!`) |
| `remember_command` | nom de la commande d'enregistrement (`remember`) |
| `fact_saved_message` | réponse quand un fait a été enregistré |
| `viewer_not_found_message` | réponse quand le viewer visé est inconnu |
| `history_token_budget` | taille max de l'historique envoyé au modèle |

Le modèle, l'URL d'Ollama et la température restent dans `config.yaml`.

Les instructions données au modèle sont dans `prompts/` :

| Fichier | Rôle |
|---|---|
| `viewer_context.txt` | gabarit du contexte injecté (profil + résumé) |
| `summarize.txt` | consignes de résumé de l'historique |

Elles sont **en anglais** : les modèles suivent nettement mieux une consigne
en anglais, et répondent quand même dans la langue du viewer. Les textes lus
par les viewers, eux, sont dans la config et suivent la langue du stream.

---

## Utilisation

### Parler à Sensai

N'importe quel viewer, en le mentionnant :

```
kevinaigre : @sensai c'est quoi ce jeu ?
Sensai     : @kevinaigre C'est Elden Ring, de FromSoftware.
```

Sans la mention, le message est ignoré.

### Enregistrer un fait sur un viewer

Réservé au **streamer et aux modérateurs** :

```
!remember kevinaigre déteste les spoilers
```

Un viewer normal qui tape cette commande n'obtient aucune réponse : elle reste
discrète dans un chat public. Le viewer visé doit avoir écrit au moins une
fois, sinon son identifiant Twitch est inconnu.

---

## Ce que Sensai mémorise

Tout est dans `sensai.db` (SQLite, non versionnée), indexé sur l'**identifiant
Twitch** du viewer et non sur son pseudo : un viewer qui se renomme garde sa
mémoire, et quelqu'un qui reprend un ancien pseudo n'hérite de rien.

| Table | Contenu |
|---|---|
| `viewers` | identité et statistiques (visites, messages, temps d'activité) |
| `viewer_messages` | conversations avec Sensai, archivées après résumé |
| `viewer_facts` | faits enregistrés via `!remember` |
| `viewer_summaries` | résumés des échanges anciens |

**Ce qui n'est pas enregistré :** le contenu des messages qui ne s'adressent
pas à Sensai. Ils sont comptés, jamais stockés. On sait qu'un viewer a écrit
42 messages ce soir, pas ce qu'il a écrit.

Le schéma évolue tout seul au lancement : les colonnes manquantes sont
ajoutées, et les tables d'un ancien schéma sont renommées en `*_v1` plutôt que
supprimées. Il n'y a rien à faire sur une base existante.

### Compression de l'historique

Quand l'historique d'un viewer dépasse `history_token_budget`, les plus anciens
messages sont résumés en un bloc et archivés. Les 4 derniers sont gardés tels
quels. La consommation réelle est mesurée via `prompt_eval_count`, renvoyé par
Ollama à chaque appel.

### Statistiques

Les compteurs sont tenus en mémoire pendant le stream et écrits en base **une
seule fois, à la fermeture** : une ligne par viewer au lieu d'une écriture par
message. Un lancement de l'agent correspond à une visite.

---

## Limites connues

- **Traitement bloquant.** Pendant qu'Ollama génère une réponse, le socket
  n'est plus lu. Sur un chat très actif, les messages s'accumulent (voir #61).
- **Arrêt brutal.** Un `kill -9` ou une coupure de courant perd les
  statistiques du stream en cours. `Ctrl+C` et les plantages normaux sont
  couverts.
- **Le profil ne se remplit qu'à la main**, via `!remember`. L'extraction
  automatique a été testée puis retirée : trop peu fiable avec un modèle 3B
  en direct (voir #52).
- **Pas de personnalité.** Sensai répond comme un assistant générique
  (voir #47).
