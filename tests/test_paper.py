"""Carnet papier et moteur de mise (prereg 0001 §4 et §5).

Ces tests portent surtout sur les endroits où une erreur serait silencieuse :
les plafonds qui ne se déclenchent pas, un pari annulé compté comme perdu,
un CLV calculé sur une cote postérieure au coup d'envoi.
"""

import sqlite3

import numpy as np
import pandas as pd
import pytest

from odds import paper


@pytest.fixture
def carnet(tmp_path):
    """Chemin d'un carnet vide, isolé du carnet réel."""
    return tmp_path / "paper.db"


# ---------------------------------------------------------------------------
# Moteur de mise
# ---------------------------------------------------------------------------

def test_kelly_formule_du_prereg():
    # (p × cote − 1) / (cote − 1) — prereg 0001 §4.
    assert paper.kelly(0.5, 3.0) == pytest.approx((0.5 * 3 - 1) / 2)
    assert paper.kelly(0.6, 2.0) == pytest.approx(0.2)


def test_kelly_negatif_au_prix_juste_ou_en_dessous():
    # À la cote juste exactement, l'espérance est nulle.
    assert paper.kelly(0.5, 2.0) == pytest.approx(0.0)
    # En dessous, elle est négative — et le signe doit être conservé.
    assert paper.kelly(0.5, 1.8) < 0


def test_kelly_refuse_une_cote_impossible():
    with pytest.raises(ValueError):
        paper.kelly(0.5, 1.0)
    with pytest.raises(ValueError):
        paper.kelly(1.5, 2.0)


def test_confiance_penalise_un_petit_echantillon():
    plein = paper.confiance(n_hist=5_000, n_books=12, ev_robuste=True)
    maigre = paper.confiance(n_hist=200, n_books=12, ev_robuste=True)
    assert plein["confiance"] == pytest.approx(1.0)
    assert maigre["confiance"] < plein["confiance"]


def test_confiance_ignore_un_signal_absent():
    # Ne pas avoir mesuré n'est pas une raison de pénaliser.
    assert paper.confiance()["confiance"] == pytest.approx(1.0)


def test_confiance_divise_par_deux_si_le_signe_change_selon_la_methode():
    solide = paper.confiance(n_hist=5_000, n_books=12, ev_robuste=True)
    fragile = paper.confiance(n_hist=5_000, n_books=12, ev_robuste=False)
    assert fragile["confiance"] == pytest.approx(
        solide["confiance"] * paper.CONFIANCE_PENALITE_FRAGILE)


def test_plafond_par_match_a_1_pourcent():
    # Kelly large : le plafond de §4 doit mordre.
    r = paper.proposer_mise(bankroll=1000, p=0.60, cote=2.5)
    assert r["kelly"] > 0
    assert r["mise"] == pytest.approx(10.0)      # 1 % de 1 000
    assert r["plafond"] == "match"


def test_plafond_d_exposition_simultanee():
    # 48 € déjà engagés sur une bankroll de 1 000 : il ne reste que 2 €
    # avant le plafond de 5 %.
    r = paper.proposer_mise(bankroll=1000, p=0.60, cote=2.5, exposition=48.0)
    assert r["mise"] == pytest.approx(2.0)
    assert r["plafond"] == "exposition"


def test_exposition_saturee_ne_propose_rien():
    r = paper.proposer_mise(bankroll=1000, p=0.60, cote=2.5, exposition=50.0)
    assert r["mise"] == 0.0
    assert r["plafond"] == "exposition"


def test_aucune_mise_proposee_sans_avantage():
    r = paper.proposer_mise(bankroll=1000, p=0.50, cote=1.90)
    assert r["kelly"] < 0
    assert r["mise"] == 0.0
    assert r["plafond"] == "kelly"


def test_mise_sous_les_plafonds_suit_kelly_fractionnaire():
    # Avantage ténu : ni l'un ni l'autre plafond ne doit intervenir.
    r = paper.proposer_mise(bankroll=1000, p=0.51, cote=2.0)
    attendu = 1000 * paper.kelly(0.51, 2.0) * paper.F_BASE
    assert r["plafond"] is None
    assert r["mise"] == pytest.approx(round(attendu, 2))


