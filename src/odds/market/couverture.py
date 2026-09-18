"""Couverture — répartir une mise sur plusieurs issues d'un même marché.

« Couvrir », c'est miser sur plusieurs issues exclusives d'un même marché
pour réduire la perte quand celle qu'on visait ne sort pas. Ce module dit
exactement ce que ça coûte et ce que ça rapporte, issue par issue, et il ne
laisse rien croire de plus : **aucune répartition ne crée d'espérance.**
L'espérance d'une couverture est la somme des espérances de ses jambes.
Couvrir une issue sans valeur dilue l'avantage qu'on avait sur les autres
et paie la marge du bookmaker une fois de plus.

Deux façons de répartir, et une seule qui se justifie :

- ``couvrir`` — répartition à **retour égal** (« dutching ») : chaque issue
  couverte rend la même somme si elle sort. C'est la lecture de « on fait
  comment ? » et c'est la couverture que tout le monde calcule. Elle est
  fournie pour être comprise, avec son espérance affichée en face.
- ``kelly_simultane`` — répartition **en proportion de l'avantage** : la
  solution de Kelly sur des issues exclusives (Smoczynski & Tomkins, 2010).
  Elle ne couvre que les issues dont le prix bat encore le marché une fois
  les autres retenues, et ne couvre rien quand aucune n'en a. C'est la seule
  répartition que le moteur de mise propose ; pour une seule issue, elle
  redonne exactement ``paper.kelly``.

Les issues couvrables sont celles du catalogue de ``models.football.buts``,
regroupées en **partitions** : des ensembles d'issues exclusives qui
recouvrent tous les scores. Le 1X2 en est une, chaque ligne over/under en
est une autre, BTTS aussi. On ne couvre qu'à l'intérieur d'une partition —
« Monaco » et « moins de 3 buts » ne s'excluent pas, leur couverture n'a pas
de retour garanti à calculer.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from odds.models.football import buts

# ---------------------------------------------------------------------------
# Partitions du catalogue
# ---------------------------------------------------------------------------


def _partitions() -> dict[str, tuple[str, ...]]:
    p: dict[str, tuple[str, ...]] = {"1X2": ("1", "N", "2")}
    for s in buts.LIGNES_TOTAL:
        p[f"total_{s}"] = (f"total_over_{s}", f"total_under_{s}")
    for prefixe in ("dom", "ext"):
        for s in buts.LIGNES_EQUIPE:
            p[f"{prefixe}_{s}"] = (f"{prefixe}_over_{s}", f"{prefixe}_under_{s}")
    p["btts"] = ("btts_oui", "btts_non")
    return p


PARTITIONS: dict[str, tuple[str, ...]] = _partitions()

_PARTITION_DE = {code: nom for nom, codes in PARTITIONS.items() for code in codes}


def partition_de(code: str) -> str:
    """Nom de la partition qui contient ce code de pari."""
    try:
        return _PARTITION_DE[code]
    except KeyError:
        raise ValueError(f"marché inconnu ou non couvrable : {code!r}") from None


def libelle_partition(nom: str, dom: str = "Domicile", ext: str = "Extérieur") -> str:
    """Libellé lisible d'une partition, noms d'équipe compris."""
    if nom == "1X2":
        return "Résultat du match (1 N 2)"
    if nom == "btts":
        return "Les deux équipes marquent"
    famille, _, ligne = nom.partition("_")
    k = buts._entier_au_dessus(float(ligne))
    but = "but" if k == 1 else "buts"
    if famille == "total":
        return f"Total du match : {k} {but} ou plus / moins"
    equipe = dom if famille == "dom" else ext
    return f"{equipe} : {k} {but} ou plus / moins"


def est_partition(codes) -> bool:
    """Ces codes forment-ils exactement une partition du catalogue ?"""
    return any(set(codes) == set(p) for p in PARTITIONS.values())


# ---------------------------------------------------------------------------
# Une couverture : des mises, et ce qu'elles donnent selon l'issue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Couverture:
    """Des mises sur un sous-ensemble d'une partition, et leurs conséquences.

    ``partition`` liste toutes les issues du marché ; ``mises`` ne porte que
    celles qu'on couvre. ``probas`` et ``cotes`` sont indexées par code.
    Tout le reste se déduit, et se lit issue par issue : ``profit(code)``
    est ce qu'on gagne ou perd **si cette issue survient**, mises comprises.
    """
    partition: tuple[str, ...]
    probas: dict
    cotes: dict
    mises: dict

    def __post_init__(self):
        if not self.mises:
            raise ValueError("une couverture porte au moins une mise")
        inconnus = set(self.mises) - set(self.partition)
        if inconnus:
            raise ValueError(f"issues hors de la partition : {sorted(inconnus)}")
        for code, mise in self.mises.items():
            if mise < 0:
                raise ValueError(f"mise négative sur {code!r} : {mise!r}")
            if self.cotes.get(code, 0.0) <= 1.0:
                raise ValueError(f"cote invalide sur {code!r} : {self.cotes.get(code)!r}")

    # --- lecture -----------------------------------------------------------

    @property
    def codes(self) -> tuple[str, ...]:
        """Issues couvertes, dans l'ordre de la partition."""
        return tuple(c for c in self.partition if c in self.mises)

    @property
    def total(self) -> float:
        return float(sum(self.mises.values()))

    def retour(self, code: str) -> float:
        """Ce que le bookmaker rend si ``code`` survient."""
        return float(self.mises.get(code, 0.0) * self.cotes.get(code, 0.0))

    def profit(self, code: str) -> float:
        return self.retour(code) - self.total

    @property
    def profits(self) -> dict:
        return {c: self.profit(c) for c in self.partition}

    @property
    def complete(self) -> bool:
        """Toutes les issues sont couvertes : le résultat ne dépend plus du match."""
        return set(self.codes) == set(self.partition)

    @property
    def p_couverte(self) -> float:
        return float(sum(self.probas[c] for c in self.codes))

    @property
    def esperance(self) -> float:
        """Espérance de profit, en euros : somme des p × profit sur la partition."""
        return float(sum(self.probas[c] * self.profit(c) for c in self.partition))

    @property
    def esperance_relative(self) -> float:
        """Espérance rapportée à la mise totale. Comparable à ``p × cote − 1``."""
        return self.esperance / self.total if self.total > 0 else float("nan")

    @property
    def pire(self) -> float:
        """Le pire profit possible — négatif sauf sur-arbitrage."""
        return float(min(self.profits.values()))

    @property
    def meilleur(self) -> float:
        return float(max(self.profits.values()))

    @property
    def booksum(self) -> float:
        """Somme des inverses des cotes couvertes. < 1 = les prix laissent un gain sûr."""
        return float(sum(1.0 / self.cotes[c] for c in self.codes))

    @property
    def retour_egal(self) -> bool:
        """Les issues couvertes rendent-elles toutes la même somme ?"""
        r = [self.retour(c) for c in self.codes]
        return bool(np.allclose(r, r[0], rtol=1e-9, atol=1e-6))

    @property
    def cote_synthetique(self) -> float:
        """Cote du pari équivalent « une des issues couvertes sort ».

        N'a de sens qu'à retour égal : c'est alors ``retour / mise totale``,
        la cote à laquelle on a acheté la réunion des issues couvertes.
        """
        if not self.retour_egal:
            return float("nan")
        return self.retour(self.codes[0]) / self.total if self.total > 0 else float("nan")

    def tableau(self, libelles: dict | None = None) -> pd.DataFrame:
        """Une ligne par issue de la partition : mise, retour, profit, probabilité."""
        libelles = libelles or {}
        return pd.DataFrame({
            "code": list(self.partition),
            "issue": [libelles.get(c, c) for c in self.partition],
            "p": [self.probas[c] for c in self.partition],
            "cote": [self.cotes.get(c, np.nan) if c in self.mises else np.nan
                     for c in self.partition],
            "mise": [self.mises.get(c, 0.0) for c in self.partition],
            "retour": [self.retour(c) for c in self.partition],
            "profit": [self.profit(c) for c in self.partition],
        })


