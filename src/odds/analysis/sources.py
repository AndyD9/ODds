"""Lecture des sources — collecte propre et historique — au format long.

Un seul format de sortie, quelle que soit la source : une ligne par
(match, bookmaker, sélection), pour que le consensus n'ait jamais à savoir
d'où viennent les cotes.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from odds import chemins, temps
from odds.analysis import base
from odds.market.vocabulaire import MARCHE_1X2, MARCHE_TOTAUX, selection_totaux

# Livres agrégés : utiles pour le price shopping, mais ce ne sont pas des
# bookmakers réels et ils ne doivent pas entrer dans le consensus.
AGREGATS = ("_max_marche", "_moyenne_marche")

# Cotes relevées à un AUTRE instant. Ce n'est pas un bookmaker concurrent,
# c'est le même book plus tôt. L'inclure gonflerait artificiellement la
# dispersion et ferait apparaître comme "meilleur prix" une cote qui n'était
# plus disponible au moment considéré.
AUTRE_INSTANT = ("pinnacle_precoce",)

HORS_CONSENSUS = AGREGATS + AUTRE_INSTANT

BENCHMARKS = ("betfair_exchange", "pinnacle_closing", "pinnacle")


# Ordre de préférence entre sources collectées. The Odds API d'abord : elle
# est continue, porte ~24 bookmakers dont Pinnacle et Betfair Exchange, là où
# football-data ne publie que deux fois par semaine et a perdu Pinnacle.
# On ne MÉLANGE pas les deux : les noms d'équipe diffèrent d'une source à
# l'autre et un appariement approximatif créerait des doublons silencieux.
PREFERENCE_SOURCES = ("odds-api", "football-data")


def _bdd():
    """Chemin de la base de collecte, lu à l'appel (patchable, rapatriable)."""
    return chemins.rapatrier(chemins.BDD_COLLECTE)


def _long_depuis_collecte(jour: pd.Timestamp) -> pd.DataFrame:
    bdd = _bdd()
    if not bdd.exists():
        return pd.DataFrame()
    requete = """
        SELECT s.fixture_key, s.source, s.country, s.league, s.kickoff,
               s.home_team, s.away_team, s.bookmaker, s.selection,
               s.odds, s.observed_at
        FROM odds_snapshot s
        JOIN (
            SELECT fixture_key, bookmaker, selection, MAX(observed_at) AS vu
            FROM odds_snapshot WHERE market = ?
            GROUP BY fixture_key, bookmaker, selection
        ) d
          ON s.fixture_key = d.fixture_key AND s.bookmaker = d.bookmaker
         AND s.selection = d.selection AND s.observed_at = d.vu
        WHERE s.market = ? AND substr(s.kickoff, 1, 10) = ?
    """
    con = sqlite3.connect(bdd)
    try:
        d = pd.read_sql(requete, con, params=(MARCHE_1X2, MARCHE_1X2, temps.jour(jour)))
    finally:
        con.close()
    if len(d) == 0 or "source" not in d.columns:
        return d
    for src in PREFERENCE_SOURCES:
        sous = d[d.source == src]
        if len(sous):
            return sous.reset_index(drop=True)
    return d


def _long_depuis_historique(jour: pd.Timestamp) -> pd.DataFrame:
    df = base.charger()
    d = df[df.date.dt.normalize() == jour.normalize()]
    if len(d) == 0:
        return pd.DataFrame()
    blocs = []
    for prefixe, book in (("psc", "pinnacle_closing"), ("ps", "pinnacle_precoce"),
                          ("avgc", "_moyenne_marche"), ("maxc", "_max_marche")):
        cols = [f"{prefixe}_{x}" for x in ("h", "d", "a")]
        if not set(cols) <= set(d.columns):
            continue
        ok = d[d[cols].notna().all(axis=1)]
        if len(ok) == 0:
            continue
        for col, sel in zip(cols, ("home", "draw", "away")):
            blocs.append(pd.DataFrame({
                "fixture_key": ok.index.astype(str),
                "country": ok.country, "league": ok.league,
                "kickoff": ok.date.dt.strftime(temps.FORMAT_MINUTE),
                "home_team": ok.home_team, "away_team": ok.away_team,
                "bookmaker": book, "selection": sel,
                "odds": ok[col].astype(float),
                "observed_at": pd.NA,
                "resultat": ok.result,
                "score": ok.home_goals.astype(str) + "–" + ok.away_goals.astype(str),
            }))
    return pd.concat(blocs, ignore_index=True) if blocs else pd.DataFrame()



def _totaux_depuis_collecte(jour: pd.Timestamp) -> pd.DataFrame:
    bdd = _bdd()
    if not bdd.exists():
        return pd.DataFrame()
    requete = """
        SELECT s.fixture_key, s.bookmaker, s.selection, s.odds
        FROM odds_snapshot s
        JOIN (
            SELECT fixture_key, bookmaker, selection, MAX(observed_at) AS vu
            FROM odds_snapshot WHERE market = ?
            GROUP BY fixture_key, bookmaker, selection
        ) d
          ON s.fixture_key = d.fixture_key AND s.bookmaker = d.bookmaker
         AND s.selection = d.selection AND s.observed_at = d.vu
        WHERE s.market = ? AND substr(s.kickoff, 1, 10) = ?
    """
    con = sqlite3.connect(bdd)
    try:
        return pd.read_sql(requete, con,
                           params=(MARCHE_TOTAUX, MARCHE_TOTAUX, temps.jour(jour)))
    finally:
        con.close()


def _totaux_depuis_historique(jour: pd.Timestamp) -> pd.DataFrame:
    df = base.charger()
    d = df[df.date.dt.normalize() == jour.normalize()]
    blocs = []
    for prefixe, book in (("psc", "pinnacle_closing"), ("avgc", "_moyenne_marche"),
                          ("maxc", "_max_marche")):
        cols = [f"{prefixe}_o25", f"{prefixe}_u25"]
        if not set(cols) <= set(d.columns):
            continue
        ok = d[d[cols].notna().all(axis=1)]
        if len(ok) == 0:
            continue
        for col, sel in zip(cols, (selection_totaux(2.5, "over"),
                                   selection_totaux(2.5, "under"))):
            blocs.append(pd.DataFrame({
                "fixture_key": ok.index.astype(str), "bookmaker": book,
                "selection": sel, "odds": ok[col].astype(float)}))
    return pd.concat(blocs, ignore_index=True) if blocs else pd.DataFrame()



def dates_disponibles() -> dict:
    """Dates couvertes par chaque source, pour guider le sélecteur."""
    bdd = _bdd()
    out = {"collecte": [], "historique": (None, None)}
    if bdd.exists():
        con = sqlite3.connect(bdd)
        try:
            out["collecte"] = [r[0] for r in con.execute(
                "SELECT DISTINCT substr(kickoff,1,10) FROM odds_snapshot ORDER BY 1")]
        finally:
            con.close()
    df = base.charger()
    out["historique"] = (df.date.min().date(), df.date.max().date())
    return out