# ---------------------------------------------------------------------------
# Carnet
# ---------------------------------------------------------------------------

def _pari(carnet, issue="1", cote=2.0, mise=10.0, p=0.55, **kw):
    return paper.enregistrer(
        fixture_key=kw.pop("fixture_key", "oa:abc"),
        kickoff=kw.pop("kickoff", "2026-09-18 18:00"),
        home_team="Bayern Munich", away_team="Union Berlin",
        issue=issue, cote=cote, p_modele=p, mise=mise,
        chemin=carnet, **kw)


def test_enregistrer_puis_relire(carnet):
    pid = _pari(carnet)
    d = paper.paris(carnet)
    assert len(d) == 1
    assert int(d.id.iloc[0]) == pid
    assert d.statut.iloc[0] == "en attente"
    assert np.isnan(d.profit.iloc[0])


def test_enregistrer_refuse_une_saisie_absurde(carnet):
    with pytest.raises(ValueError):
        _pari(carnet, issue="X")
    with pytest.raises(ValueError):
        _pari(carnet, cote=0.9)
    with pytest.raises(ValueError):
        _pari(carnet, mise=0)


def test_gain_et_perte(carnet):
    gagnant = _pari(carnet, issue="1", cote=2.5, mise=10)
    perdant = _pari(carnet, issue="2", cote=3.0, mise=10)
    # Un seul score règle les deux paris du match.
    assert paper.regler_match("oa:abc", 2, 1, chemin=carnet) == 2

    d = paper.paris(carnet).set_index("id")
    assert d.loc[gagnant, "statut"] == "gagné"
    assert d.loc[gagnant, "retour"] == pytest.approx(25.0)
    assert d.loc[gagnant, "profit"] == pytest.approx(15.0)
    assert d.loc[perdant, "statut"] == "perdu"
    assert d.loc[perdant, "profit"] == pytest.approx(-10.0)


def test_un_pari_annule_est_rembourse_pas_perdu(carnet):
    pid = _pari(carnet, mise=10)
    paper.annuler(pid, chemin=carnet)
    d = paper.paris(carnet).set_index("id")
    assert d.loc[pid, "statut"] == "annulé"
    assert d.loc[pid, "profit"] == pytest.approx(0.0)
    # ... et il ne doit pas entrer dans le dénominateur du ROI.
    assert paper.bilan(paper.paris(carnet))["n_regles"] == 0


def test_regler_refuse_un_score_absurde(carnet):
    _pari(carnet)
    with pytest.raises(ValueError):
        paper.regler_match("oa:abc", -1, 0, chemin=carnet)


def test_regler_un_match_sans_pari_ne_fait_rien(carnet):
    _pari(carnet)
    assert paper.regler_match("oa:inconnu", 1, 0, chemin=carnet) == 0
    assert paper.paris(carnet).statut.iloc[0] == "en attente"


def test_annuler_un_pari_inexistant_leve(carnet):
    with pytest.raises(KeyError):
        paper.annuler(4242, chemin=carnet)


def test_derregler_remet_en_attente(carnet):
    pid = _pari(carnet)
    paper.regler_match("oa:abc", 1, 0, chemin=carnet)
    paper.derregler(pid, chemin=carnet)
    d = paper.paris(carnet)
    assert d.statut.iloc[0] == "en attente"
    # Le score est retiré avec le verdict : sinon un carnet dérèglé
    # porterait un score sans règlement, et la prochaine lecture croirait
    # le pari soldé.
    assert pd.isna(d.buts_dom.iloc[0])


def test_filtre_par_periode(carnet):
    _pari(carnet, kickoff="2026-09-02 18:00")
    _pari(carnet, kickoff="2026-10-02 18:00")
    assert len(paper.paris(carnet, depuis="2026-10-01")) == 1
    assert len(paper.paris(carnet, jusqua="2026-09-30")) == 1


# ---------------------------------------------------------------------------
# Bankroll
# ---------------------------------------------------------------------------

def test_bankroll_vide_vaut_l_initiale(carnet):
    b = paper.bankroll(carnet)
    assert b["courante"] == pytest.approx(paper.BANKROLL_DEFAUT)
    assert b["exposition"] == 0.0
    assert b["drawdown"] == pytest.approx(0.0)


