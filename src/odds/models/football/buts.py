"""Marchés de buts — matrice de score, probabilités et règlement.

Ce module répond à deux questions qui n'en font qu'une :

- « quelle probabilité le marché donne-t-il à *3 buts ou plus dans le
  match*, ou à *cette équipe marque 2 buts* ? » ;
- « ce pari est-il gagné, sachant que le match s'est terminé 2–1 ? »

Le point de conception central est qu'elles partagent **une seule
définition**. Chaque marché est un ``Marche`` porteur d'un prédicat sur le
score ``(x, y)``. La probabilité est la somme des cases de la matrice de
score qui satisfont ce prédicat ; le règlement est le même prédicat appliqué
au score réel. Il devient impossible qu'un marché soit coté selon une règle
et réglé selon une autre — c'est le genre d'écart qui ne se voit pas et qui
corrompt silencieusement un carnet de paris.

D'où viennent les probabilités
------------------------------

Le marché ne cote que le 1X2 et, quand on a de la chance, l'over/under 2,5.
« Telle équipe marque 1,5 but » n'est pas accessible : c'est un marché
additionnel, réservé aux offres payantes de The Odds API. Ces probabilités
sont donc **dérivées**, par une matrice de score ajustée pour reproduire les
prix que le marché affiche réellement :

    lambda, mu, rho  tels que  P(matrice) = probabilités de marché dévigées

Le 1X2 donne deux contraintes indépendantes, ce qui détermine exactement
(lambda, mu) à rho fixé. Une cote over/under fournit une troisième
contrainte et libère rho.

Cette distinction n'est pas cosmétique et l'interface doit la montrer : une
probabilité lue sur un prix et une probabilité dérivée d'une hypothèse de
Poisson corrigée ne valent pas la même chose. ``Implicite.ecart_max`` dit de
combien la matrice rate les prix qu'on lui a donnés à reproduire — quand ce
nombre n'est pas petit, la famille Poisson n'a pas su représenter ce match
et rien de ce qui en découle n'est fiable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from odds.models.football.dixon_coles import score_matrix

MAX_BUTS = 12

# rho par défaut, CALIBRÉ et non supposé.
#
# Premier réflexe, et il était faux : ajuster Dixon-Coles par pool sur
# l'historique et prendre la médiane des rho obtenus (-0,055). Mesuré ainsi,
# le rho décrit la dépendance des scores faibles DANS un modèle ajusté sur
# les buts. Ici il joue un autre rôle : il est le degré de liberté restant
# une fois le 1X2 imposé, et c'est la calibration des marchés de buts qui
# doit le fixer.
#
# La différence n'est pas théorique. À -0,05, la matrice sous-estime les
# buts de façon SYSTÉMATIQUE : -3,4 points sur « 3 buts ou plus », -4,5 sur
# BTTS (research/RESULTS.md R9). Le mécanisme est intelligible — à taux de
# buts réel, un produit de Poisson donne trop peu de nuls ; pour reproduire
# le P(nul) du marché, l'ajustement baisse les buts.
#
# Valeur retenue : balayage sur train + validation (20 000 matchs), minimum
# du Brier moyen sur quatre marchés de buts, puis VÉRIFICATION sur le jeu de
# test (20 000 autres, jamais vus par le balayage) :
#
#     rho      3 buts ou plus      BTTS
#     -0,05    biais -3,38 pts     -4,49 pts
#     -0,09    biais +0,26 pts     -1,04 pts     <- retenu, Brier meilleur
#                                                   sur les quatre marchés
#
# Reste un pis-aller : une valeur unique pour tous les championnats, alors
# que le rho ajusté varie de +0,04 (Portugal) à -0,15 (Grèce). Dès qu'une
# cote de totaux existe, rho est ajusté sur CE match et cette valeur ne sert
# plus — c'est ce qui justifie d'en collecter une.
RHO_DEFAUT = -0.09

# ---------------------------------------------------------------------------
# Jusqu'où la dérivation tient — MESURÉ (research/RESULTS.md R9)
# ---------------------------------------------------------------------------
# Reproduire le 1X2 ne suffit pas à rendre un total crédible. Le 1X2 ne dit
# rien du nombre de buts ; la famille de Poisson comble ce silence, et elle
# le comble d'autant plus mal que le match est déséquilibré. Pour donner
# 93 % à un favori et 5 % au nul, il lui faut un lambda énorme.
#
# Ordre de grandeur mesuré sur 43 576 matchs, en comparant P(3 buts ou plus)
# dérivée du 1X2 seul à la fréquence réellement observée :
#
#   force du favori   biais       buts impliqués vs réels
#   <= 60 %           < 1 pt      -0,01 à +0,04       <- fiable
#   60 - 70 %         +1,6 pt     +0,08
#   70 - 80 %         +2,8 pts    +0,22
#   80 - 85 %         +5,1 pts    +0,37
#   85 - 95 %         +3,8 à +4,1 +0,42 à +0,53
#   > 95 %            +10,8 pts   +1,53               <- inexploitable
#
# Le biais est toujours du même côté : la dérivation SURESTIME les buts des
# matchs déséquilibrés. On ne corrige pas — un rattrapage ajusté après coup
# sur la donnée qui l'a révélé ne serait pas une correction mais un
# surajustement. On BORNE l'usage, et on affiche l'incertitude. Le vrai
# remède est ailleurs : collecter la cote over/under, qui supprime le
# problème au lieu de le rattraper.

# borne haute de la force du favori -> (biais mesuré en points, qualificatif)
BIAIS_DERIVE = (
    (0.60, 1.0, "fiable"),
    (0.70, 1.6, "acceptable"),
    (0.80, 2.8, "acceptable"),
    (0.85, 5.1, "dégradé"),
    (0.95, 4.1, "dégradé"),
    (1.01, 10.8, "inexploitable"),
)


def fiabilite_derivee(p_max: float) -> tuple[float, str]:
    """Biais attendu d'une probabilité de buts dérivée du 1X2 seul.

    ``p_max`` est la probabilité de l'issue 1X2 la plus probable : c'est
    elle, et non la ligne de buts visée, qui commande la qualité de la
    dérivation.
    """
    for borne, biais, niveau in BIAIS_DERIVE:
        if p_max <= borne:
            return biais, niveau
    return BIAIS_DERIVE[-1][1], BIAIS_DERIVE[-1][2]


LIGNES_TOTAL = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
LIGNES_EQUIPE = (0.5, 1.5, 2.5, 3.5)


# ---------------------------------------------------------------------------
# Catalogue des marchés
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Marche:
    """Un marché = un code stable, un libellé, et UN prédicat sur le score.

    ``predicat`` doit accepter aussi bien deux entiers que deux tableaux
    numpy : il sert à sommer la matrice de score et à régler un pari réel.
    """
    code: str
    famille: str
    libelle: str
    predicat: Callable = field(compare=False, repr=False)

    def pour(self, dom: str = "Domicile", ext: str = "Extérieur") -> str:
        """Libellé avec les noms d'équipe du match."""
        return self.libelle.format(dom=dom, ext=ext)

    def gagne(self, buts_dom: int, buts_ext: int) -> bool:
        """Le pari est-il gagné avec ce score ? Règlement sans ambiguïté."""
        return bool(self.predicat(int(buts_dom), int(buts_ext)))


