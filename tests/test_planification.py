"""Tests de l'ordonnanceur de crédits The Odds API.

Ce que ces tests protègent : le défaut constaté le 2026-09-18 — douze
passes, quatorze crédits, budget vidé avant midi, plus rien pour relever
les cotes avant les coups d'envoi du soir. Le CLV se mesure contre la
dernière cote observée avant le coup d'envoi ; une passe mal placée ne se
rachète pas.

``planifier`` est une fonction pure : aucun de ces tests ne touche au
réseau ni au budget réel.
"""

import pandas as pd
import pytest

from odds.data.collect import FENETRES, planifier

MAINTENANT = pd.Timestamp("2026-09-19 08:00:00", tz="UTC")


def _plan(**delais_heures) -> pd.DataFrame:
    """Plan factice : championnat -> heures avant son prochain coup d'envoi."""
    return pd.DataFrame([
        {"sport": s, "n_total": 3, "n_proches": 1 if h <= 36 else 0,
         "prochain": MAINTENANT + pd.Timedelta(hours=h), "erreur": None}
        for s, h in delais_heures.items()
    ])


def test_le_coup_d_envoi_imminent_passe_devant():
    d = planifier(_plan(lointain=30.0, imminent=1.0), dispo=2, cout_unitaire=1,
                  maintenant=MAINTENANT)
    retenus = d[d.retenu].sport.tolist()
    assert retenus[0] == "imminent"
    assert d.set_index("sport").loc["imminent", "fenetre"] == FENETRES[0][0]


def test_la_reserve_protege_la_passe_de_cloture_du_soir():
    """Un seul crédit, un match ce soir : on ne le dépense pas ce matin.

    C'est le cœur du correctif. « ce_soir » joue dans 11 h — donc encore
    aujourd'hui — et aura besoin d'une passe à T−1 h. « demain » joue dans
    30 h et sera payé sur le budget de demain : il attend.
    """
    d = planifier(_plan(ce_soir=11.0, demain=30.0), dispo=1, cout_unitaire=1,
                  maintenant=MAINTENANT)
    assert d.retenu.sum() == 0
    assert d[d.sport == "demain"].motif.iloc[0].endswith("clôture du jour")


def test_la_reserve_ne_bloque_pas_la_passe_de_cloture_elle_meme():
    """La réserve borne les fenêtres lointaines, jamais la clôture."""
    d = planifier(_plan(maintenant_=0.5, ce_soir=11.0), dispo=1, cout_unitaire=1,
                  maintenant=MAINTENANT)
    assert d[d.retenu].sport.tolist() == ["maintenant_"]


def test_la_cadence_evite_de_repayer_un_championnat_lointain():
    plan = _plan(lointain=30.0)
    vus = {"lointain": MAINTENANT - pd.Timedelta(hours=2)}
    d = planifier(plan, dispo=10, cout_unitaire=1, dernieres_passes=vus,
                  maintenant=MAINTENANT)
    assert d.retenu.sum() == 0
    assert "cadence" in d.motif.iloc[0]

    # Passé la cadence de 12 h, il redevient éligible.
    vus = {"lointain": MAINTENANT - pd.Timedelta(hours=13)}
    d = planifier(plan, dispo=10, cout_unitaire=1, dernieres_passes=vus,
                  maintenant=MAINTENANT)
    assert d.retenu.sum() == 1


def test_la_cloture_ignore_la_cadence():
    """À T−1 h, on repaye même si on vient de relever : c'est le prix du CLV."""
    plan = _plan(imminent=1.0)
    vus = {"imminent": MAINTENANT - pd.Timedelta(minutes=20)}
    d = planifier(plan, dispo=10, cout_unitaire=1, dernieres_passes=vus,
                  maintenant=MAINTENANT)
    assert d.retenu.sum() == 1


def test_un_championnat_sans_match_proche_ne_coute_rien():
    d = planifier(_plan(rien=200.0), dispo=10, cout_unitaire=1,
                  maintenant=MAINTENANT)
    assert d.retenu.sum() == 0
    assert d.fenetre.isna().all()


def test_un_match_deja_commence_n_est_pas_un_coup_d_envoi_imminent():
    d = planifier(_plan(en_cours=-0.5), dispo=10, cout_unitaire=1,
                  maintenant=MAINTENANT)
    assert d.retenu.sum() == 0
    assert "déjà passé" in d.motif.iloc[0]


def test_le_cout_unitaire_est_respecte():
    """Deux marchés = 2 crédits par championnat : deux fois moins de passes."""
    plan = _plan(a=1.0, b=1.5, c=2.0)
    assert planifier(plan, dispo=3, cout_unitaire=1,
                     maintenant=MAINTENANT).retenu.sum() == 3
    assert planifier(plan, dispo=3, cout_unitaire=2,
                     maintenant=MAINTENANT).retenu.sum() == 1


def test_budget_nul_et_plan_vide():
    assert planifier(_plan(a=1.0), dispo=0, cout_unitaire=1,
                     maintenant=MAINTENANT).retenu.sum() == 0
    assert len(planifier(pd.DataFrame(), dispo=10, cout_unitaire=1,
                         maintenant=MAINTENANT)) == 0


def test_chaque_ligne_porte_un_motif():
    """Un ordonnanceur qui n'explique pas ses refus est indébogable."""
    d = planifier(_plan(a=1.0, b=11.0, c=30.0, d=200.0), dispo=1,
                  cout_unitaire=1, maintenant=MAINTENANT)
    assert d.motif.notna().all()


def test_la_reserve_couvre_un_coup_d_envoi_juste_apres_minuit():
    """À 21 h, un match à 00 h 30 se relèvera à 22 h 30 — sur le budget
    d'AUJOURD'HUI. Sa passe de clôture doit être réservée au même titre que
    celle d'un match à 23 h 30, sinon la fenêtre « veille » d'un autre
    championnat la consomme et la clôture tombe sur un budget vide."""
    soir = pd.Timestamp("2026-09-18 21:00:00", tz="UTC")
    plan = pd.DataFrame([
        {"sport": "nuit", "n_total": 1, "n_proches": 1,
         "prochain": soir + pd.Timedelta(hours=3.5), "erreur": None},
        {"sport": "lointain", "n_total": 1, "n_proches": 1,
         "prochain": soir + pd.Timedelta(hours=30), "erreur": None},
    ])
    d = planifier(plan, dispo=1, cout_unitaire=1, maintenant=soir).set_index("sport")
    assert not d.loc["lointain", "retenu"]
    assert "réservé" in d.loc["lointain", "motif"]
    # Et à 22 h 30, la clôture de « nuit » est servie sur ce crédit.
    d2 = planifier(plan, dispo=1, cout_unitaire=1,
                   maintenant=soir + pd.Timedelta(hours=1.5)).set_index("sport")
    assert d2.loc["nuit", "retenu"]
    assert d2.loc["nuit", "fenetre"] == FENETRES[0][0]