def test_bankroll_initiale_modifiable_et_persistante(carnet):
    paper.definir_bankroll_initiale(500, chemin=carnet)
    assert paper.bankroll_initiale(carnet) == pytest.approx(500)
    assert paper.bankroll(carnet)["courante"] == pytest.approx(500)


def test_bankroll_initiale_refuse_zero(carnet):
    with pytest.raises(ValueError):
        paper.definir_bankroll_initiale(0, chemin=carnet)


def test_exposition_ne_compte_que_les_paris_en_attente(carnet):
    ouvert = _pari(carnet, mise=10)
    clos = _pari(carnet, mise=10, fixture_key="oa:clos")
    paper.regler_match("oa:clos", 1, 0, chemin=carnet)
    b = paper.bankroll(carnet)
    assert b["exposition"] == pytest.approx(10.0)
    assert b["exposition_restante"] == pytest.approx(
        paper.PLAFOND_EXPOSITION * b["courante"] - 10.0)
    assert ouvert  # le pari ouvert existe bien


def test_drawdown_mesure_depuis_le_pic(carnet):
    paper.definir_bankroll_initiale(1000, chemin=carnet)
    gagnant = _pari(carnet, issue="1", cote=3.0, mise=100)   # +200 -> 1200
    perdant = _pari(carnet, issue="2", cote=3.0, mise=300)   # -300 -> 900
    paper.regler_match("oa:abc", 1, 0, chemin=carnet)
    assert gagnant < perdant

    b = paper.bankroll(carnet)
    assert b["courante"] == pytest.approx(900.0)
    assert b["pic"] == pytest.approx(1200.0)
    assert b["drawdown"] == pytest.approx(300 / 1200)
    assert b["reexamen"] is True     # 25 % > seuil de 20 % de §4


# ---------------------------------------------------------------------------
# Bilan
# ---------------------------------------------------------------------------

def test_bilan_roi_et_garde_fou_du_prereg(carnet):
    _pari(carnet, issue="1", cote=3.0, mise=10)
    _pari(carnet, issue="2", cote=3.0, mise=10)
    paper.regler_match("oa:abc", 1, 0, chemin=carnet)

    b = paper.bilan(paper.paris(carnet))
    assert b["n_regles"] == 2
    assert b["mises"] == pytest.approx(20.0)
    assert b["profit"] == pytest.approx(10.0)
    assert b["roi"] == pytest.approx(0.5)
    # prereg §2 : sous 20 000 paris, aucune affirmation sur le ROI.
    assert b["roi_interpretable"] is False
    assert b["n_manquants_roi"] == paper.N_MIN_ROI - 2


def test_bilan_d_un_carnet_vide_ne_casse_pas(carnet):
    b = paper.bilan(paper.paris(carnet))
    assert b["n"] == 0
    assert np.isnan(b["roi"])


# ---------------------------------------------------------------------------
# CLV
# ---------------------------------------------------------------------------

def _base_collecte(chemin, lignes):
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE odds_snapshot (fixture_key TEXT, kickoff TEXT, "
                "bookmaker TEXT, market TEXT, selection TEXT, odds REAL, "
                "observed_at TEXT)")
    con.executemany("INSERT INTO odds_snapshot VALUES (?,?,?,?,?,?,?)", lignes)
    con.commit()
    con.close()
    return chemin


def test_clv_calcule_sur_la_derniere_cote_avant_le_coup_d_envoi(carnet, tmp_path):
    bdd = _base_collecte(tmp_path / "odds.db", [
        ("oa:abc", "2026-09-10 18:00", "betfair_ex_eu", "1X2", "home", 2.20,
         "2026-09-10 12:00"),
        ("oa:abc", "2026-09-10 18:00", "betfair_ex_eu", "1X2", "home", 2.00,
         "2026-09-10 17:30"),
        # Postérieure au coup d'envoi : ne doit jamais être retenue.
        ("oa:abc", "2026-09-10 18:00", "betfair_ex_eu", "1X2", "home", 1.10,
         "2026-09-10 19:00"),
    ])
    _pari(carnet, issue="1", cote=2.20, kickoff="2026-09-10 18:00")
    assert paper.capturer_clotures(chemin=carnet, bdd=bdd) == 1

    d = paper.paris(carnet)
    assert d.cote_cloture.iloc[0] == pytest.approx(2.00)
    assert d.clv.iloc[0] == pytest.approx(10.0)   # 2.20 / 2.00 − 1