def _entier_au_dessus(ligne: float) -> int:
    """2.5 -> 3. Le nombre de buts qu'il faut atteindre pour passer la ligne."""
    return int(np.floor(ligne) + 1)


def _catalogue() -> dict[str, Marche]:
    m: dict[str, Marche] = {}

    def ajouter(code, famille, libelle, predicat):
        m[code] = Marche(code, famille, libelle, predicat)

    # --- 1X2, pour que le règlement passe par le même chemin que le reste --
    ajouter("1", "1X2", "{dom}", lambda x, y: x > y)
    ajouter("N", "1X2", "Match nul", lambda x, y: x == y)
    ajouter("2", "1X2", "{ext}", lambda x, y: x < y)

    # --- total du match ---------------------------------------------------
    # Libellés en nombre entier de buts : « 3 buts ou plus » se comprend
    # sans traduction, « plus de 2,5 buts » demande un instant de réflexion
    # à chaque lecture.
    for s in LIGNES_TOTAL:
        k = _entier_au_dessus(s)
        but = "but" if k == 1 else "buts"
        ajouter(f"total_over_{s}", "total", f"{k} {but} ou plus dans le match",
                lambda x, y, s=s: (x + y) > s)
        ajouter(f"total_under_{s}", "total", f"Moins de {k} {but} dans le match",
                lambda x, y, s=s: (x + y) < s)

    # --- total par équipe -------------------------------------------------
    for prefixe, cote, equipe in (("dom", "{dom}", 0), ("ext", "{ext}", 1)):
        for s in LIGNES_EQUIPE:
            k = _entier_au_dessus(s)
            but = "but" if k == 1 else "buts"
            ajouter(f"{prefixe}_over_{s}", f"total_{prefixe}",
                    f"{cote} marque {k} {but} ou plus",
                    (lambda x, y, s=s: x > s) if equipe == 0
                    else (lambda x, y, s=s: y > s))
            ajouter(f"{prefixe}_under_{s}", f"total_{prefixe}",
                    f"{cote} marque moins de {k} {but}",
                    (lambda x, y, s=s: x < s) if equipe == 0
                    else (lambda x, y, s=s: y < s))

    # --- les deux équipes marquent ----------------------------------------
    ajouter("btts_oui", "btts", "Les deux équipes marquent",
            lambda x, y: (x >= 1) & (y >= 1))
    ajouter("btts_non", "btts", "Au moins une équipe ne marque pas",
            lambda x, y: (x == 0) | (y == 0))

    return m


