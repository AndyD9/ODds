"""Tests des marchés de buts.

Ce qui est protégé ici, par ordre de gravité :

1. **Cotation et règlement ne peuvent pas diverger.** Un marché coté selon
   une règle et réglé selon une autre inscrirait des gains faux dans le
   carnet, sans qu'aucune erreur ne soit levée. Le test le vérifie par
   simulation exhaustive sur tous les scores plausibles.
2. La matrice implicite reproduit bien les prix qu'on lui donne.
3. Les entrées non dévigées sont refusées plutôt que subies.
"""

import numpy as np
import pytest

from odds.market.devig import devig
from odds.models.football import buts as buts_module
from odds.models.football.buts import (MARCHES, marche, marches_buts,
                                       matrice_implicite, probabilite, regler)

SCORES = [(x, y) for x in range(7) for y in range(7)]


def test_probabilite_et_reglement_sont_la_meme_regle():
    """L'invariant central : P(marché) = somme des scores que le règlement
    déclare gagnants, pondérés par leur probabilité."""
    i = matrice_implicite(0.45, 0.27, 0.28)
    m = i.matrice
    for code in MARCHES:
        attendu = sum(m[x, y] for x, y in SCORES if regler(code, x, y))
        # On ne somme que jusqu'à 6-6, d'où la tolérance : la queue de la
        # distribution au-delà est négligeable mais pas nulle.
        assert probabilite(m, code) == pytest.approx(attendu, abs=2e-3), code


def test_reglement_de_quelques_cas_evidents():
    assert regler("total_over_2.5", 2, 1) is True      # 3 buts
    assert regler("total_over_2.5", 1, 1) is False     # 2 buts
    assert regler("total_under_2.5", 1, 1) is True
    assert regler("dom_over_1.5", 2, 0) is True        # le domicile en met 2
    assert regler("dom_over_1.5", 1, 3) is False
    assert regler("ext_over_1.5", 1, 3) is True
    assert regler("btts_oui", 1, 1) is True
    assert regler("btts_oui", 3, 0) is False
    assert regler("btts_non", 3, 0) is True
    assert regler("1", 2, 1) is True
    assert regler("N", 1, 1) is True
    assert regler("2", 1, 2) is True


def test_over_et_under_sont_complementaires():
    i = matrice_implicite(0.40, 0.28, 0.32)
    for code in [c for c in MARCHES if "_over_" in c]:
        p_o = probabilite(i.matrice, code)
        p_u = probabilite(i.matrice, code.replace("_over_", "_under_"))
        assert p_o + p_u == pytest.approx(1.0, abs=1e-9), code
        # Une ligne en demi-but ne laisse aucun score à cheval : c'est la
        # raison d'être des .5, et le règlement ne peut pas être ambigu.
        for x, y in SCORES:
            assert regler(code, x, y) != regler(code.replace("_over_", "_under_"), x, y)


def test_la_matrice_reproduit_le_1x2_fourni():
    for cotes in ([1.80, 3.60, 4.50], [2.50, 3.30, 2.80], [1.20, 7.00, 15.0]):
        p = devig(np.array(cotes), "shin")
        i = matrice_implicite(*p)
        assert i.fiable, f"{cotes} : écart {i.ecart_max:.4f}"
        assert probabilite(i.matrice, "1") == pytest.approx(p[0], abs=1e-6)
        assert probabilite(i.matrice, "N") == pytest.approx(p[1], abs=1e-6)
        assert probabilite(i.matrice, "2") == pytest.approx(p[2], abs=1e-6)


def test_la_cote_over_under_devient_une_troisieme_contrainte():
    p = devig(np.array([2.10, 3.40, 3.60]), "shin")
    p_over = float(devig(np.array([1.85, 1.95]), "shin")[0])

    libre = matrice_implicite(*p, p_over=p_over)
    assert libre.fiable
    assert probabilite(libre.matrice, "total_over_2.5") == pytest.approx(p_over, abs=1e-6)
    assert libre.contraintes == ("1X2", "over/under")

    # Sans la contrainte, rho reste à sa valeur par défaut et la probabilité
    # d'over est celle que la matrice implique, pas celle que le marché cote.
    contraint = matrice_implicite(*p)
    assert contraint.rho == pytest.approx(buts_module.RHO_DEFAUT)
    assert contraint.contraintes == ("1X2",)


