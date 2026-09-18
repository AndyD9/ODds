"""Tests du module de dévig.

Ces tests ne vérifient pas seulement que le code tourne : ils verrouillent les
propriétés mathématiques sur lesquelles repose tout le reste du projet. En
particulier la direction du biais de la normalisation proportionnelle (§9.1),
qui est la raison pour laquelle Shin est la méthode par défaut.
"""

import numpy as np
import pytest

from odds.market.devig import (
    METHODS,
    devig,
    devig_proportional,
    devig_shin,
    implied_raw,
    overround,
    shin_z,
)

# Livres AVEC MARGE (booksum > 1). Cas nominal.
BOOKS = [
    np.array([1.80, 3.60, 4.80]),        # 1X2 équilibré
    np.array([1.25, 6.00, 12.00]),       # gros favori
    np.array([4.50, 3.70, 1.85]),        # favori extérieur
    np.array([2.60, 3.30, 2.70]),        # serré
    np.array([1.91, 1.91]),              # 2 issues, even money
    np.array([1.44, 2.75]),              # 2 issues, déséquilibré
    np.array([4.00, 4.80, 5.75, 7.25, 8.75, 9.50, 11.00, 14.00]),  # 8 issues
]

# Livres SOUS-RONDS (booksum < 1). Surviennent dès qu'on retient le meilleur
# prix entre bookmakers — cas nominal d'un moteur de prix réel, pas un cas
# limite exotique.
SUB_ROUND_BOOKS = [
    np.array([2.10, 3.80, 4.60]),
    np.array([2.05, 2.05]),
    np.array([9.0, 7.5, 8.0, 11.0, 13.0, 17.0, 24.0, 30.0]),
]

MARKET_BOOKS = [b for b in BOOKS if len(b) >= 3]

ALL_METHODS = sorted(METHODS)


def test_les_livres_de_test_ont_bien_une_marge():
    """Garde-fou : un livre de test sous-rond invaliderait silencieusement
    les tests de direction du biais."""
    for b in BOOKS:
        assert overround(b) > 1.0, b
    for b in SUB_ROUND_BOOKS:
        assert overround(b) < 1.0, b


@pytest.mark.parametrize("odds", BOOKS)
@pytest.mark.parametrize("method", ALL_METHODS)
def test_somme_a_un(odds, method):
    p = devig(odds, method)
    assert p.sum() == pytest.approx(1.0, abs=1e-12)
    assert np.all(p > 0.0)
    assert np.all(p < 1.0)


@pytest.mark.parametrize("method", ALL_METHODS)
def test_livre_juste_est_identite(method):
    """Sur un livre sans marge, toute méthode doit être l'identité.

    Si une méthode déforme un livre déjà juste, elle injecte un biais qui
    n'existe pas dans les données.
    """
    p_vrai = np.array([0.55, 0.27, 0.18])
    odds = 1.0 / p_vrai
    assert overround(odds) == pytest.approx(1.0, abs=1e-12)
    assert devig(odds, method) == pytest.approx(p_vrai, abs=1e-9)


@pytest.mark.parametrize("odds", BOOKS)
@pytest.mark.parametrize("method", ALL_METHODS)
def test_ordre_preserve(odds, method):
    """Le classement des issues ne doit jamais changer."""
    assert np.all(np.argsort(devig(odds, method)) == np.argsort(implied_raw(odds)))


@pytest.mark.parametrize("odds", MARKET_BOOKS)
@pytest.mark.parametrize("method", ["shin", "power", "odds_ratio"])
def test_direction_du_biais_proportionnel(odds, method):
    """LE test central du module (PLAN §9.1).

    La marge est concentrée sur les outsiders. Toute méthode correcte doit
    donc, par rapport à la normalisation proportionnelle :
      - donner MOINS de probabilité à l'outsider,
      - donner PLUS de probabilité au favori.

    Si ce test échoue, le moteur d'edge fabriquera de faux signaux sur les
    cotes élevées et le backtest mesurera un artefact de sa propre dévig.
    """
    p_prop = devig_proportional(odds)
    p_meth = devig(odds, method)
    favori = int(np.argmax(p_prop))
    outsider = int(np.argmin(p_prop))

    assert p_meth[outsider] < p_prop[outsider], "outsider non corrigé à la baisse"
    assert p_meth[favori] > p_prop[favori], "favori non corrigé à la hausse"


def _ecart_relatif_outsider(p_vrai, marge):
    """Erreur relative que la normalisation proportionnelle commet sur
    l'outsider, par rapport à Shin, pour un livre de forme et de marge
    données."""
    p_vrai = np.asarray(p_vrai, dtype=float)
    p_vrai = p_vrai / p_vrai.sum()
    odds = 1.0 / (p_vrai * marge)
    p_prop = devig_proportional(odds)
    p_shin = devig_shin(odds)
    i = int(np.argmin(p_prop))
    return abs(p_shin[i] - p_prop[i]) / p_prop[i]


def test_livre_parfaitement_equilibre_sans_biais():
    """Sur un livre symétrique, proportionnelle et Shin coïncident.

    Il n'y a alors rien à redistribuer asymétriquement : c'est le seul cas où
    la normalisation proportionnelle est exacte.
    """
    for marge in (1.02, 1.06, 1.15):
        assert _ecart_relatif_outsider([0.5, 0.5], marge) == pytest.approx(0.0, abs=1e-9)
        assert _ecart_relatif_outsider([1 / 3] * 3, marge) == pytest.approx(0.0, abs=1e-9)


