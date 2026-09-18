"""Tests du client The Odds API.

Le danger principal est la correspondance des issues : l'API nomme les
sélections par le NOM DE L'ÉQUIPE, pas par home/away. Une correspondance
approximative inverserait silencieusement domicile et extérieur — l'erreur la
plus coûteuse possible, et la plus difficile à repérer a posteriori.
"""

import sqlite3

import pandas as pd
import pytest

from odds.data import oddsapi


def _reponse(dom="Arsenal", ext="Chelsea", nul="Draw"):
    return [{
        "id": "evt1",
        "sport_key": "soccer_epl",
        "commence_time": "2026-09-20T14:00:00Z",
        "home_team": dom,
        "away_team": ext,
        "bookmakers": [
            {"key": "pinnacle", "last_update": "2026-09-20T12:00:00Z",
             "markets": [{"key": "h2h", "outcomes": [
                 {"name": ext, "price": 3.10},      # ordre volontairement mélangé
                 {"name": nul, "price": 3.40},
                 {"name": dom, "price": 2.30}]}]},
            {"key": "betfair_ex_eu", "last_update": "2026-09-20T12:01:00Z",
             "markets": [{"key": "h2h", "outcomes": [
                 {"name": dom, "price": 2.34},
                 {"name": nul, "price": 3.45},
                 {"name": ext, "price": 3.15}]}]},
        ],
    }]


def test_correspondance_domicile_exterieur():
    """L'ordre des issues dans la réponse ne doit rien changer."""
    d = oddsapi._normaliser(_reponse(), "soccer_epl")
    pin = d[d.bookmaker == "pinnacle"].set_index("selection").odds
    assert pin["home"] == pytest.approx(2.30), "Arsenal (domicile) mal associé"
    assert pin["draw"] == pytest.approx(3.40)
    assert pin["away"] == pytest.approx(3.10), "Chelsea (extérieur) mal associé"


def test_issue_non_reconnue_leve():
    """Un nom d'équipe qui ne correspond à rien doit LEVER.

    Retomber sur une heuristique (position, ordre) produirait des inversions
    domicile/extérieur invisibles dans toutes les analyses en aval.
    """
    r = _reponse()
    r[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["name"] = "Chelsea FC"
    with pytest.raises(ValueError, match="issue non reconnue"):
        oddsapi._normaliser(r, "soccer_epl")


def test_equipes_aux_noms_proches():
    """Deux équipes de noms proches ne doivent pas être confondues."""
    d = oddsapi._normaliser(_reponse(dom="Manchester United",
                                     ext="Manchester City"), "soccer_epl")
    pin = d[d.bookmaker == "pinnacle"].set_index("selection").odds
    assert pin["home"] == pytest.approx(2.30)
    assert pin["away"] == pytest.approx(3.10)


def test_colonnes_et_formats():
    d = oddsapi._normaliser(_reponse(), "soccer_epl")
    assert set(d.columns) >= {"event_id", "sport", "kickoff", "home_team", "away_team",
                              "bookmaker", "market", "selection", "odds", "book_updated_at"}
    assert set(d.market) == {"1X2"}, "h2h doit être renommé 1X2 comme le reste du projet"
    assert d.kickoff.iloc[0] == "2026-09-20 14:00"
    assert d.book_updated_at.iloc[0] == "2026-09-20 12:00:00"
    assert len(d) == 6           # 2 bookmakers x 3 issues


def test_reponse_vide():
    assert len(oddsapi._normaliser([], "soccer_epl")) == 0


def test_match_sans_bookmaker():
    r = _reponse()
    r[0]["bookmakers"] = []
    assert len(oddsapi._normaliser(r, "soccer_epl")) == 0


def test_cle_absente_leve(monkeypatch):
    from odds import config
    monkeypatch.setattr(config, "get", lambda c, d=None: None)
    with pytest.raises(RuntimeError, match="ODDS_API_KEY"):
        oddsapi._cle()


# --- budget ---------------------------------------------------------------

def test_budget_bloque_la_passe(tmp_path, monkeypatch):
    """Au-delà du budget du jour, aucune requête payante ne doit partir."""
    import odds.data.collect as mod
    from odds import config

    bdd = tmp_path / "b.db"
    con = mod._connexion(bdd)
    jour = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")
    con.execute("INSERT INTO collecte_run (run_id, demarre_a, credits_utilises) "
                "VALUES (?,?,?)", ("r0", f"{jour} 00:00:00", 14))
    con.commit()

    monkeypatch.setattr(config, "get", lambda c, d=None: {
        "ODDS_API_SPORTS": "soccer_epl", "ODDS_API_REGIONS": "eu",
        "ODDS_API_MARKETS": "h2h", "ODDS_API_BUDGET_JOUR": "14"}.get(c, d))

    def interdit(*a, **k):
        raise AssertionError("une requête payante est partie malgré le budget épuisé")

    monkeypatch.setattr(oddsapi, "cotes", interdit)
    monkeypatch.setattr(oddsapi, "championnats_avec_matchs", interdit)

    v, e, credits, restants, errs = mod._collecter_oddsapi(
        con, "2026-09-20 10:00:00", "r1", {}, verbose=False)
    assert (v, e, credits) == (0, 0, 0)
    con.close()


def test_credits_utilises_aujourdhui(tmp_path):
    import odds.data.collect as mod
    bdd = tmp_path / "b.db"
    con = mod._connexion(bdd)
    jour = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")
    con.execute("INSERT INTO collecte_run (run_id, demarre_a, credits_utilises) "
                "VALUES (?,?,?)", ("a", f"{jour} 01:00:00", 5))
    con.execute("INSERT INTO collecte_run (run_id, demarre_a, credits_utilises) "
                "VALUES (?,?,?)", ("b", f"{jour} 02:00:00", 3))
    con.execute("INSERT INTO collecte_run (run_id, demarre_a, credits_utilises) "
                "VALUES (?,?,?)", ("c", "2020-01-01 02:00:00", 99))
    con.commit()
    assert mod.credits_utilises_aujourdhui(con) == 8, "les jours passés ne comptent pas"
    con.close()


def test_migration_idempotente(tmp_path):
    """Une base créée avant l'ajout des colonnes doit être migrée sans perte."""
    import odds.data.collect as mod
    bdd = tmp_path / "vieille.db"
    con = sqlite3.connect(bdd)
    con.execute("""CREATE TABLE odds_snapshot (
        fixture_key TEXT, country TEXT, league TEXT, kickoff TEXT,
        home_team TEXT, away_team TEXT, bookmaker TEXT, market TEXT,
        selection TEXT, odds REAL, observed_at TEXT, run_id TEXT)""")
    con.execute("""CREATE TABLE collecte_run (
        run_id TEXT PRIMARY KEY, demarre_a TEXT, flux TEXT, matchs INTEGER,
        lignes_vues INTEGER, lignes_ecrites INTEGER, erreur TEXT)""")
    con.execute("INSERT INTO odds_snapshot VALUES "
                "('k',NULL,'E0','2026-01-01 12:00','A','B','x','1X2','home',2.0,'t','r')")
    con.commit(); con.close()

    c2 = mod._connexion(bdd)
    cols = {r[1] for r in c2.execute("PRAGMA table_info(odds_snapshot)")}
    assert {"source", "book_updated_at"} <= cols
    assert c2.execute("SELECT COUNT(*) FROM odds_snapshot").fetchone()[0] == 1
    c2.close()
    mod._connexion(bdd).close()   # deuxième passage : ne doit pas lever
