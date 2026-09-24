"""Tests du collecteur de cotes.

Le collecteur constitue l'historique dont dépendra toute mesure en avant.
Une erreur de parsing silencieuse y coûterait des mois de données perdues —
c'est déjà arrivé une fois (BOM UTF-8 lu en latin-1).
"""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from odds.data.collect import BOOKMAKERS, _cle, _connexion, _normaliser, collecter, resume


def _flux_main() -> pd.DataFrame:
    return pd.DataFrame({
        "Div": ["E0", "E0"],
        "Date": ["20/09/2026", "20/09/2026"],
        "Time": ["15:00", "17:30"],
        "HomeTeam": ["Arsenal ", "Chelsea"],
        "AwayTeam": ["Liverpool", " Everton"],
        "BFEH": [2.10, 1.60], "BFED": [3.50, 4.20], "BFEA": [3.60, 5.50],
        "B365H": [2.05, 1.57], "B365D": [3.40, 4.00], "B365A": [3.50, 5.25],
        "AvgH": [2.08, 1.58], "AvgD": [3.45, 4.10], "AvgA": [3.55, 5.40],
        "Max>2.5": [1.95, 1.80], "Max<2.5": [1.98, 2.10],
    })


def _flux_extra() -> pd.DataFrame:
    return pd.DataFrame({
        "Country": ["Norway"], "League": ["Eliteserien"],
        "Date": ["21/09/2026"], "Time": ["18:00"],
        "Home": ["Molde"], "Away": ["Bodo/Glimt"],
        "PSH": [2.30], "PSD": [3.40], "PSA": [3.10],
        "BFEH": [2.34], "BFED": [3.45], "BFEA": [3.15],
    })


def test_normalisation_format_long():
    d = _normaliser(_flux_main(), "main")
    assert len(d) > 0
    assert set(d.columns) >= {"fixture_key", "home_team", "away_team", "bookmaker",
                              "market", "selection", "odds", "kickoff"}
    # les espaces parasites des noms d'équipe sont retirés
    assert set(d.home_team) == {"Arsenal", "Chelsea"}
    assert set(d.away_team) == {"Liverpool", "Everton"}
    # 1X2 et Over/Under sont tous deux captés
    # Même vocabulaire que The Odds API : la ligne fait partie de la sélection.
    assert set(d.market) == {"1X2", "totals"}
    assert set(d[d.market == "1X2"].selection) == {"home", "draw", "away"}
    assert set(d[d.market == "totals"].selection) == {"over_2.5", "under_2.5"}
    # Betfair Exchange, le benchmark retenu en avant, est bien présent
    assert "betfair_exchange" in set(d.bookmaker)


def test_normalisation_flux_extra():
    d = _normaliser(_flux_extra(), "extra")
    assert len(d) > 0
    assert set(d.country) == {"Norway"}
    assert "pinnacle" in set(d.bookmaker), "PSH/PSD/PSA doit être capté s'il revient"
    assert d[d.bookmaker == "pinnacle"].odds.tolist() == [2.30, 3.40, 3.10]


def test_kickoff_parse_en_jour_premier():
    """20/09/2026 est le 20 septembre, pas une date invalide."""
    d = _normaliser(_flux_main(), "main")
    assert d.kickoff.str.startswith("2026-09-20").all()
    assert set(d.kickoff) == {"2026-09-20 15:00", "2026-09-20 17:30"}


def test_cotes_invalides_ecartees():
    f = _flux_main()
    f.loc[0, "BFEH"] = 1.0      # cote impossible
    f.loc[1, "B365D"] = None    # manquante
    d = _normaliser(f, "main")
    assert (d.odds > 1.0).all()
    assert d.odds.notna().all()


def test_cle_de_match_stable_et_discriminante():
    a = _cle("England", "E0", "2026-09-20 15:00", "Arsenal", "Liverpool")
    b = _cle("England", "E0", "2026-09-20 15:00", "Arsenal", "Liverpool")
    c = _cle("England", "E0", "2026-09-20 15:00", "Liverpool", "Arsenal")
    assert a == b, "la clé doit être stable entre deux passes"
    assert a != c, "domicile et extérieur ne sont pas interchangeables"


def test_deduplication(tmp_path, monkeypatch):
    """Une cote inchangée ne doit PAS être réécrite : l'historique est une
    série de mouvements, pas un journal de sondages."""
    bdd = tmp_path / "t.db"
    import odds.data.collect as mod

    appels = {"n": 0}

    def faux_flux(url):
        appels["n"] += 1
        f = _flux_main()
        if appels["n"] > 2:          # 3e passe : une cote bouge
            f.loc[0, "BFEH"] = 2.25
        return f

    monkeypatch.setattr(mod, "_lire_flux", faux_flux)
    monkeypatch.setattr(mod, "FLUX", {"main": "x"})

    r1 = mod.collecter(bdd, verbose=False)
    assert r1["ecrites"] == r1["vues"] > 0, "1re passe : tout est nouveau"

    r2 = mod.collecter(bdd, verbose=False)
    assert r2["vues"] == r1["vues"]
    assert r2["ecrites"] == 0, "2e passe identique : rien ne doit être écrit"

    r3 = mod.collecter(bdd, verbose=False)
    assert r3["ecrites"] == 1, "3e passe : seule la cote qui a bougé est écrite"

    con = sqlite3.connect(bdd)
    n = con.execute("SELECT COUNT(*) FROM odds_snapshot").fetchone()[0]
    assert n == r1["ecrites"] + 1
    con.close()


