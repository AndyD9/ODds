"""Commission des bourses d'échange.

Le sujet de ces tests n'est pas l'arithmétique — elle tient en une ligne —
mais le fait qu'elle soit appliquée **partout où un prix se compare ou se
paie** : sélection du meilleur prix, écart au consensus, mise proposée,
carnet, CLV. Le jour où l'un de ces chemins repasse à la cote brute, une
bourse redevient la meilleure offre de toutes les pages, et l'outil se remet
à recommander des paris dont l'avantage est déjà pris.
"""

import sqlite3

import numpy as np
import pytest

import odds.analysis as ana
from odds import chemins, config, paper
from odds.market import commission


# --- l'arithmétique, et à qui elle s'applique ------------------------------

def test_la_commission_porte_sur_le_gain_pas_sur_la_mise():
    # 5 % de (2,38 − 1) = 0,069 retirés au gain, pas à la cote.
    assert commission.cote_nette(2.38, "betfair_ex_eu") == pytest.approx(2.311)
    assert commission.cote_nette(6.00, "matchbook") == pytest.approx(5.925)


def test_un_bookmaker_classique_n_est_pas_touche():
    """Sa marge est déjà dans le prix : le dévig la retire, pas nous."""
    assert commission.taux("unibet_nl") == 0.0
    assert commission.cote_nette(2.38, "unibet_nl") == 2.38
    assert commission.cote_nette(2.38, None) == 2.38
    # Betfair Sportsbook est un bookmaker, pas la bourse du même groupe.
    assert not commission.est_exchange("betfair_sportsbook")


def test_le_nom_saisi_a_la_main_est_reconnu():
    """Le carnet accepte du texte libre : « Betfair_EX_EU » doit compter."""
    assert commission.taux(" Betfair_EX_EU ") == 0.05


def test_aller_retour():
    brute = commission.cote_brute(commission.cote_nette(4.10, "smarkets"), "smarkets")
    assert brute == pytest.approx(4.10)


def test_le_taux_du_compte_prime_sur_celui_de_la_bourse(monkeypatch):
    monkeypatch.setenv("COMMISSION_EXCHANGE", "2")
    assert commission.taux("betfair_ex_eu") == pytest.approx(0.02)
    assert commission.taux("matchbook") == pytest.approx(0.02)
    assert commission.taux("unibet_nl") == 0.0, "une surcharge ne crée pas une bourse"


@pytest.mark.parametrize("valeur", ["", "  ", "cinq", "-3", "120"])
def test_un_reglage_illisible_retombe_sur_les_defauts(monkeypatch, valeur):
    """Un .env mal tapé ne doit pas ouvrir la porte à une commission nulle."""
    monkeypatch.setenv("COMMISSION_EXCHANGE", valeur)
    assert commission.taux("betfair_ex_eu") == pytest.approx(0.05)


def test_zero_est_une_valeur_recevable(monkeypatch):
    monkeypatch.setenv("COMMISSION_EXCHANGE", "0")
    assert commission.taux("betfair_ex_eu") == 0.0


# --- le consensus : le meilleur prix est le mieux PAYANT -------------------

@pytest.fixture
def bdd(tmp_path, monkeypatch):
    """Un match, trois livres dont une bourse qui affiche le plus haut.

    Sur le nul, la bourse affiche 3,50 contre 3,40 chez bet365 — mais à 5 %
    de commission elle ne paie que 3,375. C'est exactement le cas que la
    cote brute traite à l'envers.
    """
    p = tmp_path / "c.db"
    from odds.data.collect import _connexion
    con = _connexion(p)
    livres = {
        "bet365": (2.00, 3.40, 4.00),
        "bwin": (2.02, 3.30, 3.90),
        "unibet_nl": (2.01, 3.35, 3.95),
        "betfair_ex_eu": (2.10, 3.50, 4.10),
    }
    lignes = [("fk1", "odds-api", "Spain", "SP1", "2026-10-01 20:00", "Betis",
               "Getafe", book, "1X2", sel, o, "2026-09-30 10:00", "r1")
              for book, cotes in livres.items()
              for sel, o in zip(("home", "draw", "away"), cotes)]
    con.executemany(
        "INSERT INTO odds_snapshot (fixture_key, source, country, league, kickoff, "
        "home_team, away_team, bookmaker, market, selection, odds, observed_at, run_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", lignes)
    con.commit()
    con.close()
    monkeypatch.setattr(chemins, "BDD_COLLECTE", p)
    return p


def test_la_bourse_ne_rafle_pas_le_meilleur_prix_avec_une_cote_brute(bdd):
    res = ana.matchs_a_la_date("2026-10-01").resume.iloc[0]
    assert res.book_N == "bet365", (
        "3,50 chez la bourse paie 3,375 : bet365 à 3,40 paie plus")
    assert res.best_N == pytest.approx(3.40)
    assert res.net_best_N == pytest.approx(3.40)


def test_la_bourse_garde_le_prix_quand_elle_paie_quand_meme_le_plus(bdd):
    """2,10 à 5 % paie 2,045, au-dessus des 2,02 du deuxième."""
    res = ana.matchs_a_la_date("2026-10-01").resume.iloc[0]
    assert res.book_1 == "betfair_ex_eu"
    assert res.best_1 == pytest.approx(2.10), "on affiche la cote vue chez le livre"
    assert res.net_best_1 == pytest.approx(2.045), "on calcule sur ce qu'elle paie"
    assert res.comm_1 == pytest.approx(0.05)


