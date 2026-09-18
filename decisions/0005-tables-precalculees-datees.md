# 0005 — Les tables précalculées portent le rho et le catalogue qui les ont produites

**Statut :** acceptée · **Date :** 2026-09-18 · **Code :** `src/odds/analysis/fiabilite.py`, `research/fiabilite_buts.py`

## Contexte

La réussite historique d'un marché de buts (« ce niveau de probabilité s'est vérifié 61,6 % du
temps, n = 211 ») demande d'ajuster 150 626 matrices de score. Elle est donc précalculée par un
script de recherche dans un parquet que l'application lit. Ce parquet dépend de deux constantes
du code : `RHO_DEFAUT`, qui fixe chaque matrice dérivée du 1X2 seul, et le catalogue des
marchés, dont les prédicats décident ce qui compte pour « réussi ».

Changer rho sans relancer le script laissait une table lisible, plausible, et fausse. C'est la
pire forme d'erreur : rien ne casse.

## Décision

Le script écrit dans les métadonnées du parquet le rho et une signature du catalogue. Le lecteur
compare aux valeurs de la version courante et, en cas d'écart, renvoie une table **vide** avec un
motif (`.attrs["motif"]`) que l'interface affiche à la place de la colonne. Le moteur de mise voit
alors « signal absent », ce qui est exactement l'état des connaissances.

## Options écartées

- **Recalculer à la volée, en cache.** Plusieurs minutes à la première ouverture de page, à
  chaque changement de version. Écarté pour l'usage quotidien ; reste la bonne réponse pour un
  test d'intégration.
- **Un numéro de version manuel.** Il faut penser à l'incrémenter — c'est le problème qu'on
  cherche à supprimer.

## Conséquences

- Tout changement de `RHO_DEFAUT` ou du catalogue rend la colonne vide jusqu'à
  `uv run python research/fiabilite_buts.py`. C'est voulu.
- Le même mécanisme s'applique à toute table précalculée future : écrire ce dont elle dépend,
  refuser de la servir sinon.
