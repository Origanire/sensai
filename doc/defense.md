# Complément de soutenance — 1er novembre 2026

Ce document répond aux commentaires d'évaluation. Il ne modifie ni les notes
attribuées ni les résultats historiques. Les tests et mesures nouveaux sont
identifiés séparément. Le compte rendu initial décrivait aussi une machine WSL
8 Go ; les mesures de ce complément concernent le Mac local.

## Scénario et traçabilité du brief à la preuve

Scénario : un streamer débutant prépare sa chaîne, lance une session, joue en
restant disponible pour ses viewers, puis consulte un bilan. Un habitué revient,
un nouveau pose une question, un participant tente une injection. Lumi aide sans
prendre la place du streamer ni présenter une supposition comme un fait.

| Étape | Besoin et user stories | Implémentation | Démonstration / preuve |
|---|---|---|---|
| S1 Préparer | Configuration locale, US-DASH, US-SYNC | dashboard, bot_settings, twitch_context | Choisir la chaîne à l'arrêt, vérifier le contexte |
| S2 Accueillir | M1 mémoire viewer, M2 compression, US-AUTO | memory, auto_memory, chat_agent | Tests de persistance et de correction ; ne pas promettre une mémoire exhaustive |
| S3 Jouer et échanger | US-MASC, US-AUDIO | mascot, live_audio, chat_context | Réaction courte ; appel vocal puis réponse écrite |
| S4 Répondre utilement | R1, inter-agent #43, T3 routage | channel_rag, router, web_search | Question FAQ puis recherche explicite ; signaler un échec réseau |
| S5 Protéger le chat | EV2, EV4 | guardrails, tests/adversarial | Adresse de test masquée, injection refusée |
| S6 Faire le bilan | M4, X3, X5 / rapports planifiés | report, export, scheduled_reports | `!event` par un modérateur ; consulter/exporter le bilan ; veille via CLI |
| S7 Expliquer le fonctionnement | US-PROMPT, T1, T5 | ollama_client, MCP CLI, JSON contraint | Inspecter la requête exacte ; outil MCP dans une séquence CLI séparée |

Les user stories complètes et critères sont dans [user_stories.md](user_stories.md).
Le tableau relie les fonctionnalités au scénario ; présence dans le code,
validation automatisée et démonstration réelle sont des niveaux de preuve distincts.

## Abandons, reports et évolution du périmètre

| Élément | Story concernée | Décision dans le périmètre évalué | État vérifié aujourd'hui et conséquence |
|---|---|---|---|
| Overlay OBS | Inter-agent #44, les deux stories overlay et panne OBS | Écarté de la démo principale selon le retour reçu : installation et écran supplémentaires | Code toujours présent (`search_and_share`) et `obs.enabled: true` dans la configuration. Ce n'est pas un abandon technique. Aucune preuve nouvelle de connexion OBS ; ne pas le présenter comme validé en live. |
| RAG documentaire global dans le bot | R1, réponse sur horaires/setup et refus si absent | Mis de côté dans le bot lors de l'évaluation | CLI `/ingest` et `/ask` conservée. Le bot actuel utilise `ChannelRAG` sur FAQ/fiche par chaîne : recherche lexicale puis embeddings si disponibles. Réintégration après le périmètre évalué, avec `test_channel_rag.py`. |
| Réponse orale de Lumi | US-AUDIO | Hors périmètre initial | Transcription entrante et réponse écrite seulement. Pas de TTS ni de reconnaissance certaine du streamer. |
| Lore inféré automatiquement d'un titre | US-SYNC / personnalisation | Non retenu comme source de faits confirmés | Le titre est une annonce, pas une observation. Les références de communauté doivent être confirmées dans la fiche/FAQ. |

Les raisons OBS ci-dessus justifient un périmètre de démonstration, pas une
chronologie de décision reconstruite. Le retour d'évaluation est la source du
statut historique ; le code est la source du statut actuel.

## Alternatives techniques concrètes

