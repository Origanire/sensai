# Agent chat Twitch

Sensai lit le chat d'une chaîne Twitch et répond aux viewers qui le
mentionnent. Il se souvient de chaque viewer d'un stream à l'autre.

---

## Lancer l'agent

Sans configuration, l'agent se connecte au chat **en lecture seule et en
anonyme** : ses réponses n'apparaissent que dans le terminal.

Pour qu'il **réponde dans le chat**, il lui faut un compte bot Twitch :

1. Créer un compte Twitch dédié au bot (ex. `sensai_bot`).
2. Générer pour ce compte un token OAuth avec les scopes `chat:read` et
   `chat:edit` (par exemple via [twitchtokengenerator.com](https://twitchtokengenerator.com)).
3. Copier `.env.example` en `.env` et remplir `TWITCH_BOT_USERNAME` et
   `TWITCH_OAUTH_TOKEN`.

Au lancement, l'agent indique `Listening on #chaine as sensai_bot`. Si Twitch
refuse le token, il s'arrête avec un message qui pointe vers `.env`. Toutes
les réponses (mention, `!remember`, `!moment`, `!search`) partent alors dans le
chat ; Twitch coupant à 500 caractères, les messages plus longs sont tronqués
proprement avec `...`.

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
| `command_prefix` | préfixe des commandes (`!`) |
| `remember_command` | nom de la commande d'enregistrement (`remember`) |
| `fact_saved_message` | réponse quand un fait a été enregistré |
| `viewer_not_found_message` | réponse quand le viewer visé est inconnu |
| `moment_command` | nom de la commande de moment fort (`moment`) |
| `moment_saved_message` | réponse quand un moment fort a été ajouté |
| `moment_usage_message` | réponse quand `!moment` est tapé sans description |
| `search_command` | nom de la commande de recherche web (`search`) |
| `search_usage_message` | réponse quand `!search` est tapé sans question |
| `moment_cooldown` | délai minimum entre deux `!moment` d'un même viewer (s) |
| `burst_window` | fenêtre de détection d'un pic d'activité (s) |
| `burst_audience_window` | fenêtre de comptage des chatteurs actifs (s) |
| `burst_ratio` | messages requis par chatteur actif pour un pic |
| `burst_min_messages` | seuil minimum d'un pic, quelle que soit l'audience |
| `burst_cooldown` | silence après un pic détecté (s) |
| `burst_description` | texte du moment fort noté pour un pic |
| `history_token_budget` | taille max de l'historique envoyé au modèle |

Le modèle, l'URL d'Ollama et la température restent dans `config.yaml`, avec
les réglages partagés de l'agent Internet et d'OBS :

| Clé (`config.yaml`) | Rôle |
|---|---|
| `internet_agent.cooldown_seconds` | délai minimum entre deux `!search`, tous viewers confondus (30) |
| `internet_agent.max_results` | résultats web donnés au modèle (5) |
| `obs.enabled` | met à jour l'overlay OBS à chaque `!search` |
| `obs.host` / `obs.port` | serveur WebSocket d'OBS (`localhost:4455`) |
| `obs.password` | mot de passe WebSocket ; `OBS_WEBSOCKET_PASSWORD` dans `.env` est prioritaire |
| `obs.source_name` | source Texte à mettre à jour (`SensaiOverlay`) |

Sans section `internet_agent` ou `obs`, des valeurs par défaut s'appliquent et
l'overlay est désactivé.

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

### Noter un moment fort

Ouvert à **tous les viewers** :

```
!moment victoire contre Messmer après 37 tentatives
```

La ligne est ajoutée à la section « Moments forts » de `stream_report.json`,
précédée de l'heure d'envoi du message et suivie de son auteur
(`- 22h15 : victoire contre Messmer… (kevinaigre)`). Le texte est écrit tel
quel, sans passer par le modèle. Un même viewer ne peut noter qu'un moment
toutes les `moment_cooldown` secondes ; les suivants sont ignorés sans réponse.

### Pics d'activité

Sensai note aussi tout seul un moment fort quand le chat s'emballe :

```
- 22h16 : pic d'activité dans le chat (42 messages en 10 s)
```

Le seuil s'adapte à l'audience. L'agent étant connecté en anonyme, il n'a pas
accès au nombre réel de viewers : il compte à la place les **chatteurs
actifs**, ceux qui ont écrit pendant les `burst_audience_window` dernières
secondes. Un pic est noté quand au moins
`max(burst_min_messages, chatteurs actifs × burst_ratio)` messages arrivent en
`burst_window` secondes. Avec les valeurs par défaut (10 s, ratio 0,5,
minimum 8) :

| Chatteurs actifs | Messages en 10 s pour un pic |
|---|---|
| 5 | 8 |
| 40 | 20 |
| 300 | 150 |

Après un pic, aucun autre n'est noté pendant `burst_cooldown` secondes, pour
qu'une même vague ne soit pas comptée plusieurs fois. Rien n'est détecté
pendant les `burst_audience_window` premières secondes après le lancement de
l'agent, le temps de mesurer l'audience.

Les moments forts, notés à la main ou détectés, servent ensuite aux
recommandations stratégiques (`src/tools/strategy.py`) une fois
le compte-rendu archivé.

### Chercher sur le web

Ouvert à **tous les viewers** :

```
viewer : !search qui a gagné l'elden ring boss rush
Sensai : @viewer D'après mes recherches, ... https://www.nexusmods.com/eldenring/mods/2905
```

La question est transmise à l'agent Internet (`ask_internet`), qui cherche
sur le web et répond en citant sa source. Si la réponse dépasse la limite de
Twitch, elle est coupée et l'URL de la source est remise à la fin. Si la
recherche ou le modèle est indisponible, Sensai répond « Recherche
indisponible pour le moment. ».

Une recherche bloque l'agent plusieurs secondes : un **cooldown global**
(`internet_agent.cooldown_seconds`) ignore sans réponse les `!search` qui
arrivent trop tôt, quel que soit le viewer.

### Overlay OBS

À chaque `!search` réussi, un fait court (une ou deux phrases, 160 caractères
max, `get_quick_fact`) remplace le texte de la source OBS `obs.source_name`.

Mise en place dans OBS (28 ou plus) :

1. *Outils > Paramètres du serveur WebSocket* : cocher *Activer le serveur
   WebSocket* (port 4455). Si l'authentification est activée, mettre le mot de
   passe dans `.env` (`OBS_WEBSOCKET_PASSWORD`).
2. Ajouter à la scène une source *Texte (GDI+)* nommée `SensaiOverlay`.

Si OBS est fermé, l'overlay est simplement sauté (`[OBS] injoignable...` dans
le terminal) et le fait n'est même pas calculé. Une source introuvable ou un
mauvais mot de passe sont signalés par un message clair, sans arrêter l'agent.

> **WSL :** si Sensai tourne dans WSL et OBS sous Windows, `localhost` ne
> pointe vers Windows qu'avec le réseau en mode *mirrored*. Sinon, mettre dans
> `obs.host` l'IP de Windows (`ip route show default | awk '{print $3}'`) et
> autoriser le port 4455 dans le pare-feu.

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
- **`!search` est lent.** Une recherche enchaîne une recherche web et deux à
  quatre appels au modèle (dont le fait de l'overlay) : comptez 10 à 30 s
  avec llama3.2, pendant lesquelles le chat n'est pas lu (voir #61).
- **Sources approximatives.** Le modèle oublie parfois de citer ses sources :
  l'URL du premier résultat est alors ajoutée d'office, sans garantie qu'elle
  soit celle qui a servi. DDGS échoue aussi par intermittence ; une seconde
  recherche avec la question brute est tentée avant d'abandonner.
- **Pics d'activité sans contexte.** Le contenu des messages n'étant pas
  stocké, un pic est noté sans dire ce qui l'a provoqué ; un `!moment` permet
  de préciser.
- **Pas de personnalité.** Sensai répond comme un assistant générique
  (voir #47).
