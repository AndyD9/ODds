# 0004 — `data/` pour l'état irremplaçable, `research/data/` pour le dérivé

**Statut :** acceptée · **Date :** 2026-09-18 · **Code :** `src/odds/chemins.py`

## Contexte

Le carnet de paris et la base de collecte vivaient dans `research/data/`, à côté de 42 Mo de
cache brut football-data, du parquet réingérable et des artefacts de recherche. Ce dossier est
ignoré par git et traité comme jetable — le README lui-même invite à l'effacer pour repartir.
La docstring de `paper.py` interdisait de mélanger le carnet et le cache ; l'arborescence faisait
l'inverse. Chaque module recalculait par ailleurs sa propre `RACINE` et ses propres chemins.

## Décision

Deux dossiers, distingués par une seule question : *peut-on le régénérer ?*

- `data/` — **état** : `paper.db` (décisions datées), `odds_history.db` (prix qui n'existent
  plus une fois le match commencé). À sauvegarder.
- `research/data/` — **dérivé** : cache brut, `matches.parquet`, tables de fiabilité. Un script
  les refait.

Tous les chemins sont définis dans `odds.chemins`, et lus à l'appel — ce qui les rend
détournables en test. Une installation qui a encore ses bases à l'ancien emplacement les voit
déplacées au premier accès (`chemins.rapatrier`), plutôt que de repartir d'un carnet vide sans le
dire.

## Options écartées

- **Tout laisser dans `research/data/` et documenter.** La documentation existait déjà et n'a
  pas suffi.
- **Un chemin configurable dans `.env`.** Utile un jour pour un disque externe, mais la question
  du jour est la séparation, pas l'emplacement. Le module `chemins` est l'endroit où un tel
  réglage se brancherait.

## Conséquences

- `.gitignore` gagne une ligne : `data/`.
- Les scripts de recherche lisent leurs entrées via `chemins` et non par chemin relatif au
  répertoire courant.