| Décision | Option retenue | Alternative | Avantage de l'alternative | Coût / raison de ne pas la retenir actuellement | Quand reconsidérer |
|---|---|---|---|---|---|
| Génération | Modèle local via Ollama | API distante | Libère la mémoire locale, matériel serveur | Dépendance réseau, coût variable, transmission des messages | Si le matériel ne tient pas la latence requise et avec une politique de données explicite |
| Connaissance chaîne | FAQ/fiche locale et RAG par chaîne | Toute la FAQ dans chaque prompt | Simplicité, pas d'embedding | Coût en contexte croissant, informations non pertinentes | Pour une FAQ très courte |
| Audio | Son Twitch transcrit localement | Micro dédié avec détection de fin de parole | Moins de délai, moins de musique/jeu dans l'entrée | Installation chez le streamer, permissions et routage audio | Si l'interaction orale devient le cas d'usage principal |
| Garde-fous | Règles déterministes puis consignes | Modèle de modération séparé | Compréhension de formulations plus variées | Latence supplémentaire, coût mémoire, erreurs possibles | Si les faux négatifs mesurés le justifient |
| Mémoire | SQLite par chaîne et citations de préférences | Résumé libre de tous les messages | Couverture plus large | Risque de mémoriser une inférence ou une plaisanterie | Après protocole de correction/oubli et évaluation dédiée |
| Réactivité | Rafraîchissement Twitch périodique | Événements Twitch | Réaction plus rapide aux changements | Gestion des abonnements/reconnexions | Si une minute de retard devient gênante |

Ce sont des alternatives d'architecture, pas seulement « un modèle plus gros »
ou « mieux réfléchir avant ». Chaque choix doit être réévalué avec une mesure.

## Culture IA : explications à donner à l'oral

- **Paramètres** : poids appris du réseau. « 14B » indique environ 14 milliards de
  paramètres ; cela ne garantit ni vérité ni mémoire des viewers. La mémoire de
  Lumi est externe, dans SQLite, et réinjectée dans les messages.
- **Familles** : Llama, Qwen et Ministral correspondent à des familles différentes,
  avec entraînements, tokeniseurs et capacités propres. Une taille proche ne les
  rend pas équivalentes. Les métadonnées locales mesurées sont dans le JSON de preuve.
- **Quantification** : réduire la précision de représentation des poids diminue
  leur empreinte, avec un compromis possible de qualité. Q4_K_M est une variante
  de quantification par blocs, pas « exactement quatre bits pour tout le modèle ».
  À titre d'ordre de grandeur, 14 milliards de poids à 16 bits représentent
  28 milliards d'octets pour les poids seuls ; cela exclut cache et exécution.
- **Mémoire d'exécution** : poids, cache d'attention et buffers contribuent à la
  mémoire. Le fichier téléchargé n'est pas la RAM consommée. Sur Apple Silicon,
  CPU/GPU partagent la mémoire : ne pas additionner `size` et `size_vram` comme
  deux allocations indépendantes, ni les confondre avec la mémoire libre du Mac.
- **Embeddings** : vecteurs numériques représentant des textes pour rechercher
  des passages proches. La similarité cosinus mesure une proximité, pas la vérité.
  Un embedding ne rédige pas la réponse : le modèle génératif reçoit les passages
  récupérés. BGE-M3 est configuré ; sa disponibilité doit être vérifiée avant démo.
- **RAG** : découpage → recherche → sélection de passages → génération avec ces
  passages. Aucun réentraînement des poids. Une mauvaise récupération peut produire
  une mauvaise réponse ; d'où l'isolation par chaîne et la possibilité d'abstention.
- **Paramètres de génération** : température pour l'échantillonnage, `num_predict`
  pour le plafond de sortie, `num_ctx` pour la fenêtre de contexte. Température
  basse ne garantit pas l'exactitude. `think: false` demande une réponse directe
  sur les modèles compatibles ; ce n'est pas un filtre de sécurité.

