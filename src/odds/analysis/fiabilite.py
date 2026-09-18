"""Fiabilité MESURÉE des probabilités — 1X2 et marchés de buts.

Nous disposons de 150 626 matchs historiques avec le résultat réel. La
question « à quel point ce pronostic est-il sûr ? » n'a donc pas à être
devinée : on mesure, sur ces matchs, à quelle fréquence l'issue annoncée à
p % s'est réellement produite.

Usage strictement descriptif et pédagogique. Rien ici ne recommande de
miser quoi que ce soit.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from odds import chemins
from odds.analysis import base
from odds.models.football import buts

BORNES_CONFIANCE = [0.0, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65,
                    0.70, 0.75, 0.80, 0.85, 0.90, 1.01]

NIVEAUX = [
    (0.85, "Très élevée"),
    (0.70, "Élevée"),
    (0.60, "Modérée"),
    (0.50, "Faible"),
    (0.00, "Très faible"),
]


@lru_cache(maxsize=4)
def fiabilite_historique(methode: str = "shin") -> pd.DataFrame:
    """Fréquence réelle de l'issue la plus probable, par tranche.

    Calculée sur l'ensemble de l'historique à clôture Pinnacle. C'est la
    table qui transforme une probabilité affichée en taux de réussite
    observé, avec sa taille d'échantillon et son intervalle de confiance.
    """
    d = base.avec_cloture(base.charger())
    y = base.cible(d)
    p = base.probabilites_marche(d, "psc", methode)
    lig = np.arange(len(p))
    j = p.argmax(axis=1)
    p_max, touche = p[lig, j], y[lig, j]

    t = (pd.DataFrame({"p": p_max, "ok": touche,
                       "bin": pd.cut(p_max, BORNES_CONFIANCE)})
           .groupby("bin", observed=True)
           .agg(n=("p", "size"), p_moyenne=("p", "mean"), reussite=("ok", "mean"))
           .reset_index())
    t["ic95"] = 1.96 * np.sqrt(t.reussite * (1 - t.reussite) / t.n)
    # .apply sur une colonne catégorielle renvoie du catégoriel : sans le
    # cast, toute comparaison numérique lève.
    t["borne_inf"] = t.bin.apply(lambda b: b.left).astype(float)
    t["borne_sup"] = t.bin.apply(lambda b: b.right).astype(float)
    t["bin"] = t.bin.astype(str)
    return t


# --------------------------------------------------------------------------
# Fiabilité mesurée des marchés de buts
# --------------------------------------------------------------------------
# Même principe que ``fiabilite_historique``, mais par marché de buts. La
# table est précalculée par ``research/fiabilite_buts.py`` : la dériver à la
# volée demanderait d'ajuster 150 626 matrices de score, soit plusieurs
# minutes à chaque ouverture de page.
#
# Sans elle, un pari sur un marché de buts ne transmettait aucun ``n`` au
# moteur de mise, et « un signal absent vaut 1 » (prereg 0001 §4) le faisait
# sortir PLUS confiant qu'un 1X2 sur le même match. Le moteur aurait misé
# davantage là où l'on sait moins.


# Métadonnées écrites dans le parquet par research/fiabilite_buts.py, et
# relues ici. La table dépend de deux choses qui peuvent changer sans elle :
# le rho par défaut, qui fixe chaque matrice dérivée du 1X2 seul, et le
# catalogue des marchés, dont les prédicats décident ce qui compte pour
# « réussi ». Une table calculée avec un autre rho reste lisible et
# plausible — c'est ce qui la rend dangereuse. On refuse donc de la servir.
CLE_RHO, CLE_CATALOGUE = b"odds.rho", b"odds.catalogue"


def metadonnees_fiabilite() -> dict[bytes, bytes]:
    """Ce que la table doit porter pour être acceptée par la version courante."""
    return {CLE_RHO: repr(buts.RHO_DEFAUT).encode(),
            CLE_CATALOGUE: buts.signature_catalogue().encode()}


def _vide(motif: str) -> pd.DataFrame:
    t = pd.DataFrame()
    t.attrs["motif"] = motif
    return t


def fiabilite_buts() -> pd.DataFrame:
    """Fréquence réelle par marché et par tranche.

    Vide si non calculée, ou calculée pour un autre rho ou un autre
    catalogue : ``.attrs["motif"]`` dit lequel, pour l'afficher.

    Le cache est indexé par la date du fichier : régénérer la table suffit,
    sans redémarrer l'application — et un refus n'est jamais mémorisé au
    point de survivre au fichier qui l'a causé.
    """
    chemin = chemins.FIABILITE_BUTS
    if not chemin.exists():
        return _vide("table non calculée")
    return _lire_fiabilite_buts(str(chemin), chemin.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _lire_fiabilite_buts(chemin: str, _mtime: int) -> pd.DataFrame:
    fichier = pq.ParquetFile(chemin)
    meta = fichier.schema_arrow.metadata or {}
    attendu = metadonnees_fiabilite()
    for cle, valeur in attendu.items():
        if meta.get(cle) != valeur:
            nom = cle.decode().split(".")[-1]
            trouve = (meta.get(cle) or b"absent").decode()
            return _vide(f"table calculée avec {nom} = {trouve}, la version "
                         f"courante attend {valeur.decode()}")
    return fichier.read().to_pandas()


def tranche_fiabilite_buts(code: str, p: float,
                           contraint: bool = False) -> pd.Series | None:
    """Tranche couvrant ``p`` pour ce marché, ou ``None``.

    Trois retours distincts, et la distinction compte pour le moteur de
    mise :

    - une ligne          -> on a mesuré, voici le n et la réussite ;
    - ``None`` + table vide -> on n'a rien mesuré (table non générée) ;
    - ``None`` + table pleine -> on a mesuré et cette tranche est trop
      mince pour dire quoi que ce soit.

    Repli assumé : faute de tranche dans la variante contrainte, on lit
    celle dérivée du 1X2 seul. Elle porte sur un échantillon plus large et
    une calibration moins bonne — se tromper de ce côté-là est le bon sens
    de l'erreur.
    """
    t = fiabilite_buts()
    if len(t) == 0:
        return None
    sous = t[(t.code == code) & (t.contraint == bool(contraint))]
    if len(sous) == 0:
        sous = t[t.code == code]
    if len(sous) == 0:
        return None
    ligne = sous[(sous.borne_inf < p) & (p <= sous.borne_sup)]
    return ligne.iloc[0] if len(ligne) else None


def _niveau(p: float) -> str:
    for seuil, nom in NIVEAUX:
        if p >= seuil:
            return nom
    return NIVEAUX[-1][1]


def tranche_fiabilite(p: float, methode: str = "shin") -> pd.Series:
    """Ligne de ``fiabilite_historique`` couvrant la probabilité ``p``.

    Extraite d'``annoter_confiance`` pour servir sur une issue quelconque :
    un pari ne porte pas nécessairement sur l'issue la plus probable, et le
    taux de réussite observé dépend de la tranche, pas du match.
    """
    table = fiabilite_historique(methode)
    ligne = table[(table.borne_inf < p) & (p <= table.borne_sup)]
    if len(ligne) == 0:
        ligne = table.iloc[[-1]] if p > table.borne_sup.max() else table.iloc[[0]]
    return ligne.iloc[0]


def annoter_confiance(res: pd.DataFrame, methode: str = "shin") -> pd.DataFrame:
    """Ajoute le score de confiance du pronostic le plus probable.

    Colonnes ajoutées :
      confiance        niveau qualitatif
      reussite_hist    fréquence réelle observée à ce niveau de probabilité
      n_hist           taille de l'échantillon derrière cette fréquence
      ic95_hist        demi-largeur de l'intervalle de confiance à 95 %
      echoue_hist      fréquence d'échec — la moitié qu'on oublie de regarder
    """
    if len(res) == 0:
        return res
    out = []
    for p in res.p_probable:
        r = tranche_fiabilite(float(p), methode)
        out.append({
            "confiance": _niveau(float(p)),
            "reussite_hist": float(r.reussite),
            "n_hist": int(r.n),
            "ic95_hist": float(r.ic95),
            "echoue_hist": 1.0 - float(r.reussite),
        })
    return pd.concat([res.reset_index(drop=True),
                      pd.DataFrame(out)], axis=1)
