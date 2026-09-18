# Décisions techniques

Les fichiers de `prereg/` fixent des **hypothèses** avant de les mesurer. Ceux-ci fixent des
**choix de construction** : ce qu'on a retenu, ce qu'on a écarté, et pourquoi. Un choix qu'on ne
retrouve que dans un commentaire de code finit par être défait par quelqu'un qui n'a pas vu le
commentaire.

Format : contexte, décision, options écartées, conséquences. Une décision remplacée n'est pas
effacée : son statut passe à « remplacée » et pointe vers la suivante.

| n° | décision | statut |
|---|---|---|
| [0001](0001-base-du-carnet-separee.md) | Le carnet de paris vit dans sa propre base, hors du cache | acceptée |
| [0002](0002-ordonnancement-des-credits.md) | Les crédits API sont placés sur les coups d'envoi, avec une réserve | acceptée |
| [0003](0003-vocabulaire-unique-de-la-collecte.md) | Un seul vocabulaire `(market, selection)` pour toutes les sources | acceptée |
| [0004](0004-etat-et-derive.md) | `data/` pour l'état irremplaçable, `research/data/` pour le dérivé | acceptée |
| [0005](0005-tables-precalculees-datees.md) | Les tables précalculées portent le rho et le catalogue qui les ont produites | acceptée |
| [0006](0006-jambes-groupees.md) | Les jambes d'une couverture sont des paris ordinaires reliés par un `groupe` | acceptée |