Sources primaires : [API Ollama](https://github.com/ollama/ollama/blob/main/docs/openapi.yaml),
[embeddings Ollama](https://github.com/ollama/ollama/blob/main/docs/capabilities/embeddings.mdx),
[Ministral 3, rapport technique](https://arxiv.org/abs/2601.08584),
[variantes Ministral dans Ollama](https://ollama.com/library/ministral-3/tags).

## Démo en 6 minutes et mode secours

| Temps | Action | Résultat attendu | Secours |
|---|---|---|---|
| 0:00–0:45 | Présenter S1 et ouvrir Pilotage | Chaîne et état visibles | Capture du dashboard |
| 0:45–1:30 | Essai privé « on est sur quel live ? » | Identité de la chaîne, pas ancien jeu | Capture de réponse factuelle |
| 1:30–2:30 | Essai « salut Lumi » puis ouvrir les requêtes | Messages, ordre et options réellement préparés pour `/api/chat` | Capture et JSON de l'essai privé |
| 2:30–3:15 | Injection puis e-mail synthétique `demo@example.org` | Refus / masquage | Tests de garde-fous et rapport adversarial |
| 3:15–4:15 | Expliquer M1/US-AUTO, montrer les tests | Persistance par identité/chaîne, pas mémoire parfaite | Sortie pytest sauvegardée |
| 4:15–5:00 | Audio si disponible : « Lumi, quel jeu ? » | Réponse écrite, délai explicitement annoncé | Montrer le code/test ; ne pas faire passer une capture pour une validation audio |
| 5:00–6:00 | Bilan, benchmark, limites | Chiffres et limites séparés | Rapport Markdown et données JSON hors ligne |

Les captures sont des preuves datées, **pas un direct**. En panne Twitch, ne pas
lancer de faux chat. En panne Ollama, ouvrir les captures/JSON locaux et présenter
les tests séparément. Aucune nouvelle capture audio réelle n'est revendiquée.

## Inspection exacte du contexte

Pilotage → essai privé → « Requêtes exactes de cet essai vers Ollama ». Chaque
objet est une copie du payload au point d'envoi HTTP : rôles, contenu, modèle,
options, schéma JSON éventuel et `think`. Plusieurs appels peuvent apparaître
(routeur puis réponse, ou recherche). Une réponse déterministe ou bloquée ne
produit pas de prompt. Une requête capturée peut échouer lors du transport.

Cette inspection concerne **l'essai privé**, sans historique viewer. Dans le bot,
`build_prompt` assemble persona/chaîne et mémoire, contexte récent puis historique
borné ; `compress` résume les anciens tours. La capture privée ne démontre donc
pas à elle seule la compression M2 : utiliser les tests et le code pour cette partie.
Aucune capture automatique des conversations réelles n'est activée.

## Preuves nouvelles et points restant à démontrer

- [Mesures mémoire et effet du plafond de tokens](evaluations/defense-2026-11-01/README.md) : données réelles, scripts et limites du protocole.
- [Capture du prompt](evaluations/defense-2026-11-01/prompt-detail.png) et [payload complet](evaluations/defense-2026-11-01/prompt-exact.json).
- [Dashboard et réponse générée](evaluations/defense-2026-11-01/prompt-exact.png).
- [Réponse factuelle sans modèle](evaluations/defense-2026-11-01/reponse-factuelle.png).
- [145 tests réussis](evaluations/defense-2026-11-01/tests.txt).

Captures réalisées sur le dashboard local de validation, port 8767, avec la chaîne
configurée OriganireTV. Le bot de ce dashboard est arrêté : les réponses montrées
sont des essais privés réels. Aucun message de cette validation n'a été publié
sur Twitch. Les captures ne prétendent pas démontrer l'écoute audio en direct.

La liste `/api/tags` mesurée ne contient pas BGE-M3 : la configuration RAG ne
prouve donc pas que les embeddings sont disponibles sur cette installation.
Le chemin lexical est présent et testé. Ne pas prétendre avoir démontré le repli
sémantique en live sans installer le modèle et effectuer le test correspondant.

Les critères déjà validés (engagement, EV2/T1/T3 en démo, etc.) restent fondés sur
leurs preuves historiques ; aucun nouveau gain d'engagement n'est inventé ici.