def test_biais_croit_avec_la_marge():
    """Premier moteur du biais : la marge, de façon quasi linéaire."""
    p = [0.55, 0.27, 0.18]
    ecarts = [_ecart_relatif_outsider(p, m) for m in (1.02, 1.04, 1.06, 1.10, 1.15, 1.25)]
    assert all(a < b for a, b in zip(ecarts, ecarts[1:]))


def test_biais_croit_avec_lasymetrie_du_livre():
    """Second moteur : l'écart entre le favori et l'outsider.

    À marge égale et nombre d'issues égal, un livre à gros favori est
    beaucoup plus biaisé qu'un livre serré.
    """
    serre = _ecart_relatif_outsider([0.40, 0.33, 0.27], 1.06)
    typique = _ecart_relatif_outsider([0.55, 0.27, 0.18], 1.06)
    gros_favori = _ecart_relatif_outsider([0.78, 0.14, 0.08], 1.06)
    assert serre < typique < gros_favori


def test_le_nombre_dissues_nest_pas_le_moteur():
    """Documente une intuition FAUSSE, écartée par la mesure.

    On pourrait croire que le biais croît avec le nombre d'issues. C'est faux :
    un marché à 8 issues plat est MOINS biaisé qu'un 1X2 à gros favori. Ce qui
    compte est la dispersion du livre, pas sa cardinalité.
    """
    huit_plat = _ecart_relatif_outsider(
        [0.22, 0.18, 0.15, 0.12, 0.10, 0.09, 0.08, 0.06], 1.06
    )
    trois_gros_favori = _ecart_relatif_outsider([0.78, 0.14, 0.08], 1.06)
    assert huit_plat < trois_gros_favori


def test_ampleur_du_faux_edge_en_points():
    """Chiffre l'enjeu concret : le faux edge que produirait la proportionnelle.

    Sur un 1X2 à 8 % de marge, l'artefact vaut ~0,9 point de probabilité sur
    l'outsider. À comparer aux edges réels recherchés, de l'ordre de 1 à 3
    points : l'artefact représenterait une fraction majeure du signal.
    """
    p = np.array([0.55, 0.27, 0.18])
    odds = 1.0 / (p * 1.08)
    p_prop = devig_proportional(odds)
    p_shin = devig_shin(odds)
    i = int(np.argmin(p_prop))
    faux_edge_points = p_prop[i] - p_shin[i]
    assert 0.005 < faux_edge_points < 0.015
    # et il est toujours dans le sens qui SURESTIME l'outsider
    assert faux_edge_points > 0.0


@pytest.mark.parametrize("z_vrai", [0.005, 0.02, 0.05, 0.10])
@pytest.mark.parametrize(
    "p_vrai",
    [
        np.array([0.55, 0.27, 0.18]),
        np.array([0.75, 0.15, 0.10]),
        np.array([0.34, 0.33, 0.33]),
    ],
)
def test_shin_aller_retour(z_vrai, p_vrai):
    """Génère des cotes depuis le modèle de Shin, puis les inverse.

    Modèle direct :
        Pi    = (somme_i sqrt(p_i ((1-z) p_i + z)))**2
        pi_i  = sqrt(Pi * p_i * ((1-z) p_i + z))
    """
    g = p_vrai * ((1.0 - z_vrai) * p_vrai + z_vrai)
    booksum = np.sum(np.sqrt(g)) ** 2
    pi = np.sqrt(booksum * g)
    odds = 1.0 / pi

    assert overround(odds) == pytest.approx(booksum, rel=1e-12)
    assert shin_z(odds) == pytest.approx(z_vrai, abs=1e-8)
    assert devig_shin(odds) == pytest.approx(p_vrai, abs=1e-9)


@pytest.mark.parametrize("odds", BOOKS)
def test_shin_z_dans_domaine(odds):
    z = shin_z(odds)
    assert 0.0 <= z < 1.0


def test_shin_z_croit_avec_la_marge():
    """Plus la marge est forte, plus z estimé est élevé."""
    p = np.array([0.55, 0.27, 0.18])
    zs = [shin_z(1.0 / (p * m)) for m in (1.02, 1.05, 1.10, 1.20)]
    assert zs == sorted(zs)
    assert all(a < b for a, b in zip(zs, zs[1:]))


@pytest.mark.parametrize("odds", SUB_ROUND_BOOKS)
@pytest.mark.parametrize("method", ALL_METHODS)
def test_livre_sous_rond_ne_casse_pas(odds, method):
    """Un livre sous-rond doit produire une distribution valide, pas une
    exception. C'est le cas nominal quand on retient le meilleur prix de
    marché, donc il ne peut pas lever."""
    assert overround(odds) < 1.0
    p = devig(odds, method)
    assert p.sum() == pytest.approx(1.0, abs=1e-12)
    assert np.all(p > 0.0)
    assert np.all(np.argsort(p) == np.argsort(implied_raw(odds)))


def test_cotes_invalides_rejetees():
    with pytest.raises(ValueError, match="cote"):
        implied_raw(np.array([1.80, 1.00, 4.80]))
    with pytest.raises(ValueError, match="cote"):
        implied_raw(np.array([1.80, -2.0, 4.80]))


def test_methode_inconnue_rejetee():
    with pytest.raises(ValueError, match="méthode inconnue"):
        devig(np.array([2.0, 2.0]), "normalisation_magique")