def test_clv_prefere_la_bourse_d_echange(carnet, tmp_path):
    bdd = _base_collecte(tmp_path / "odds.db", [
        ("oa:abc", "2026-09-10 18:00", "williamhill", "1X2", "home", 1.80,
         "2026-09-10 17:00"),
        ("oa:abc", "2026-09-10 18:00", "betfair_ex_eu", "1X2", "home", 2.00,
         "2026-09-10 17:00"),
    ])
    _pari(carnet, issue="1", cote=2.20, kickoff="2026-09-10 18:00")
    paper.capturer_clotures(chemin=carnet, bdd=bdd)
    assert paper.paris(carnet).book_cloture.iloc[0] == "betfair_ex_eu"


def test_clv_absent_quand_le_match_n_a_pas_ete_collecte(carnet, tmp_path):
    bdd = _base_collecte(tmp_path / "odds.db", [])
    _pari(carnet, issue="1", cote=2.20, kickoff="2026-09-10 18:00")
    assert paper.capturer_clotures(chemin=carnet, bdd=bdd) == 0
    assert paper.paris(carnet).cote_cloture.isna().all()


def test_capture_ne_touche_pas_un_match_a_venir(carnet, tmp_path):
    bdd = _base_collecte(tmp_path / "odds.db", [
        ("oa:futur", "2099-01-01 18:00", "betfair_ex_eu", "1X2", "home", 2.0,
         "2098-12-31 12:00"),
    ])
    _pari(carnet, fixture_key="oa:futur", kickoff="2099-01-01 18:00")
    assert paper.capturer_clotures(chemin=carnet, bdd=bdd) == 0


def test_capture_est_idempotente(carnet, tmp_path):
    bdd = _base_collecte(tmp_path / "odds.db", [
        ("oa:abc", "2026-09-10 18:00", "pinnacle", "1X2", "home", 2.0,
         "2026-09-10 17:00"),
    ])
    _pari(carnet, issue="1", cote=2.2, kickoff="2026-09-10 18:00")
    assert paper.capturer_clotures(chemin=carnet, bdd=bdd) == 1
    assert paper.capturer_clotures(chemin=carnet, bdd=bdd) == 0


def test_annuler_vise_l_identifiant_et_non_la_position(carnet):
    """Le tableau est trié par coup d'envoi, pas par identifiant.

    Annuler « la 2e ligne » au lieu de « le pari n° 1 » solderait le mauvais
    pari sans rien signaler — c'est l'erreur que ce test interdit. Le
    règlement, lui, passe par le match entier et ne peut plus se tromper de
    ligne ; l'annulation reste unitaire, donc exposée.
    """
    tardif = _pari(carnet, issue="1", cote=2.0, kickoff="2026-09-20 18:00",
                   fixture_key="oa:tardif")
    tot = _pari(carnet, issue="2", cote=3.0, kickoff="2026-09-19 18:00",
                fixture_key="oa:tot")

    # paris() trie par coup d'envoi décroissant : le pari tardif est en tête,
    # donc l'ordre des lignes est l'inverse de l'ordre des identifiants.
    en_attente = paper.paris(carnet)
    assert list(en_attente.id) == [tardif, tot]

    ligne = en_attente.iloc[1]
    paper.annuler(int(ligne.id), chemin=carnet)

    d = paper.paris(carnet).set_index("id")
    assert d.loc[tot, "statut"] == "annulé"
    assert d.loc[tardif, "statut"] == "en attente"


# ---------------------------------------------------------------------------
# Marchés de buts
# ---------------------------------------------------------------------------

