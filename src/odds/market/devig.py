"""Retrait de la marge bookmaker (dévig).

Quatre méthodes, toutes ramenant un vecteur de cotes à une distribution de
probabilités sommant à 1 :

- ``proportional`` : p_i = pi_i / somme(pi)        [biaisée, cf. §9.1 du PLAN]
- ``power``        : p_i = pi_i ** k
- ``shin``         : modèle de Shin (1993), insider trading
- ``odds_ratio``   : méthode du rapport de cotes (Cheung)

``shin`` est la méthode par défaut du projet (décision actée, PLAN §0.2).
Les autres sont conservées comme comparateurs : le choix par marché est une
décision *mesurée*, pas supposée (PLAN §9.2).

Convention : pi_i = 1 / cote_i (probabilité implicite brute),
             Pi   = somme(pi_i) = overround (booksum).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

__all__ = [
    "implied_raw",
    "overround",
    "devig",
    "devig_proportional",
    "devig_power",
    "devig_shin",
    "devig_odds_ratio",
    "shin_z",
    "METHODS",
]

_TOL = 1e-12


def implied_raw(odds: np.ndarray) -> np.ndarray:
    """Probabilités implicites brutes, 1 / cote."""
    odds = np.asarray(odds, dtype=float)
    if np.any(odds <= 1.0):
        raise ValueError("cote <= 1.0 : impossible (%s)" % odds[odds <= 1.0])
    return 1.0 / odds


def overround(odds: np.ndarray) -> float:
    """Booksum. > 1 pour un livre avec marge, 1.0 pour un livre juste."""
    return float(implied_raw(odds).sum())


# --------------------------------------------------------------------------
# Méthodes
# --------------------------------------------------------------------------

def devig_proportional(odds: np.ndarray) -> np.ndarray:
    """Normalisation proportionnelle.

    ATTENTION : biaisée de façon directionnelle. La marge n'est pas répartie
    uniformément entre les issues — elle est concentrée sur les outsiders.
    Cette méthode surestime donc la probabilité des outsiders et fabrique de
    faux signaux sur les cotes élevées. Conservée comme référence de
    comparaison uniquement (PLAN §9.1).
    """
    pi = implied_raw(odds)
    return pi / pi.sum()


def devig_power(odds: np.ndarray) -> np.ndarray:
    """Power method : p_i = pi_i ** k, avec k tel que somme(p) = 1.

    k > 1 pour un livre avec marge, k < 1 pour un livre sous-rond. Le second
    cas n'est pas théorique : il survient dès qu'on retient le meilleur prix
    entre plusieurs bookmakers, ce que fait tout moteur de prix réel.
    """
    pi = implied_raw(odds)
    if abs(pi.sum() - 1.0) < _TOL:
        return pi.copy()

    def f(k: float) -> float:
        return float(np.sum(pi ** k) - 1.0)

    # f est strictement décroissante sur (0, inf) :
    #   f(0+) = n - 1 > 0    et    f(+inf) = -1 < 0
    k = brentq(f, 1e-9, 100.0, xtol=1e-14, rtol=1e-15)
    p = pi ** k
    return p / p.sum()


def _shin_probs(pi: np.ndarray, z: float) -> np.ndarray:
    """Probabilités de Shin pour une valeur de z donnée."""
    booksum = pi.sum()
    if z <= 0.0:
        return pi / np.sqrt(booksum)
    if z >= 1.0:
        return pi ** 2 / booksum
    inner = z * z + 4.0 * (1.0 - z) * pi * pi / booksum
    return (np.sqrt(inner) - z) / (2.0 * (1.0 - z))


def shin_z(odds: np.ndarray) -> float:
    """Proportion d'insider trading z implicite dans un vecteur de cotes.

    Interprétable : c'est la part du volume que le book attribue à des
    parieurs informés. Valeur typique 0.01-0.05 sur un 1X2 de grand
    championnat, plus élevée sur les marchés minces.
    """
    pi = implied_raw(odds)
    if abs(pi.sum() - 1.0) < _TOL:
        return 0.0

    def f(z: float) -> float:
        return float(_shin_probs(pi, z).sum() - 1.0)

    lo, hi = 1e-12, 1.0 - 1e-12
    f_lo, f_hi = f(lo), f(hi)
    if f_lo < 0.0:          # livre déjà sous-rond, rien à retirer
        return 0.0
    if f_hi > 0.0:          # marge extrême, hors du domaine du modèle
        return hi
    return brentq(f, lo, hi, xtol=1e-14, rtol=1e-15)


def devig_shin(odds: np.ndarray) -> np.ndarray:
    """Modèle de Shin (1993). Méthode par défaut du projet.

    Suppose que la marge observée résulte de la protection du bookmaker
    contre une proportion z de parieurs informés. Retire mécaniquement plus
    de marge sur les outsiders que sur les favoris, ce qui corrige le
    favourite-longshot bias au lieu de le laisser contaminer le signal.
    """
    pi = implied_raw(odds)
    p = _shin_probs(pi, shin_z(odds))
    return p / p.sum()


def devig_odds_ratio(odds: np.ndarray) -> np.ndarray:
    """Méthode du rapport de cotes (Cheung).

    Suppose un rapport de cotes constant entre probabilité juste et
    probabilité affichée : OR = [p/(1-p)] / [pi/(1-pi)].
    """
    pi = implied_raw(odds)
    if abs(pi.sum() - 1.0) < _TOL:
        return pi.copy()

    def probs(c: float) -> np.ndarray:
        return c * pi / (1.0 - pi + c * pi)

    def f(c: float) -> float:
        return float(probs(c).sum() - 1.0)

    # f est strictement croissante en c :
    #   f(0+) = -1 < 0    et    f(+inf) = n - 1 > 0
    # c < 1 pour un livre avec marge, c > 1 pour un livre sous-rond.
    c = brentq(f, 1e-12, 1e6, xtol=1e-14, rtol=1e-15)
    p = probs(c)
    return p / p.sum()


METHODS = {
    "proportional": devig_proportional,
    "power": devig_power,
    "shin": devig_shin,
    "odds_ratio": devig_odds_ratio,
}


def devig(odds: np.ndarray, method: str = "shin") -> np.ndarray:
    """Point d'entrée unique. ``method`` dans METHODS."""
    try:
        fn = METHODS[method]
    except KeyError:
        raise ValueError(
            "méthode inconnue %r ; attendu %s" % (method, sorted(METHODS))
        ) from None
    return fn(np.asarray(odds, dtype=float))