def test_l_ecart_se_mesure_sur_ce_qui_est_encaisse(bdd):
    res = ana.matchs_a_la_date("2026-10-01").resume.iloc[0]
    for sel in ("1", "N", "2"):
        attendu = 100.0 * (res[f"p_loo_{sel}"] * res[f"net_best_{sel}"] - 1.0)
        assert res[f"ecart_{sel}"] == pytest.approx(attendu, abs=1e-9)
    # …et la sélection retenue porte les deux prix, plus le taux appliqué.
    assert res.cote_nette_prix == pytest.approx(
        commission.cote_nette(res.cote_prix, res.book_prix))
    assert res.ev_min <= res.ecart_prix <= res.ev_max + 1e-9, (
        "les bornes des 4 méthodes doivent encadrer l'écart affiché")


def test_le_detail_porte_la_cote_brute_et_la_nette(bdd):
    d = ana.matchs_a_la_date("2026-10-01").detail
    bfe = d[d.bookmaker == "betfair_ex_eu"].iloc[0]
    assert bfe.cote_1 == pytest.approx(2.10)
    assert bfe.net_1 == pytest.approx(2.045)
    assert d[d.bookmaker == "bet365"].iloc[0].net_1 == pytest.approx(2.00)


# --- le carnet : on encaisse le net ----------------------------------------

@pytest.fixture
def carnet(tmp_path):
    return tmp_path / "paper.db"


def test_le_carnet_fige_le_taux_du_pari(carnet):
    paper.enregistrer("fk1", "2026-10-01 20:00", "Betis", "Getafe", "1",
                      cote=3.00, p_modele=0.40, mise=10.0,
                      bookmaker="betfair_ex_eu", chemin=carnet)
    d = paper.paris(chemin=carnet).iloc[0]
    assert d.commission == pytest.approx(0.05)
    assert d.cote == pytest.approx(3.00), "le ticket porte la cote affichée"
    assert d.cote_nette == pytest.approx(2.90)


def test_un_pari_gagnant_sur_une_bourse_rapporte_le_net(carnet):
    paper.enregistrer("fk1", "2026-10-01 20:00", "Betis", "Getafe", "1",
                      cote=3.00, p_modele=0.40, mise=10.0,
                      bookmaker="betfair_ex_eu", chemin=carnet)
    paper.regler_match("fk1", 2, 0, chemin=carnet)
    d = paper.paris(chemin=carnet).iloc[0]
    assert d.statut == "gagné"
    assert d.retour == pytest.approx(29.0), "10 € à 2,90 net, pas à 3,00"
    assert d.profit == pytest.approx(19.0)


def test_l_esperance_annoncee_est_celle_du_prix_net(carnet):
    paper.enregistrer("fk1", "2026-10-01 20:00", "Betis", "Getafe", "1",
                      cote=3.00, p_modele=0.35, mise=10.0,
                      bookmaker="betfair_ex_eu", chemin=carnet)
    d = paper.paris(chemin=carnet).iloc[0]
    # 0,35 × 3,00 = +5 % en brut ; 0,35 × 2,90 = +1,5 % une fois payé.
    assert d.valeur == pytest.approx(1.5)
    assert d.esperance == pytest.approx(0.15)


def test_le_clv_compte_ce_qu_on_a_encaisse(carnet):
    """La clôture est une référence de prix, le pari un paiement.

    Prendre 3,00 sur une bourse alors que le marché clôture à 2,95 n'est pas
    un avantage de +1,7 % : à 5 %, on a encaissé comme un 2,90.
    """
    paper.enregistrer("fk1", "2026-10-01 20:00", "Betis", "Getafe", "1",
                      cote=3.00, p_modele=0.40, mise=10.0,
                      bookmaker="betfair_ex_eu", chemin=carnet)
    con = sqlite3.connect(carnet)
    con.execute("UPDATE pari SET cote_cloture = 2.95, book_cloture = 'pinnacle'")
    con.commit(); con.close()
    d = paper.paris(chemin=carnet).iloc[0]
    assert d.clv == pytest.approx(100.0 * (2.90 / 2.95 - 1.0))
    assert d.clv < 0


def test_un_carnet_anterieur_recoit_le_taux_de_son_livre(carnet):
    """Le pari a toujours payé la commission ; le carnet ne l'écrivait pas."""
    paper.enregistrer("fk1", "2026-10-01 20:00", "Betis", "Getafe", "1",
                      cote=3.00, p_modele=0.40, mise=10.0,
                      bookmaker="betfair_ex_eu", chemin=carnet)
    paper.enregistrer("fk2", "2026-10-01 20:00", "Betis", "Getafe", "1",
                      cote=3.00, p_modele=0.40, mise=10.0,
                      bookmaker="unibet_nl", chemin=carnet)
    # On remet le carnet dans l'état d'avant la v4 : colonne vide, jalon de
    # schéma reculé.
    con = sqlite3.connect(carnet)
    con.execute("UPDATE pari SET commission = NULL")
    con.execute("UPDATE reglage SET valeur = '3' WHERE cle = 'schema_version'")
    con.commit(); con.close()

    d = paper.paris(chemin=carnet).sort_values("fixture_key").reset_index(drop=True)
    assert list(np.round(d.commission, 4)) == [0.05, 0.0]


def test_a_commission_nulle_la_bourse_reprend_la_tete(bdd, monkeypatch):
    """Preuve que le test précédent mord : sans commission, 3,50 gagne.

    Si un jour le price shopping repasse à la cote brute, ce test-ci
    continuera de passer et le précédent tombera — c'est le but.
    """
    monkeypatch.setenv("COMMISSION_EXCHANGE", "0")
    res = ana.matchs_a_la_date("2026-10-01").resume.iloc[0]
    assert res.book_N == "betfair_ex_eu"
    assert res.best_N == pytest.approx(3.50)