MARCHES: dict[str, Marche] = _catalogue()

FAMILLES = ("1X2", "total", "total_dom", "total_ext", "btts")


def marche(code: str) -> Marche:
    try:
        return MARCHES[code]
    except KeyError:
        raise ValueError(
            f"marché inconnu : {code!r}. Codes connus : "
            f"{', '.join(sorted(MARCHES))}") from None


def regler(code: str, buts_dom: int, buts_ext: int) -> bool:
    """Un pari sur ``code`` est-il gagné par le score ``buts_dom-buts_ext`` ?

    C'est la fonction que le carnet appelle : on saisit le score une fois et
    tous les paris du match se règlent, quel que soit leur marché.
    """
    return marche(code).gagne(buts_dom, buts_ext)


# ---------------------------------------------------------------------------
# Lecture d'une matrice de score
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _grille(n: int) -> tuple[np.ndarray, np.ndarray]:
    k = np.arange(n + 1)
    return np.meshgrid(k, k, indexing="ij")


def probabilite(matrice: np.ndarray, code: str) -> float:
    """Probabilité d'un marché, somme des cases qui satisfont son prédicat."""
    x, y = _grille(matrice.shape[0] - 1)
    return float(matrice[marche(code).predicat(x, y)].sum())


def marches_buts(matrice: np.ndarray, familles=("total", "total_dom",
                                                "total_ext", "btts"),
                 dom: str = "Domicile", ext: str = "Extérieur") -> pd.DataFrame:
    """Toute la famille de marchés lisible sur une matrice de score.

    Colonnes : ``code``, ``famille``, ``libelle``, ``p``, ``cote_juste``.
    La cote juste est 1/p : c'est le prix sans marge, celui auquel miser a
    une espérance nulle. Le comparer au prix affiché est tout l'intérêt.
    """
    x, y = _grille(matrice.shape[0] - 1)
    lignes = []
    for m in MARCHES.values():
        if m.famille not in familles:
            continue
        p = float(matrice[m.predicat(x, y)].sum())
        lignes.append({"code": m.code, "famille": m.famille,
                       "libelle": m.pour(dom, ext), "p": p,
                       "cote_juste": (1.0 / p) if p > 0 else np.inf})
    return pd.DataFrame(lignes)


# ---------------------------------------------------------------------------
# Matrice de score implicite au marché
# ---------------------------------------------------------------------------