# --------------------------------------------------------------------------
# Versions vectorisées (n marchés x k issues)
# --------------------------------------------------------------------------
# Bisection vectorisée : robuste, sans dépendance à brentq, et assez rapide
# pour appliquer le dévig à ~10^5 marchés à chaque itération du backtest.

_BISECT_ITERS = 80


def _bisect_vec(f, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Bisection vectorisée sur f croissante ou décroissante, ligne à ligne."""
    lo, hi = np.asarray(lo, float).copy(), np.asarray(hi, float).copy()
    croissante = f(hi) > f(lo)
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        positif = f(mid) > 0.0
        va_en_haut = positif == croissante
        hi = np.where(va_en_haut, mid, hi)
        lo = np.where(va_en_haut, lo, mid)
    return 0.5 * (lo + hi)


def devig_matrix(odds: np.ndarray, method: str = "shin") -> np.ndarray:
    """Dévig vectorisé. ``odds`` de forme (n, k). Renvoie (n, k)."""
    odds = np.asarray(odds, dtype=float)
    if odds.ndim != 2:
        raise ValueError("odds doit être de forme (n, k), reçu %r" % (odds.shape,))
    if np.any(~np.isfinite(odds)) or np.any(odds <= 1.0):
        raise ValueError("cotes invalides (NaN, inf ou <= 1.0) dans devig_matrix")

    pi = 1.0 / odds
    booksum = pi.sum(axis=1, keepdims=True)

    if method == "proportional":
        p = pi / booksum

    elif method == "power":
        def f(k):
            return np.sum(pi ** k[:, None], axis=1) - 1.0
        n = odds.shape[0]
        k = _bisect_vec(f, np.full(n, 1e-9), np.full(n, 60.0))
        p = pi ** k[:, None]

    elif method == "shin":
        def f(z):
            zz = z[:, None]
            inner = zz * zz + 4.0 * (1.0 - zz) * pi * pi / booksum
            return np.sum((np.sqrt(inner) - zz) / (2.0 * (1.0 - zz)), axis=1) - 1.0
        n = odds.shape[0]
        z = _bisect_vec(f, np.full(n, 1e-12), np.full(n, 1.0 - 1e-12))
        zz = z[:, None]
        inner = zz * zz + 4.0 * (1.0 - zz) * pi * pi / booksum
        p = (np.sqrt(inner) - zz) / (2.0 * (1.0 - zz))

    elif method == "odds_ratio":
        def f(c):
            cc = c[:, None]
            return np.sum(cc * pi / (1.0 - pi + cc * pi), axis=1) - 1.0
        n = odds.shape[0]
        c = _bisect_vec(f, np.full(n, 1e-12), np.full(n, 1e6))
        cc = c[:, None]
        p = cc * pi / (1.0 - pi + cc * pi)

    else:
        raise ValueError("méthode inconnue %r ; attendu %s" % (method, sorted(METHODS)))

    return p / p.sum(axis=1, keepdims=True)


__all__.append("devig_matrix")