def test_les_buts_attendus_suivent_le_sens_du_match():
    favori = matrice_implicite(*devig(np.array([1.30, 5.50, 9.00]), "shin"))
    equilibre = matrice_implicite(*devig(np.array([2.60, 3.30, 2.70]), "shin"))
    assert favori.lam > favori.mu
    assert equilibre.lam == pytest.approx(equilibre.mu, rel=0.15)
    # Un match verrouillé produit moins de buts qu'un match ouvert.
    ferme = matrice_implicite(*devig(np.array([2.90, 2.90, 2.90]), "shin"))
    assert ferme.buts_attendus < favori.buts_attendus


def test_les_probabilites_non_deviguees_sont_refusees():
    """1/cote ne somme pas à 1 : accepter ces valeurs reviendrait à dériver
    des marchés de buts depuis une distribution qui n'en est pas une."""
    with pytest.raises(ValueError, match="dévig"):
        matrice_implicite(1 / 1.80, 1 / 3.60, 1 / 4.50)
    with pytest.raises(ValueError):
        matrice_implicite(0.5, 0.3, -0.1)
    with pytest.raises(ValueError):
        matrice_implicite(0.45, 0.27, 0.28, p_over=1.4)


def test_marche_inconnu_leve():
    with pytest.raises(ValueError, match="marché inconnu"):
        marche("total_over_2")


def test_tableau_des_marches_nomme_les_equipes():
    i = matrice_implicite(0.45, 0.27, 0.28)
    t = marches_buts(i.matrice, dom="Lille", ext="Brest")
    assert (t.p.between(0, 1)).all()
    assert t.cote_juste.min() > 1.0
    assert "Lille marque 2 buts ou plus" in set(t.libelle)
    assert "3 buts ou plus dans le match" in set(t.libelle)
    # Pas de « 1 buts ».
    assert not any(" 1 buts" in x for x in t.libelle)


def test_fiabilite_derivee_croit_avec_le_desequilibre():
    """R9 : la dérivation tient sur les matchs équilibrés et dérape sur les
    autres. Le seuil n'est pas choisi, il est mesuré."""
    assert buts_module.fiabilite_derivee(0.35)[1] == "fiable"
    assert buts_module.fiabilite_derivee(0.55)[1] == "fiable"
    assert buts_module.fiabilite_derivee(0.75)[1] == "acceptable"
    assert buts_module.fiabilite_derivee(0.84)[1] == "dégradé"
    assert buts_module.fiabilite_derivee(0.97)[1] == "inexploitable"
    # Le biais est monotone : plus le match penche, plus on surestime.
    biais = [buts_module.fiabilite_derivee(x)[0] for x in (0.5, 0.65, 0.75, 0.97)]
    assert biais == sorted(biais)


def test_un_favori_ecrasant_implique_un_total_invraisemblable():
    """Le cas qui a motivé la mesure : reproduire un 1X2 extrême exige un
    lambda énorme. La matrice est « fiable » au sens où elle reproduit les
    prix, et pourtant son total ne l'est pas — d'où une seconde notion."""
    ecrase = matrice_implicite(0.935, 0.047, 0.018)
    equilibre = matrice_implicite(0.40, 0.28, 0.32)
    assert ecrase.fiable           # le 1X2 EST reproduit
    assert ecrase.buts_attendus > 4.5
    assert 2.0 < equilibre.buts_attendus < 3.5
    assert buts_module.fiabilite_derivee(0.935)[1] == "dégradé"


def test_une_cote_de_totaux_incompatible_rend_la_matrice_non_fiable():
    """Un 1X2 équilibré et « 99 % de 3 buts ou plus » ne peuvent pas venir
    de la même distribution de Poisson. L'ajustement doit le DIRE, pas
    rendre une matrice qui reproduit l'un en sacrifiant l'autre."""
    i = matrice_implicite(0.45, 0.28, 0.27, p_over=0.99)
    assert not i.fiable
    assert i.ecart_max > 0.01
    assert i.contraintes == ("1X2", "over/under")
    # Sans la contrainte fautive, le même 1X2 s'ajuste très bien : c'est le
    # repli que l'interface utilise.
    assert matrice_implicite(0.45, 0.28, 0.27).fiable


def test_rho_hors_bornes_est_refuse_clairement():
    with pytest.raises(ValueError, match="rho"):
        matrice_implicite(0.4, 0.3, 0.3, rho=0.3)
    with pytest.raises(ValueError, match="rho"):
        matrice_implicite(0.4, 0.3, 0.3, p_over=0.5, rho=-0.5)
    assert matrice_implicite(0.4, 0.3, 0.3, rho=buts_module.RHO_BORNE).fiable