# ---------------------------------------------------------------------------
# Répartitions
# ---------------------------------------------------------------------------

def _verifier(partition, probas, cotes, codes) -> None:
    manquants = [c for c in partition if c not in probas]
    if manquants:
        raise ValueError(f"probabilité manquante pour {manquants}")
    p = np.array([probas[c] for c in partition], dtype=float)
    if np.any(p < 0) or abs(p.sum() - 1.0) > 0.02:
        raise ValueError(
            f"les probabilités de la partition doivent sommer à 1 (reçu "
            f"{p.sum():.4f}) : elles viennent d'un livre dévigé ou d'une "
            "matrice de score, jamais de 1/cote.")
    for c in codes:
        if c not in partition:
            raise ValueError(f"{c!r} n'appartient pas à la partition {partition}")
        if c not in cotes or cotes[c] <= 1.0:
            raise ValueError(f"cote manquante ou invalide pour {c!r}")


def repartir(cotes: dict, total: float) -> dict:
    """Mises à retour égal : chaque issue rend la même somme si elle sort.

    ``mise_i = total × (1 / cote_i) / Σ (1 / cote_j)``. La somme des inverses
    est aussi ce que la couverture coûte : ``total / Σ`` est le retour
    garanti, et il n'excède la mise que si ``Σ < 1``.
    """
    if total <= 0:
        raise ValueError(f"mise totale invalide : {total!r}")
    if not cotes:
        raise ValueError("aucune cote à répartir")
    inv = {c: 1.0 / o for c, o in cotes.items()}
    s = sum(inv.values())
    return {c: total * v / s for c, v in inv.items()}