def test_observed_at_est_notre_horodatage(tmp_path, monkeypatch):
    """observed_at doit dater la COLLECTE, pas le match. C'est la seule date
    qui permette un backtest honnête (PLAN §4.3)."""
    bdd = tmp_path / "t.db"
    import odds.data.collect as mod
    monkeypatch.setattr(mod, "_lire_flux", lambda url: _flux_main())
    monkeypatch.setattr(mod, "FLUX", {"main": "x"})
    mod.collecter(bdd, verbose=False)

    con = sqlite3.connect(bdd)
    obs, ko = con.execute(
        "SELECT observed_at, kickoff FROM odds_snapshot LIMIT 1").fetchone()
    con.close()
    assert pd.Timestamp(obs) < pd.Timestamp(ko), "la collecte précède le coup d'envoi"
    assert pd.Timestamp(obs).year >= 2026


def test_erreur_reseau_nempeche_pas_le_run(tmp_path, monkeypatch):
    """Un flux en panne doit être enregistré comme erreur, sans faire échouer
    la passe ni perdre l'autre flux."""
    bdd = tmp_path / "t.db"
    import odds.data.collect as mod

    def flux(url):
        if url == "casse":
            raise ConnectionError("réseau indisponible")
        return _flux_main()

    monkeypatch.setattr(mod, "_lire_flux", flux)
    monkeypatch.setattr(mod, "FLUX", {"main": "bon", "extra": "casse"})
    r = mod.collecter(bdd, verbose=False)
    assert r["ecrites"] > 0, "le flux valide doit quand même être collecté"
    assert len(r["erreurs"]) == 1 and "réseau" in r["erreurs"][0]

    con = sqlite3.connect(bdd)
    err = con.execute("SELECT erreur FROM collecte_run").fetchone()[0]
    con.close()
    assert err and "réseau" in err, "l'erreur doit être tracée en base"


def test_format_inattendu_leve_au_lieu_de_perdre_les_donnees():
    """Un flux dont le format change doit faire ECHOUER la passe bruyamment.

    Un retour silencieux d'un tableau vide laisserait la collecte tourner des
    mois en n'enregistrant rien — le pire mode de défaillance possible pour
    ce module.
    """
    with pytest.raises(ValueError, match="colonnes attendues absentes"):
        _normaliser(pd.DataFrame({"Truc": [1], "Machin": [2]}), "main")
    with pytest.raises(ValueError, match="flux inconnu"):
        _normaliser(_flux_main(), "inattendu")


def test_deux_passes_dans_la_meme_seconde(tmp_path, monkeypatch):
    """Deux collectes rapprochées ne doivent pas violer la clé primaire."""
    bdd = tmp_path / "t.db"
    import odds.data.collect as mod
    monkeypatch.setattr(mod, "_lire_flux", lambda url: _flux_main())
    monkeypatch.setattr(mod, "FLUX", {"main": "x"})
    r1 = mod.collecter(bdd, verbose=False)
    r2 = mod.collecter(bdd, verbose=False)
    assert r1["run_id"] != r2["run_id"]
    con = sqlite3.connect(bdd)
    assert con.execute("SELECT COUNT(*) FROM collecte_run").fetchone()[0] == 2
    con.close()


def test_resume(tmp_path, monkeypatch):
    bdd = tmp_path / "t.db"
    import odds.data.collect as mod
    monkeypatch.setattr(mod, "_lire_flux", lambda url: _flux_main())
    monkeypatch.setattr(mod, "FLUX", {"main": "x"})
    mod.collecter(bdd, verbose=False)
    r = mod.resume(bdd)
    assert r["lignes"] > 0 and r["matchs"] == 2 and r["runs"] == 1
    assert "betfair_exchange" in set(r["bookmakers"].bookmaker)


def test_etat_flux_trace_la_fraicheur(tmp_path, monkeypatch):
    """La fraîcheur du flux amont doit être enregistrée.

    Sans elle, une journée sans match est indiscernable d'une panne du
    collecteur — c'est exactement la confusion qu'elle sert à lever.
    """
    bdd = tmp_path / "t.db"
    import odds.data.collect as mod

    def flux(url):
        mod._DERNIER_LAST_MODIFIED[url] = "Tue, 15 Sep 2026 11:00:05 GMT"
        return _flux_main()

    monkeypatch.setattr(mod, "_lire_flux", flux)
    monkeypatch.setattr(mod, "FLUX", {"main": "x"})
    mod.collecter(bdd, verbose=False)

    e = mod.etat_flux(bdd)
    assert len(e) == 1
    ligne = e.iloc[0]
    assert ligne.flux == "main"
    assert ligne.last_modified == "Tue, 15 Sep 2026 11:00:05 GMT"
    assert ligne.n_matchs == 2
    assert ligne.date_min == "2026-09-20" and ligne.date_max == "2026-09-20"
    assert ligne.age_heures > 0


