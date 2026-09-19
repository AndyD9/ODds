"""Règle « sûr et payant » — prereg 0006.

Deux seuils qui se contraignent : la cote juste d'un favori à p vaut 1/p.
Le seuil de probabilité est la borne du niveau de confiance « Élevée »
(0,70, cote juste 1,43) ; le plancher de cote, 1,25, reste en dessous, donc
c'est l'écart positif chez un livre réel qui décide. Ces tests fixent ce que
la règle laisse passer, et surtout ce qu'elle refuse — un favori payé sous
son prix juste, un prix qu'on ne peut prendre nulle part, un outsider bien
payé.
"""

import numpy as np
import pytest

import odds.analysis as ana
from odds import chemins

# Six livres qui cotent un gros favori à 1,18, plus un généreux à 1,31.
# Après dévig, le favori sort autour de 80 % : sa cote juste est ~1,25, et
# 1,31 la bat de quelques points.
SERRES = (1.18, 7.0, 15.0)
GENEREUX = (1.31, 6.5, 14.0)


def _base(tmp_path, monkeypatch, livres, jour="2026-10-01"):
    from odds.data.collect import _connexion
    p = tmp_path / "c.db"
    con = _connexion(p)
    lignes = [("fk1", "odds-api", "Spain", "SP1", f"{jour} 20:00", "Betis",
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
    return ana.matchs_a_la_date(jour).resume


@pytest.fixture
def resume(tmp_path, monkeypatch):
    livres = {f"book{i}": SERRES for i in range(6)}
    livres["genereux"] = GENEREUX
    return _base(tmp_path, monkeypatch, livres)


def test_un_favori_paye_au_dessus_de_son_prix_juste_passe(resume):
    g = ana.paris_surs(resume)
    assert len(g) == 1
    r = g.iloc[0]
    assert r.issue_sure == "1", "la règle ne retient que le favori du marché"
    assert r.book_sur == "genereux"
    assert r.cote_sure == pytest.approx(1.31)
    assert r.p_sure >= ana.SEUIL_P_SUR
    assert r.ecart_sur > 0
    # La cote juste du favori est sous la cote offerte : c'est tout le sujet.
    assert 1.0 / r.p_sure < r.cote_sure


def test_le_seuil_est_la_borne_de_la_confiance_elevee():
    """Le seuil « sûr » est le chiffre que la page affiche déjà : pas un de plus."""
    assert ana.SEUIL_P_SUR == pytest.approx(0.70)
    assert ana._niveau(ana.SEUIL_P_SUR) == "Élevée"
    assert ana._niveau(ana.SEUIL_P_SUR - 1e-9) == "Modérée"


def test_le_plancher_de_cote_reste_sous_la_cote_juste(resume):
    """Sinon la règle exige qu'un livre paie mieux que le prix juste, et reste vide.

    À 0,80 / 1,25 c'était le cas (0 candidat sur 144 matchs, prereg 0006 §1).
    Tout candidat retenu bat quand même sa cote juste : c'est la condition
    d'écart positif qui l'impose, pas le plancher.
    """
    assert ana.SEUIL_COTE_SURE < 1.0 / ana.SEUIL_P_SUR
    r = ana.paris_surs(resume).iloc[0]
    assert r.p_sure * r.cote_sure_nette > 1.0


def test_un_favori_de_confiance_elevee_passe_au_defaut(tmp_path, monkeypatch):
    """Un favori autour de 72 %, payé au-dessus de sa cote juste.

    Refusé au seuil d'origine (0,80), retenu au seuil « Élevée » : c'est le
    changement du 2026-09-19, et son prix — un pari sur quatre perd.
    """
    livres = {f"book{i}": (1.32, 5.0, 9.0) for i in range(6)}
    livres["genereux"] = (1.48, 4.8, 8.5)
    resume = _base(tmp_path, monkeypatch, livres)
    r0 = resume.iloc[0]
    assert 0.70 <= r0.p_probable < 0.80, f"p_probable = {r0.p_probable:.3f}"
    g = ana.paris_surs(resume)
    assert len(g) == 1 and g.iloc[0].book_sur == "genereux"
    assert 1.0 / g.iloc[0].p_sure < g.iloc[0].cote_sure_nette
    assert len(ana.paris_surs(resume, p_min=0.80)) == 0


def test_une_cote_sous_le_seuil_est_refusee(resume):
    assert len(ana.paris_surs(resume, cote_min=1.40)) == 0


def test_un_favori_trop_juste_est_refuse(resume):
    assert len(ana.paris_surs(resume, p_min=0.90)) == 0


def test_sans_livre_genereux_la_regle_ne_propose_rien(tmp_path, monkeypatch):
    """Au prix du marché, un favori est toujours payé SOUS son prix juste.

    C'est le cas ordinaire, et le motif de la page vide : un livre vit
    précisément de ne pas payer le prix juste.
    """
    resume = _base(tmp_path, monkeypatch, {f"book{i}": SERRES for i in range(7)})
    r = resume.iloc[0]
    assert r.p_probable >= 0.75, "le favori de ce jeu d'essai est bien net"
    assert r.best_1 < 1.0 / r.p_1, "le meilleur prix reste sous la cote juste"
    assert len(ana.paris_surs(resume)) == 0


def test_un_outsider_bien_paye_ne_passe_pas(tmp_path, monkeypatch):
    """La règle ne dit rien des outsiders — c'est sa raison d'être."""
    livres = {f"book{i}": SERRES for i in range(6)}
    livres["genereux_ext"] = (1.18, 7.0, 40.0)   # l'extérieur, très bien payé
    resume = _base(tmp_path, monkeypatch, livres)
    assert resume.iloc[0].issue_prix == "2", "l'écart de prix vise bien l'outsider"
    assert len(ana.paris_surs(resume)) == 0


def test_une_cote_d_exchange_est_jugee_nette(tmp_path, monkeypatch):
    """1,31 brut chez Betfair paie 1,295 : sous le seuil de 1,30."""
    livres = {f"book{i}": SERRES for i in range(6)}
    livres["betfair_ex_eu"] = GENEREUX
    resume = _base(tmp_path, monkeypatch, livres)
    r = ana.paris_surs(resume, cote_min=1.25).iloc[0]
    assert r.cote_sure == pytest.approx(1.31)
    assert r.cote_sure_nette == pytest.approx(1.2945)
    assert len(ana.paris_surs(resume, cote_min=1.30)) == 0, (
        "1,31 brut ne vaut pas 1,30 une fois la commission prise")


def test_le_verdict_accompagne_sans_filtrer(resume):
    """La règle dit ce qui est sûr et payant ; le verdict dit ce que vaut le prix."""
    r = ana.paris_surs(resume).iloc[0]
    assert r.verdict_sur in ("Écart soutenu", "Écart isolé — prudence",
                             "Fragile — dépend de la méthode", "Rien à signaler",
                             "Trop peu de books")
    assert np.isfinite(r.ev_min_sur) and np.isfinite(r.ev_max_sur)
    assert r.ev_min_sur <= r.ecart_sur <= r.ev_max_sur + 1e-9


def test_un_resume_vide_rend_les_colonnes(tmp_path, monkeypatch):
    """La page lit ces colonnes sans regarder si la table est vide."""
    import pandas as pd
    g = ana.paris_surs(pd.DataFrame())
    assert len(g) == 0
    for c in ("issue_sure", "p_sure", "cote_sure_nette", "book_sur", "verdict_sur"):
        assert c in g.columns
