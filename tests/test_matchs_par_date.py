"""Tests de l'analyse par date.

Le point délicat est la composition du consensus : y inclure un agrégat de
marché ou la même cote relevée à un autre instant fausse silencieusement
toutes les sorties de la page.
"""

import sqlite3

import numpy as np
import pandas as pd
import pytest

import odds.analysis as ana
from odds.analysis import AGREGATS, AUTRE_INSTANT, HORS_CONSENSUS


@pytest.fixture
def bdd(tmp_path, monkeypatch):
    """Base de collecte minimale : 1 match, 3 books + 2 agrégats."""
    p = tmp_path / "c.db"
    # On passe par le schéma de PRODUCTION plutôt que d'en figer une copie :
    # une copie diverge silencieusement dès qu'une colonne est ajoutée.
    from odds.data.collect import _connexion
    con = _connexion(p)
    lignes = []
    livres = {
        "bet365": (2.00, 3.40, 4.00),
        "bwin": (2.05, 3.30, 3.90),
        "betfair_exchange": (2.10, 3.50, 4.10),
        "_max_marche": (2.60, 3.60, 4.30),      # agrégat : hors consensus
        "_moyenne_marche": (2.02, 3.38, 3.95),  # agrégat : hors consensus
    }
    for book, (h, d, a) in livres.items():
        for sel, o in (("home", h), ("draw", d), ("away", a)):
            lignes.append(("fk1", "odds-api", "Spain", "SP1", "2026-10-01 20:00",
                           "Betis", "Getafe", book, "1X2", sel, o, "2026-09-30 10:00", "r1"))
            # une observation ANTÉRIEURE, qui ne doit jamais être retenue
            lignes.append(("fk1", "odds-api", "Spain", "SP1", "2026-10-01 20:00",
                           "Betis", "Getafe", book, "1X2", sel, o * 1.5, "2026-09-29 10:00", "r0"))
    con.executemany(
        "INSERT INTO odds_snapshot (fixture_key, source, country, league, kickoff, "
        "home_team, away_team, bookmaker, market, selection, odds, observed_at, run_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", lignes)
    con.commit()
    con.close()
    monkeypatch.setattr(ana, "BDD_COLLECTE", p)
    return p


def test_preference_odds_api_sur_football_data(bdd):
    """Quand les deux sources couvrent la même date, on ne mélange pas :
    les noms d'équipe diffèrent et un appariement approximatif créerait des
    doublons. The Odds API l'emporte (continue, ~24 books, Pinnacle)."""
    import sqlite3 as sq
    con = sq.connect(bdd)
    con.execute(
        "INSERT INTO odds_snapshot (fixture_key, source, country, league, kickoff, "
        "home_team, away_team, bookmaker, market, selection, odds, observed_at, run_id) "
        "VALUES ('fd1','football-data','Spain','SP1','2026-10-01 20:00','Betis',"
        "'Getafe','bet365','1X2','home',9.99,'2026-09-30 11:00','r2')")
    con.commit(); con.close()

    r = ana.matchs_a_la_date("2026-10-01")
    assert set(r["detail"].fixture_key) == {"fk1"}, "les deux sources ont été mélangées"
    assert 9.99 not in set(r["detail"].cote_1)


def test_constantes_coherentes():
    assert set(HORS_CONSENSUS) == set(AGREGATS) | set(AUTRE_INSTANT)
    assert "pinnacle_precoce" in AUTRE_INSTANT


def test_source_collecte(bdd):
    r = ana.matchs_a_la_date("2026-10-01")
    assert r["source"] == "collecte"
    assert len(r["resume"]) == 1


def test_seule_la_derniere_observation_compte(bdd):
    """Une cote plus ancienne du même book ne doit pas apparaître."""
    d = ana.matchs_a_la_date("2026-10-01")["detail"]
    assert d[d.bookmaker == "bet365"].cote_1.iloc[0] == pytest.approx(2.00)
    assert len(d[d.bookmaker == "bet365"]) == 1


def test_consensus_exclut_les_agregats(bdd):
    """Le consensus ne porte que sur les bookmakers RÉELS.

    Si _max_marche entrait dans la médiane, la probabilité du favori serait
    tirée vers le bas et l'écart de price shopping deviendrait fictif.
    """
    r = ana.matchs_a_la_date("2026-10-01")
    res = r["resume"].iloc[0]
    assert res.n_books == 3, "3 bookmakers réels, pas 5"

    d = r["detail"]
    reels = d[~d.bookmaker.isin(HORS_CONSENSUS)]
    attendu = float(np.median(reels.p_1))
    somme = float(np.median(reels.p_1) + np.median(reels.p_N) + np.median(reels.p_2))
    assert res.p_1 == pytest.approx(attendu / somme, abs=1e-9)


def test_meilleur_prix_inclut_les_agregats(bdd):
    """Le meilleur prix DISPONIBLE inclut le max de marché — c'est bien le
    meilleur prix qu'on pourrait prendre."""
    res = ana.matchs_a_la_date("2026-10-01")["resume"].iloc[0]
    assert res.best_1 == pytest.approx(2.60)


def test_probabilites_somment_a_un(bdd):
    r = ana.matchs_a_la_date("2026-10-01")
    res = r["resume"]
    assert (res.p_1 + res.p_N + res.p_2).to_numpy() == pytest.approx(np.ones(len(res)), abs=1e-9)
    d = r["detail"]
    assert (d.p_1 + d.p_N + d.p_2).to_numpy() == pytest.approx(np.ones(len(d)), abs=1e-9)


def test_ecart_price_shopping_coherent(bdd):
    res = ana.matchs_a_la_date("2026-10-01")["resume"].iloc[0]
    for s in ("1", "N", "2"):
        attendu = 100.0 * (res[f"p_{s}"] * res[f"best_{s}"] - 1.0)
        assert res[f"ecart_{s}"] == pytest.approx(attendu, abs=1e-9)
    assert res.meilleur_ecart == pytest.approx(
        max(res.ecart_1, res.ecart_N, res.ecart_2), abs=1e-9)


def test_date_sans_match(bdd, monkeypatch):
    monkeypatch.setattr(ana, "charger", lambda *a, **k: pd.DataFrame(
        {"date": pd.to_datetime([]), "result": []}))
    r = ana.matchs_a_la_date("2030-01-01")
    assert r["source"] is None and len(r["resume"]) == 0


def test_dispersion_nulle_avec_un_seul_book(bdd):
    """Un seul bookmaker => dispersion 0, jamais NaN (sinon l'affichage casse)."""
    con = sqlite3.connect(bdd)
    con.execute("DELETE FROM odds_snapshot WHERE bookmaker IN ('bwin','betfair_exchange')")
    con.commit(); con.close()
    res = ana.matchs_a_la_date("2026-10-01")["resume"].iloc[0]
    assert res.n_books == 1
    assert res.dispersion == pytest.approx(0.0)
