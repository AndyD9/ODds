"""La version vectorisée doit être indiscernable de la version scalaire.

Sans ce test, une divergence entre les deux implémentations produirait des
résultats de backtest non reproductibles par le code de référence.
"""

import numpy as np
import pytest

from odds.market.devig import METHODS, devig, devig_matrix

ALL_METHODS = sorted(METHODS)
RNG = np.random.default_rng(20260918)


def _livres_aleatoires(n, k, marge_min=0.94, marge_max=1.30):
    """Livres réalistes : probabilités Dirichlet, marge tirée uniformément.

    Inclut volontairement des livres sous-ronds (marge < 1), qui surviennent
    dès qu'on retient le meilleur prix entre bookmakers.

    Les livres impossibles sont écartés plutôt que déformés : une probabilité
    implicite >= 1 correspondrait à une cote <= 1.0, qui n'existe pas. On
    sur-génère puis on filtre, pour garder un tirage non biaisé.
    """
    garde = []
    while sum(len(b) for b in garde) < n:
        p = RNG.dirichlet(np.ones(k) * 1.2, size=4 * n)
        marge = RNG.uniform(marge_min, marge_max, size=(4 * n, 1))
        implied = p * marge
        valide = implied.max(axis=1) < 0.97
        garde.append(implied[valide])
    implied = np.vstack(garde)[:n]
    return 1.0 / implied


@pytest.mark.parametrize("method", ALL_METHODS)
@pytest.mark.parametrize("k", [2, 3, 8])
def test_vectorise_egale_scalaire(method, k):
    odds = _livres_aleatoires(300, k)
    attendu = np.vstack([devig(row, method) for row in odds])
    obtenu = devig_matrix(odds, method)
    assert obtenu == pytest.approx(attendu, abs=1e-9)


@pytest.mark.parametrize("method", ALL_METHODS)
def test_vectorise_somme_a_un(method):
    p = devig_matrix(_livres_aleatoires(500, 3), method)
    assert p.sum(axis=1) == pytest.approx(np.ones(500), abs=1e-12)
    assert np.all(p > 0.0)


@pytest.mark.parametrize("method", ["shin", "power", "odds_ratio"])
def test_direction_du_biais_sur_livres_aleatoires(method):
    """La propriété directionnelle doit tenir sur TOUS les livres avec marge,
    pas seulement sur les exemples choisis à la main."""
    odds = _livres_aleatoires(2000, 3, marge_min=1.02, marge_max=1.25)
    p_prop = devig_matrix(odds, "proportional")
    p_meth = devig_matrix(odds, method)
    lignes = np.arange(len(odds))
    outsider = p_prop.argmin(axis=1)
    favori = p_prop.argmax(axis=1)
    assert np.all(p_meth[lignes, outsider] < p_prop[lignes, outsider])
    assert np.all(p_meth[lignes, favori] > p_prop[lignes, favori])


def test_formes_invalides_rejetees():
    with pytest.raises(ValueError, match="forme"):
        devig_matrix(np.array([2.0, 3.0, 4.0]), "shin")
    with pytest.raises(ValueError, match="cotes invalides"):
        devig_matrix(np.array([[2.0, np.nan, 4.0]]), "shin")
    with pytest.raises(ValueError, match="cotes invalides"):
        devig_matrix(np.array([[2.0, 1.0, 4.0]]), "shin")
