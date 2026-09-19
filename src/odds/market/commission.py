"""Commission des bourses d'échange — la cote affichée n'est pas celle qu'on encaisse.

Un bookmaker prend sa marge **dans le prix** : elle est déjà dans la cote, et
le dévig la retire. Une bourse d'échange (Betfair, Matchbook, Smarkets…) ne
prend presque rien dans le prix — c'est pourquoi ses cotes sont si souvent
les plus hautes — et prélève à la place une commission **sur le gain net**,
après coup. Les deux ne se comparent donc pas telles quelles :

    gain net encaissé = (cote − 1) × (1 − c)    →    cote nette = 1 + (cote − 1) × (1 − c)

Ce n'est pas un détail d'arrondi. Mesuré sur les 144 matchs collectés, 14 des
21 « écarts soutenus » portaient sur Betfair Exchange, pour un écart moyen de
+1,5 % — alors qu'à 5 % de commission, un écart de +1,8 % à la cote 2,38
devient **−1,1 %**. Comparer une cote d'exchange brute à un consensus de
bookmakers, c'est fabriquer exactement le genre d'avantage fictif que le
projet a mesuré partout ailleurs pour ne pas l'afficher (R3, R8, R9).

**Où la commission s'applique, et où elle ne s'applique pas.** Elle porte sur
le *paiement* d'un pari, pas sur l'*information* contenue dans le prix : une
cote d'exchange reste la meilleure estimation disponible de la probabilité,
et le consensus continue donc de la lire brute. C'est au moment de comparer
ce qu'on encaisse — espérance, Kelly, mise, CLV — qu'on prend la cote nette.

Le taux dépend du compte autant que de la bourse : les valeurs ci-dessous
sont les taux affichés par défaut, et ``COMMISSION_EXCHANGE`` dans ``.env``
les remplace tous par le vôtre.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from odds import config

# Part du GAIN NET prélevée par la bourse. Les noms varient selon la source :
# ``betfair_ex_eu`` vient de The Odds API, ``betfair_exchange`` de
# football-data. ``betfair_sportsbook`` est le bookmaker classique du même
# groupe — pas une bourse, pas de commission.
TAUX_DEFAUT = {
    "betfair_ex_eu": 0.05,
    "betfair_ex_uk": 0.05,
    "betfair_ex_au": 0.05,
    "betfair_exchange": 0.05,
    "matchbook": 0.015,
    "smarkets": 0.02,
    "betdaq": 0.02,
}

REGLAGE = "COMMISSION_EXCHANGE"


def _surcharge() -> float | None:
    """Taux unique imposé par ``.env``, en fraction. ``None`` si non réglé.

    Une valeur illisible est ignorée plutôt que fatale : un ``.env`` mal
    tapé ne doit pas empêcher le tableau de bord de s'ouvrir, mais il ne
    doit pas non plus faire croire à une commission qui n'est pas appliquée
    — ``odds config`` affiche la valeur retenue.
    """
    brut = config.get(REGLAGE)
    if brut is None or str(brut).strip() == "":
        return None
    try:
        taux_pct = float(str(brut).replace(",", ".").rstrip("%").strip())
    except ValueError:
        return None
    if not 0.0 <= taux_pct < 100.0:
        return None
    return taux_pct / 100.0


def _cle(bookmaker: str | None) -> str:
    return str(bookmaker or "").strip().lower()


def est_exchange(bookmaker: str | None) -> bool:
    """Le nom saisi à la main est normalisé : le carnet accepte du texte libre."""
    return _cle(bookmaker) in TAUX_DEFAUT


def taux(bookmaker: str | None) -> float:
    """Commission appliquée au gain net chez ce livre. 0 hors bourse d'échange."""
    if not est_exchange(bookmaker):
        return 0.0
    impose = _surcharge()
    return impose if impose is not None else TAUX_DEFAUT[_cle(bookmaker)]


def cote_nette(cote: float, bookmaker: str | None = None,
               taux_: float | None = None) -> float:
    """Cote équivalente une fois la commission retirée du gain.

    ``taux_`` permet de rejouer un pari déjà inscrit avec le taux qui lui a
    été appliqué à l'époque, plutôt qu'avec celui d'aujourd'hui.
    """
    c = taux(bookmaker) if taux_ is None else float(taux_)
    if not c:
        return float(cote)
    return 1.0 + (float(cote) - 1.0) * (1.0 - c)


def cote_brute(nette: float, bookmaker: str | None = None,
               taux_: float | None = None) -> float:
    """Réciproque de ``cote_nette`` — la cote à afficher pour un net donné."""
    c = taux(bookmaker) if taux_ is None else float(taux_)
    if not c:
        return float(nette)
    return 1.0 + (float(nette) - 1.0) / (1.0 - c)


def cotes_nettes(cotes, bookmakers: Sequence[str]) -> np.ndarray:
    """Version vectorisée : une cote nette par ligne ``(cote, bookmaker)``."""
    cotes = np.asarray(cotes, dtype=float)
    c = np.array([taux(b) for b in bookmakers], dtype=float)
    if cotes.ndim == 2:
        c = c[:, None]
    return 1.0 + (cotes - 1.0) * (1.0 - c)


def mention(bookmaker: str | None) -> str:
    """« commission 5 % » ou chaîne vide — à coller derrière un nom de livre."""
    c = taux(bookmaker)
    return f"commission {100 * c:.1f} %".replace(".0 ", " ") if c else ""
