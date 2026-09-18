# 0002 — Les crédits API sont placés sur les coups d'envoi, avec une réserve

**Statut :** acceptée · **Date :** 2026-09-18 · **Code :** `src/odds/data/collect.py`, `planifier`

## Contexte

The Odds API offre 500 crédits par mois. Chaque passe sur un championnat coûte un crédit par
marché et par région. Le budget quotidien (`ODDS_API_BUDGET_JOUR`) était un plafond, pas un
calendrier : la collecte retenait les premiers championnats du plan jusqu'à épuisement, et tout
partait au petit matin. Relevé du 2026-09-18 : douze passes, quatorze crédits, budget vidé avant
midi, plus rien pour relever les cotes avant les matchs du soir.

Or le CLV, seul critère lisible sur quelques dizaines de paris (prereg 0001 §5), se mesure contre
la **dernière cote observée avant le coup d'envoi**. Une passe à T−1 h vaut toutes celles de la
matinée.

## Décision

Une fonction pure `planifier(plan, dispo, cout_unitaire, dernieres_passes, maintenant)` décide
quels championnats interroger, selon trois fenêtres avant le coup d'envoi (clôture ≤ 2 h,
pré-match ≤ 8 h, veille ≤ 36 h), chacune avec une cadence minimale entre deux passes. Une
**réserve** met de côté le coût de la passe de clôture de chaque championnat dont le coup d'envoi
tombe avant la prochaine remise à zéro du budget (minuit UTC + fenêtre de clôture). Chaque ligne
écartée porte son **motif**.

## Options écartées

- **Une passe par heure, tous championnats.** Simple, mais 5 championnats × 2 marchés × 24 h
  dépasse le budget mensuel en quatre jours.
- **Un cron par coup d'envoi.** Exact, mais l'horaire des matchs vient de l'API elle-même ; il
  faudrait un ordonnanceur externe qui lise l'API pour se programmer. L'ordonnanceur interne fait
  la même chose sans dépendance.
- **Un budget par championnat.** Ne résout pas le problème : c'est l'heure qui compte, pas la
  répartition.

## Conséquences

- Le budget n'est plus consommé linéairement : les matins sont creux, les soirées pleines.
- La fonction est testable sans réseau ni budget réel (`tests/test_planification.py`).
- Le journal de collecte affiche chaque championnat avec sa fenêtre et son motif : un
  ordonnanceur qui n'explique pas ce qu'il écarte est indébogable, et celui-ci arbitre des crédits
  qu'on ne peut pas racheter.