def couvrir(codes, cotes: dict, probas: dict, total: float,
            partition: tuple[str, ...] | None = None) -> Couverture:
    """Couverture à retour égal des issues ``codes``, pour une mise ``total``.

    ``partition`` est déduite du premier code si elle n'est pas donnée.
    ``probas`` porte sur TOUTES les issues de la partition : sans la
    probabilité des issues non couvertes, l'espérance ne se calcule pas.
    """
    codes = tuple(codes)
    if not codes:
        raise ValueError("aucune issue à couvrir")
    partition = tuple(partition or PARTITIONS[partition_de(codes[0])])
    _verifier(partition, probas, cotes, codes)
    mises = repartir({c: cotes[c] for c in codes}, total)
    return Couverture(partition, dict(probas), {c: cotes[c] for c in codes}, mises)


def rembourser(principal: str, secondaires, cotes: dict, probas: dict,
               mise_principale: float,
               partition: tuple[str, ...] | None = None) -> Couverture:
    """Couvrir pour être **remboursé** si une issue secondaire sort.

    On garde la mise principale telle quelle et on ajoute sur chaque
    secondaire juste ce qu'il faut pour récupérer la mise totale si elle
    sort. Avec ``T`` le total et ``m_j × c_j = T`` pour chaque secondaire :

        T = mise_principale / (1 − Σ_j 1/c_j)

    Impossible dès que ``Σ_j 1/c_j ≥ 1`` : les secondaires coûteraient plus
    que ce qu'ils rendent.
    """
    secondaires = tuple(secondaires)
    if mise_principale <= 0:
        raise ValueError(f"mise principale invalide : {mise_principale!r}")
    if principal in secondaires:
        raise ValueError("l'issue principale ne peut pas être aussi secondaire")
    partition = tuple(partition or PARTITIONS[partition_de(principal)])
    _verifier(partition, probas, cotes, (principal,) + secondaires)
    s = sum(1.0 / cotes[c] for c in secondaires)
    if s >= 1.0:
        raise ValueError(
            f"Σ 1/cote des issues secondaires = {s:.3f} ≥ 1 : les couvrir "
            "coûte plus qu'elles ne rendent, aucun remboursement possible.")
    total = mise_principale / (1.0 - s)
    mises = {principal: mise_principale}
    mises.update({c: total / cotes[c] for c in secondaires})
    return Couverture(partition, dict(probas),
                      {c: cotes[c] for c in mises}, mises)