def test_un_score_regle_tous_les_marches_du_match(carnet):
    """Le cœur du règlement par le score : une saisie, tous les marchés.

    Chaque marché décide lui-même, par le prédicat qui a servi à le coter
    (odds.models.football.buts). Il devient impossible qu'un pari soit coté
    selon une règle et réglé selon une autre.
    """
    paris = {code: _pari(carnet, issue=code, cote=2.0, mise=10)
             for code in ("1", "2", "total_over_2.5", "total_under_2.5",
                          "dom_over_1.5", "ext_over_0.5", "btts_oui")}
    assert paper.regler_match("oa:abc", 3, 0, chemin=carnet) == len(paris)

    d = paper.paris(carnet).set_index("id")
    attendu = {"1": "gagné", "2": "perdu",
               "total_over_2.5": "gagné",     # 3 buts
               "total_under_2.5": "perdu",
               "dom_over_1.5": "gagné",       # le domicile en met 3
               "ext_over_0.5": "perdu",       # l'extérieur n'en met aucun
               "btts_oui": "perdu"}
    for code, statut in attendu.items():
        assert d.loc[paris[code], "statut"] == statut, code
    assert (d.buts_dom == 3).all() and (d.buts_ext == 0).all()


def test_la_famille_du_marche_est_enregistree(carnet):
    _pari(carnet, issue="dom_over_1.5")
    d = paper.paris(carnet)
    assert d.marche.iloc[0] == "total_dom"
    assert d.issue.iloc[0] == "dom_over_1.5"


def test_un_marche_inconnu_est_refuse(carnet):
    with pytest.raises(ValueError, match="marché invalide"):
        _pari(carnet, issue="total_over_2")


def test_libelle_nomme_les_equipes():
    assert paper.libelle("total_over_2.5") == "3 buts ou plus dans le match"
    assert paper.libelle("dom_over_1.5", "Lens", "Reims") == "Lens marque 2 buts ou plus"


def test_clv_sur_un_total_lit_le_vocabulaire_unique(carnet, tmp_path):
    """La collecte range les totaux sous `totals/over_2.5`, quelle que soit la
    source : le carnet n'a qu'une graphie à connaître."""
    assert paper.selections_collectees("total_over_2.5") == (("totals", "over_2.5"),)
    assert paper.selections_collectees("total_under_3.5") == (("totals", "under_3.5"),)
    bdd = _base_collecte(tmp_path / "odds.db", [
        ("oa:abc", "2026-09-10 18:00", "betfair_ex_eu", "totals", "over_2.5",
         1.90, "2026-09-10 17:00"),
    ])
    _pari(carnet, issue="total_over_2.5", cote=2.0, kickoff="2026-09-10 18:00")
    assert paper.capturer_clotures(chemin=carnet, bdd=bdd) == 1
    assert paper.paris(carnet).cote_cloture.iloc[0] == pytest.approx(1.90)


def test_pas_de_clv_sur_un_total_par_equipe(carnet, tmp_path):
    """Les team totals ne sont cotés par aucune source accessible.

    Le CLV manque donc précisément là où la probabilité est dérivée plutôt
    que lue. C'est une limite à afficher, pas à masquer.
    """
    assert paper.selections_collectees("dom_over_1.5") == ()
    assert paper.selections_collectees("btts_oui") == ()
    bdd = _base_collecte(tmp_path / "odds.db", [
        ("oa:abc", "2026-09-10 18:00", "betfair_ex_eu", "1X2", "home", 2.0,
         "2026-09-10 17:00"),
    ])
    _pari(carnet, issue="dom_over_1.5", cote=2.0, kickoff="2026-09-10 18:00")
    assert paper.capturer_clotures(chemin=carnet, bdd=bdd) == 0


