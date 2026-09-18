"""Emplacements des données — un seul endroit pour les dire.

Deux familles de fichiers, et la distinction commande leur emplacement :

- ``data/`` — l'ÉTAT : ce qu'on ne peut pas reconstituer. Le carnet de paris
  est une suite de décisions datées ; la base de collecte est un relevé de
  prix qui n'existent plus une fois le match commencé. Effacer l'un ou
  l'autre, c'est perdre des mois.
- ``research/data/`` — le DÉRIVÉ : ce qu'un script régénère. L'historique
  football-data se retélécharge, le parquet se réingère, les tables de
  fiabilité se recalculent.

Avant cette séparation, le carnet vivait à côté de 42 Mo de cache brut et
d'artefacts de recherche, dans un dossier que ``.gitignore`` traite comme
jetable. La docstring de ``paper.py`` interdisait de mélanger les deux ;
l'arborescence faisait l'inverse.
"""

from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]

ETAT = RACINE / "data"
RECHERCHE = RACINE / "research" / "data"

# --- état ------------------------------------------------------------------
BASE_PARIS = ETAT / "paper.db"
BDD_COLLECTE = ETAT / "odds_history.db"

# --- dérivé ----------------------------------------------------------------
PARQUET = RECHERCHE / "matches.parquet"
FIABILITE_BUTS = RECHERCHE / "fiabilite_buts.parquet"
CACHE_BRUT = RECHERCHE / "raw"


def rapatrier(chemin: Path) -> Path:
    """Déplace un fichier d'état encore rangé à l'ancien emplacement.

    Les deux bases vivaient dans ``research/data/``. Une installation qui
    n'a pas déplacé ses fichiers à la main les retrouve ici, une fois, au
    premier accès — plutôt que de repartir d'un carnet vide sans le dire.
    """
    if chemin.parent != ETAT or chemin.exists():
        return chemin
    ancien = RECHERCHE / chemin.name
    if ancien.exists():
        ETAT.mkdir(parents=True, exist_ok=True)
        ancien.rename(chemin)
    return chemin
