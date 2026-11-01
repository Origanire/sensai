# Mesures locales du 1er novembre 2026

Machine mesurée : Apple M5 Pro, 24.0 Gio de mémoire unifiée.

Protocole : API Ollama locale, contexte 8192, température 0,3, seed 42, think=false. Une seule génération par condition, même entrée. Le premier appel de chaque modèle peut inclure son chargement : **ces durées ne permettent pas de conclure que le plafond de tokens accélère le modèle**. Aucun message Twitch envoyé.

| Modèle | Plafond | Tokens produits | Temps total (s) | Taille chargée Ollama (Gio) | size_vram (Gio) | Taille chargée / RAM physique |
|---|---:|---:|---:|---:|---:|---:|
| llama3.2:latest | 32 | 19 | 1.52 | 2.88 | 2.88 | 12.0% |
| llama3.2:latest | 128 | 19 | 0.18 | 2.88 | 2.88 | 12.0% |
| qwen3:14b | 32 | 13 | 4.73 | 9.60 | 9.60 | 40.0% |
| qwen3:14b | 128 | 13 | 0.46 | 9.60 | 9.60 | 40.0% |
| ministral-3:14b | 32 | 18 | 4.16 | 8.74 | 8.74 | 36.4% |
| ministral-3:14b | 128 | 18 | 0.57 | 8.74 | 8.74 | 36.4% |

`size` et `size_vram` sont les valeurs de `/api/ps` après chaque réponse, pas un pic de RSS ni la mémoire libre du système. Plusieurs modèles peuvent cohabiter ; le JSON conserve la liste complète à chaque mesure. macOS, OBS, le navigateur, Whisper et les autres programmes consomment aussi de la mémoire. Ces mesures complètent les 20 cas du 16 octobre, sans constituer un nouveau classement de qualité.

## Effet observé d’un paramètre

Sur la question courte, 32 → 128 ne change pas le nombre de tokens produits. Expérience distincte avec une demande de trois phrases et Ministral :

### num_predict = 16

16 tokens ; 4.28 s ; arrêt `length`.

> 1. **Stockage sécurisé des données** : Un bot Twitch

### num_predict = 128

128 tokens ; 3.98 s ; arrêt `length`.

> 1. **Stockage sécurisé des données** : Un bot Twitch peut enregistrer les préférences déclarées par les utilisateurs (comme leurs commandes, paramètres ou choix explicites) dans une base de données dédiée, en associant chaque information à un identifiant unique (ex. : nom d’utilisateur ou ID Twitch), sans jamais en déduire ou inventer des données non communiquées.

2. **Validation explicite** : Pour éviter toute interprétation erronée, le bot ne retient que les informations **directement confirmées** par l’utilisateur (ex. : via des commandes comme

Le plafond borne la génération, il ne fixe pas la longueur souhaitée. Une limite trop basse peut couper une phrase ; le prompt reste nécessaire pour une réponse courte et complète. Ce petit test isole le plafond (même seed/température/entrée), mais une répétition et un ordre alterné seraient nécessaires pour une conclusion robuste sur la latence. La configuration de production n’a pas été modifiée par le benchmark.

Rejouer depuis la racine : `.venv/bin/python doc/evaluations/defense-2026-11-01/benchmark.py`. Cette commande remplace le fichier de résultats local. Les sorties sont des réponses brutes de modèle, pas des vérités validées.

Les deux générations de l’expérience longue atteignent leur plafond (`done_reason=length`) : 128 tokens donne plus de contenu que 16, mais ne suffit pas ici à terminer les trois phrases. Ce résultat ne justifie pas de réduire arbitrairement la limite de production à 128.

Captures hors ligne : [dashboard](prompt-exact.png), [détail du prompt](prompt-detail.png), [réponse factuelle](reponse-factuelle.png). Le [JSON du prompt](prompt-exact.json) accompagne la capture ; il ne contient pas les identifiants OAuth.