@dataclass
class Implicite:
    """Résultat de l'ajustement, avec de quoi juger s'il vaut quelque chose."""
    lam: float                  # buts attendus, domicile
    mu: float                   # buts attendus, extérieur
    rho: float
    matrice: np.ndarray
    ecart_max: float            # plus grand écart aux prix à reproduire
    contraintes: tuple[str, ...]
    converge: bool

    @property
    def fiable(self) -> bool:
        """La matrice reproduit-elle les prix de marché à 0,5 point près ?

        Seuil délibérément lâche : au-delà, ce n'est plus un défaut de
        solveur mais un match que la famille Poisson ne sait pas
        représenter, et tout ce qu'on en dérive est à jeter.
        """
        return self.converge and self.ecart_max < 0.005

    @property
    def buts_attendus(self) -> float:
        return self.lam + self.mu


def matrice_implicite(p_dom: float, p_nul: float, p_ext: float,
                      p_over: float | None = None, ligne: float = 2.5,
                      rho: float = RHO_DEFAUT,
                      max_buts: int = MAX_BUTS) -> Implicite:
    """Matrice de score qui reproduit les probabilités de marché fournies.

    ``p_dom``, ``p_nul``, ``p_ext`` sont les probabilités 1X2 **marge
    retirée** (``odds.market.devig``). ``p_over``, si fourni, est la
    probabilité dévigée du *plus de ``ligne`` buts* ; elle ajoute une
    contrainte et libère ``rho`` au lieu de le supposer.

    Le 1X2 n'apporte que deux contraintes indépendantes (les trois
    probabilités somment à 1) : sans over/under, le système à deux inconnues
    est exactement déterminé, et ``rho`` reste à sa valeur par défaut.
    """
    p = np.array([p_dom, p_nul, p_ext], dtype=float)
    if np.any(p < 0) or np.any(p > 1):
        raise ValueError(f"probabilités 1X2 hors [0, 1] : {p}")
    somme = p.sum()
    if not np.isfinite(somme) or abs(somme - 1.0) > 0.02:
        raise ValueError(
            f"les probabilités 1X2 doivent être dévigées et sommer à 1 "
            f"(reçu {somme:.4f}). Voir odds.market.devig.")
    p = p / somme
    if p_over is not None and not 0.0 < p_over < 1.0:
        raise ValueError(f"p_over hors ]0, 1[ : {p_over!r}")

    ajuste_rho = p_over is not None
    contraintes = ("1X2",) + (("over/under",) if ajuste_rho else ())

    def matrice_de(theta):
        lam, mu = np.exp(theta[0]), np.exp(theta[1])
        r = float(np.clip(theta[2], -0.2, 0.2)) if ajuste_rho else rho
        return score_matrix(lam, mu, r, max_buts), lam, mu, r

    x, y = _grille(max_buts)
    dom_gagne, nul = x > y, x == y

    def residus(theta):
        m, *_ = matrice_de(theta)
        e = [m[dom_gagne].sum() - p[0], m[nul].sum() - p[1]]
        if ajuste_rho:
            e.append(m[(x + y) > ligne].sum() - p_over)
        return e

    # Départ : 2,6 buts au total (moyenne européenne), répartis selon le sens
    # du 1X2. Un départ grossier suffit, le système est petit et lisse.
    biais = float(np.clip(p[0] - p[2], -0.6, 0.6))
    theta0 = [np.log(1.35 * (1.0 + biais)), np.log(1.25 * (1.0 - biais))]
    bornes = ([np.log(0.02)] * 2, [np.log(9.0)] * 2)
    if ajuste_rho:
        theta0.append(rho)
        bornes = (bornes[0] + [-0.2], bornes[1] + [0.2])

    sol = least_squares(residus, theta0, bounds=bornes, xtol=1e-12, ftol=1e-12)
    m, lam, mu, r = matrice_de(sol.x)
    return Implicite(lam=lam, mu=mu, rho=r, matrice=m,
                     ecart_max=float(np.max(np.abs(sol.fun))),
                     contraintes=contraintes, converge=bool(sol.success))