def test_migration_d_un_carnet_anterieur(tmp_path):
    """Un carnet d'avant l'ouverture aux buts doit se relire sans perte.

    L'ancienne colonne `resultat` portait l'issue SURVENUE et se comparait au
    pari ; elle porte désormais le verdict. Rater cette conversion
    inverserait des gains et des pertes en silence.
    """
    chemin = tmp_path / "ancien.db"
    con = sqlite3.connect(chemin)
    con.execute("""CREATE TABLE pari (
        id INTEGER PRIMARY KEY AUTOINCREMENT, place_a TEXT, fixture_key TEXT,
        source TEXT, league TEXT, kickoff TEXT, home_team TEXT, away_team TEXT,
        issue TEXT, cote REAL, bookmaker TEXT, p_modele REAL, methode TEXT,
        mise REAL, mise_proposee REAL, bankroll_avant REAL, kelly REAL,
        f_effectif REAL, plafond TEXT, cote_cloture REAL, book_cloture TEXT,
        resultat TEXT, regle_a TEXT, note TEXT)""")
    con.executemany(
        "INSERT INTO pari (place_a, fixture_key, kickoff, home_team, away_team, "
        "issue, cote, p_modele, mise, resultat, regle_a) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            ("2026-09-01 10:00", "oa:x", "2026-09-01 18:00", "A", "B",
             "1", 2.5, 0.5, 10.0, "1", "2026-09-01 21:00"),       # gagné
            ("2026-09-01 10:00", "oa:x", "2026-09-01 18:00", "A", "B",
             "2", 3.0, 0.3, 10.0, "1", "2026-09-01 21:00"),       # perdu
            ("2026-09-01 10:00", "oa:y", "2026-09-02 18:00", "C", "D",
             "N", 3.2, 0.3, 10.0, None, None),                    # en attente
        ])
    con.commit()
    con.close()

    d = paper.paris(chemin).set_index("id")
    assert d.loc[1, "statut"] == "gagné"
    assert d.loc[1, "profit"] == pytest.approx(15.0)
    assert d.loc[2, "statut"] == "perdu"
    assert d.loc[3, "statut"] == "en attente"
    assert set(d.marche.dropna()) == {"1X2"}


def test_confiance_penalise_une_probabilite_derivee():
    """R9 : dérivée du 1X2 seul, la probabilité perd 2 à 3 points de
    calibration. Le moteur de mise doit en tenir compte, sans quoi il
    miserait autant sur une estimation que sur un prix."""
    cotee = paper.confiance(n_hist=5000, n_books=10, p_cotee=True)
    derivee = paper.confiance(n_hist=5000, n_books=10, p_cotee=False)
    assert cotee["confiance"] == pytest.approx(1.0)
    assert derivee["confiance"] == pytest.approx(paper.CONFIANCE_PENALITE_DERIVEE)
    # Un signal absent ne pénalise pas : on ne punit pas ce qu'on n'a pas mesuré.
    assert paper.confiance(n_hist=5000, n_books=10)["confiance"] == pytest.approx(1.0)


def test_une_probabilite_derivee_reduit_la_mise():
    commun = dict(bankroll=10_000, p=0.55, cote=2.2, n_hist=5000, n_books=10)
    forte = paper.proposer_mise(**commun, p_cotee=True)
    faible = paper.proposer_mise(**commun, p_cotee=False)
    assert faible["mise"] < forte["mise"]
    assert faible["f_effectif"] == pytest.approx(forte["f_effectif"] / 2)


def test_l_intervalle_du_roi_suit_le_ratio_et_non_la_moyenne_des_rendements(carnet):
    """Deux paris réglés à l'identique (même cote, même verdict) : le ROI est
    exact et l'intervalle nul, quelle que soit la mise. Un intervalle fondé sur
    la moyenne des rendements le dirait aussi ; la différence apparaît dès
    que les mises diffèrent et les verdicts aussi."""
    _pari(carnet, issue="1", cote=2.0, mise=10)
    _pari(carnet, issue="2", cote=2.0, mise=90)
    paper.regler_match("oa:abc", 1, 0, chemin=carnet)      # 1 gagne, 2 perd
    b = paper.bilan(paper.paris(carnet))
    assert b["mises"] == pytest.approx(100.0)
    assert b["profit"] == pytest.approx(10 - 90)
    assert b["roi"] == pytest.approx(-0.8)
    # Résidus e = profit − ROI × mise : (10 + 8, −90 + 72) = (18, −18).
    # Var(e, ddof=1) = 648 ; IC = 1,96 × √(2 × 648) / 100.
    assert b["roi_ic95"] == pytest.approx(1.96 * (2 * 648) ** 0.5 / 100)