def test_flux_perime_detecte(tmp_path, monkeypatch):
    """Au-delà de ~4 jours sans publication, le flux est signalé en retard."""
    bdd = tmp_path / "t.db"
    import odds.data.collect as mod

    def flux(url):
        mod._DERNIER_LAST_MODIFIED[url] = "Mon, 01 Jan 2024 00:00:00 GMT"
        return _flux_main()

    monkeypatch.setattr(mod, "_lire_flux", flux)
    monkeypatch.setattr(mod, "FLUX", {"main": "x"})
    mod.collecter(bdd, verbose=False)
    assert bool(mod.etat_flux(bdd).iloc[0].perime) is True


def _annoncer(bdd, prochain, vu_a=None):
    """Simule ce que la passe The Odds API note du calendrier."""
    maintenant = pd.Timestamp.now(tz="UTC")
    con = _connexion(bdd)
    con.execute("INSERT OR REPLACE INTO calendrier_etat VALUES (?,?,?)",
                ("soccer_epl", (maintenant + prochain).isoformat(),
                 (vu_a or maintenant).isoformat()))
    con.commit()
    con.close()


def _flux_ancien(tmp_path, monkeypatch):
    bdd = tmp_path / "t.db"
    import odds.data.collect as mod

    def flux(url):
        mod._DERNIER_LAST_MODIFIED[url] = "Mon, 01 Jan 2024 00:00:00 GMT"
        return _flux_main()

    monkeypatch.setattr(mod, "_lire_flux", flux)
    monkeypatch.setattr(mod, "FLUX", {"main": "x"})
    mod.collecter(bdd, verbose=False)
    return bdd, mod


def test_treve_le_silence_du_flux_n_est_pas_un_retard(tmp_path, monkeypatch):
    """Aucun match annoncé avant 16 jours : football-data n'a rien à publier."""
    bdd, mod = _flux_ancien(tmp_path, monkeypatch)
    _annoncer(bdd, pd.Timedelta(days=16))
    e = mod.etat_flux(bdd).iloc[0]
    assert bool(e.treve) is True
    assert bool(e.perime) is False


def test_match_proche_non_publie_reste_un_retard(tmp_path, monkeypatch):
    """Un match dans 24 h que football-data n'a pas publié : là, c'est un retard."""
    bdd, mod = _flux_ancien(tmp_path, monkeypatch)
    _annoncer(bdd, pd.Timedelta(hours=24))
    e = mod.etat_flux(bdd).iloc[0]
    assert bool(e.treve) is False
    assert bool(e.perime) is True


def test_annonce_trop_ancienne_ne_prouve_pas_la_treve(tmp_path, monkeypatch):
    """Si la passe The Odds API s'est arrêtée, son dernier calendrier ne compte plus."""
    bdd, mod = _flux_ancien(tmp_path, monkeypatch)
    _annoncer(bdd, pd.Timedelta(days=16),
              vu_a=pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3))
    assert bool(mod.etat_flux(bdd).iloc[0].perime) is True


def test_le_plan_gratuit_note_le_prochain_match(tmp_path):
    """Les championnats en erreur ou sans événement ne sont pas notés."""
    from odds.data.collect import _noter_calendrier, prochain_match_annonce
    maintenant = pd.Timestamp.now(tz="UTC")
    plan = pd.DataFrame({
        "sport": ["soccer_epl", "soccer_italy_serie_a", "soccer_spain_la_liga"],
        "prochain": [maintenant + pd.Timedelta(days=10), pd.NaT,
                     maintenant + pd.Timedelta(days=2)],
        "erreur": [None, None, "HTTP 500"],
    })
    con = _connexion(tmp_path / "t.db")
    _noter_calendrier(con, plan, maintenant.isoformat())
    con.commit()
    notes = [r[0] for r in con.execute("SELECT sport FROM calendrier_etat")]
    con.close()
    assert notes == ["soccer_epl"]
    p = prochain_match_annonce(tmp_path / "t.db")
    assert abs((p - (maintenant + pd.Timedelta(days=10))).total_seconds()) < 1


def test_les_anciens_totaux_OU25_sont_convertis_a_l_ouverture(tmp_path):
    """Les bases constituées avant le vocabulaire unique portent `OU25/over`.
    La conversion se fait à la connexion, sans rien perdre."""
    import sqlite3
    p = tmp_path / "c.db"
    con = _connexion(p)
    con.execute("INSERT INTO odds_snapshot (fixture_key, source, kickoff, home_team, "
                "away_team, bookmaker, market, selection, odds, observed_at, run_id) "
                "VALUES ('k', 'football-data', '2026-10-01 20:00', 'A', 'B', "
                "'bet365', 'OU25', 'over', 1.9, '2026-09-30 10:00', 'r1')")
    con.commit(); con.close()
    con = _connexion(p)
    assert con.execute("SELECT market, selection FROM odds_snapshot").fetchall() == \
        [("totals", "over_2.5")]
    con.close()
