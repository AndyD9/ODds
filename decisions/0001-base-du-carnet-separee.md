# 0001 — Le carnet de paris vit dans sa propre base

**Statut :** acceptée · **Date :** 2026-09-18 · **Code :** `src/odds/paper.py`

## Contexte

La collecte de cotes écrit dans `odds_history.db`. Cette base est traitée comme un cache : on
peut l'effacer et recollecter, et plusieurs commandes le supposent. Le carnet de paris papier est
l'inverse : une suite de décisions datées, avec la cote prise, la mise proposée et la mise réelle.
Il n'existe nulle part ailleurs.

## Décision

Le carnet a sa propre base SQLite, `paper.db`, avec son propre schéma et sa propre migration.
Il **lit** la base de collecte pour capturer la cote de clôture, mais n'y écrit jamais, et rien
dans la collecte ne dépend de lui.

## Options écartées

- **Une table `pari` dans `odds_history.db`.** Une seule connexion, un seul fichier. Écartée :
  « j'efface et je recollecte » détruirait l'historique de décisions, et c'est précisément le
  geste que la base de collecte invite à faire.
- **Un fichier CSV ou parquet.** Simple à lire à la main. Écarté : le règlement met à jour des
  lignes existantes, le CLV se capture après coup, et deux processus (collecte horaire, tableau
  de bord) peuvent toucher aux données en même temps. SQLite donne les écritures atomiques et le
  verrouillage sans rien ajouter.

## Conséquences

- Le CLV est une jointure entre deux bases, faite en Python : `paper._cloture_observee` lit la
  collecte et **gèle** la valeur trouvée dans le carnet, pour que le CLV reste vérifiable même si
  la collecte est reconstruite.
- Le carnet doit être sauvegardé indépendamment. La décision [0004](0004-etat-et-derive.md) en
  tire la conséquence sur l'arborescence.