def test_la_migration_ne_rejoue_pas(tmp_path):
    chemin = tmp_path / "vieux.db"
    con = sqlite3.connect(chemin)
    con.executescript(paper.SCHEMA)
    con.execute("INSERT INTO pari (place_a, fixture_key, kickoff, home_team, "
                "away_team, issue, cote, p_modele, mise, resultat) "
                "VALUES ('2026-01-01 00:00:00', 'k', '2026-01-01 20:00', 'A', "
                "'B', '1', 2.0, 0.5, 10, '1')")
    con.commit(); con.close()

    d = paper.paris(chemin)
    assert d.resultat.iloc[0] == "gagne"
    con = sqlite3.connect(chemin)
    assert con.execute("SELECT valeur FROM reglage WHERE cle = 'schema_version'"
                       ).fetchone()[0] == paper.SCHEMA_VERSION
    # Un verdict inscrit APRÈS la migration au format ancien n'est plus
    # réinterprété : la conversion a eu lieu une fois, et une seule.
    con.execute("UPDATE pari SET resultat = 'N'"); con.commit(); con.close()
    assert paper.paris(chemin).resultat.iloc[0] == "N"


# ---------------------------------------------------------------------------
# Valeur — l'espérance mise en avant
# ---------------------------------------------------------------------------

def test_valeur_est_l_esperance_par_unite_misee():
    # p × cote − 1 : le favori sûr n'a pas de valeur, l'outsider payé en a.
    assert paper.valeur(0.80, 1.20) == pytest.approx(-0.04)
    assert paper.valeur(0.24, 4.40) == pytest.approx(0.056)
    assert paper.valeur(0.5, 2.0) == pytest.approx(0.0)


def test_valeur_et_kelly_ont_le_meme_signe():
    for p, cote in ((0.3, 3.0), (0.3, 3.5), (0.6, 1.5), (0.6, 1.8)):
        v, k = paper.valeur(p, cote), paper.kelly(p, cote)
        assert (v > 0) == (k > 0) and (v == 0) == (k == 0)
        # Kelly n'est que la valeur mise à l'échelle par (cote − 1).
        assert k == pytest.approx(v / (cote - 1))


def test_valeur_refuse_les_memes_saisies_que_kelly():
    with pytest.raises(ValueError):
        paper.valeur(0.5, 1.0)
    with pytest.raises(ValueError):
        paper.valeur(1.2, 2.0)


def test_le_carnet_porte_la_valeur_annoncee(carnet):
    pid = _pari(carnet, cote=2.5, p=0.5, mise=10)   # +25 % de valeur
    d = paper.paris(carnet).set_index("id")
    assert d.loc[pid, "valeur"] == pytest.approx(25.0)
    assert d.loc[pid, "esperance"] == pytest.approx(2.5)


def test_bilan_compare_l_esperance_annoncee_au_profit(carnet):
    # Deux paris à +25 % de valeur, 10 € chacun : 5 € attendus au total.
    _pari(carnet, issue="1", cote=2.5, p=0.5, mise=10)
    _pari(carnet, issue="2", cote=2.5, p=0.5, mise=10)
    en_attente = paper.bilan(paper.paris(carnet))
    assert en_attente["esperance"] == pytest.approx(0.0)
    assert en_attente["esperance_en_attente"] == pytest.approx(5.0)

    paper.regler_match("oa:abc", 1, 0, chemin=carnet)
    b = paper.bilan(paper.paris(carnet))
    assert b["esperance"] == pytest.approx(5.0)
    assert b["valeur_moyenne"] == pytest.approx(0.25)
    assert b["n_valeur_positive"] == 2
    assert b["esperance_en_attente"] == pytest.approx(0.0)
    # Le profit réalisé (+15 − 10 = +5) n'a aucune raison d'égaler l'espérance.
    assert b["profit"] == pytest.approx(5.0)


def test_un_pari_annule_n_entre_pas_dans_l_esperance(carnet):
    pid = _pari(carnet, cote=2.5, p=0.5, mise=10)
    paper.annuler(pid, chemin=carnet)
    b = paper.bilan(paper.paris(carnet))
    assert b["esperance"] == pytest.approx(0.0)
    assert np.isnan(b["valeur_moyenne"])
    assert b["n_valeur_positive"] == 0


def test_bilan_vide_porte_les_champs_de_valeur(carnet):
    b = paper.bilan(paper.paris(carnet))
    assert b["esperance"] == 0.0 and b["esperance_en_attente"] == 0.0
    assert np.isnan(b["valeur_moyenne"])