def toutes_les_couvertures(cotes: dict, probas: dict, total: float,
                           partition: tuple[str, ...] | None = None
                           ) -> list[Couverture]:
    """Toutes les couvertures à retour égal d'une partition, pour ``total``.

    Chaque sous-ensemble non vide d'issues cotées — de l'issue seule à la
    couverture complète — triées par espérance décroissante. C'est le tableau
    « on fait comment » : chaque ligne dit ce qu'on gagne si l'une des issues
    couvertes sort, ce qu'on perd sinon, et ce que ça vaut en moyenne.
    """
    partition = tuple(partition or PARTITIONS[partition_de(next(iter(cotes)))])
    cotees = [c for c in partition if c in cotes and cotes[c] > 1.0]
    out = []
    for k in range(1, len(cotees) + 1):
        for sous in combinations(cotees, k):
            out.append(couvrir(sous, cotes, probas, total, partition))
    out.sort(key=lambda c: (-c.esperance, len(c.codes)))
    return out


# ---------------------------------------------------------------------------
# Kelly simultané sur des issues exclusives
# ---------------------------------------------------------------------------

def kelly_simultane(probas: dict, cotes: dict,
                    partition: tuple[str, ...] | None = None) -> dict:
    """Fractions de Kelly sur les issues exclusives d'un marché.

    Solution explicite de Smoczynski & Tomkins (2010). Les issues sont
    prises par rendement attendu ``p × cote`` décroissant ; on en ajoute une
    tant qu'elle bat la réserve

        R(S) = (1 − Σ_S p) / (1 − Σ_S 1/cote)

    — la part de bankroll que les issues déjà retenues laissent hors jeu,
    rapportée à ce qu'elles coûtent. La fraction de chaque issue retenue est
    alors ``p − R / cote``. Pour une issue seule, ``R = (1−p)·c/(c−1)`` et la
    fraction redonne ``(p·c − 1)/(c − 1)`` : ``paper.kelly``.

    Renvoie une fraction pour CHAQUE issue cotée, nulle pour celles qu'il
    ne faut pas couvrir. Une issue sans prix n'est pas couvrable et
    n'apparaît pas.
    """
    partition = tuple(partition or PARTITIONS[partition_de(next(iter(probas)))])
    cotees = [c for c in partition if c in cotes and cotes[c] > 1.0]
    _verifier(partition, probas, cotes, cotees)

    ordre = sorted(cotees, key=lambda c: -probas[c] * cotes[c])
    retenues: list[str] = []
    reserve = 1.0
    for c in ordre:
        if probas[c] * cotes[c] <= reserve:
            break
        candidates = retenues + [c]
        num = 1.0 - sum(probas[x] for x in candidates)
        den = 1.0 - sum(1.0 / cotes[x] for x in candidates)
        if den <= 0.0:
            # Les cotes retenues laissent un gain sûr : la solution de Kelly
            # n'est plus bornée. On s'arrête aux issues déjà retenues, et
            # c'est ``booksum`` qui dira le sur-arbitrage.
            break
        retenues, reserve = candidates, num / den

    return {c: (max(0.0, probas[c] - reserve / cotes[c]) if c in retenues else 0.0)
            for c in cotees}


def couverture_kelly(probas: dict, cotes: dict, bankroll: float,
                     fraction: float = 1.0,
                     partition: tuple[str, ...] | None = None) -> Couverture | None:
    """La couverture que Kelly recommande, en euros, ou ``None`` si aucune.

    ``fraction`` est le multiplicateur de Kelly fractionnaire (``f_base ×
    confiance`` dans le moteur de mise). Les issues à fraction nulle ne
    sont pas couvertes.
    """
    partition = tuple(partition or PARTITIONS[partition_de(next(iter(probas)))])
    f = kelly_simultane(probas, cotes, partition)
    mises = {c: bankroll * fraction * v for c, v in f.items() if v > 0}
    if not mises:
        return None
    return Couverture(partition, dict(probas), {c: cotes[c] for c in mises}, mises)
