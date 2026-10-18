# Évaluation locale du 16 octobre 2026

Machine : Apple M5 Pro, 24 Go de mémoire. Qwen3 14B Q4_K_M : 9,3 Go téléchargés,
environ 10 Go chargés sur GPU, contexte 8 192 tokens, thinking désactivé.

20 scénarios synthétiques identiques, même nouvelle personnalité pour les deux
modèles, une seule génération par cas. Ce test compare les modèles, pas deux
versions complètes du produit. Température 0,7 : les résultats peuvent varier.
Médiane génération + filtrage : llama3.2 0,43 s ; Qwen3 14B 0,84 s.
Les temps excluent routage, Twitch et web. Le premier appel Qwen prend 4,95 s.
Le refus d'une injection est inclus (0 s) ; ce n'est pas une mesure de débit.

Observations manuelles :
- Qwen identifie Sam comme soigneur ; llama répond qu'il ne sait pas.
- Qwen répond « Gg » sans inventer de niveau terminé ; llama invente ce niveau.
- Qwen reconnaît ne pas voir le streamer ; llama prétend le voir de loin.
- Qwen reconnaît l'absence de mémoire ; llama invente un oubli.
- La première passe Qwen prétendait essayer de passer pour un humain et répondait
  en français à une salutation anglaise. Des exemples ont été ajoutés au prompt.
  Les vérifications ciblées finales corrigent ces deux cas (`final-checks.json`).
- Des tournures maladroites et des imprécisions restent possibles. Pas de score
  de fiabilité généralisable à partir de ce petit échantillon.

Recherche réelle Qwen : Voyager/NASA, réponse avec URL en 5,29 s. La formulation
« a traversé l'espace interstellaire » est imprécise : il y est entré en 2012.
Ce résultat démontre la liaison web, pas une exactitude parfaite de la synthèse.
La recherche Python avec filtre de domaine n'a trouvé aucun résultat après deux
essais (5,46 s) et a renvoyé le message d'indisponibilité prévu.

Aucun message de test n'a été publié sur Twitch. Les sorties JSON sont des sorties
brutes du bot à évaluer, pas des faits validés.

Sources techniques :
- https://ollama.com/library/qwen3:14b
- https://docs.ollama.com/capabilities/thinking
- https://dev.twitch.tv/docs/api/reference/#send-chat-message
