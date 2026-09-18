"""Vocabulaire de la base de collecte — un seul, partagé par tous les lecteurs.

Le carnet nomme un pari par son code de catalogue (``"1"``,
``"total_over_2.5"``). La base de collecte range une cote sous un couple
``(market, selection)``. Ce module est la SEULE traduction entre les deux.

Avant lui, la même correspondance était écrite deux fois — dans le noyau
d'analyse pour le consensus, dans le carnet pour la clôture — et les deux
sources de collecte écrivaient les totaux différemment (``totals/over_2.5``
pour The Odds API, ``OU25/over`` pour football-data). Chaque lecteur devait
connaître les deux graphies, et chaque nouveau marché en aurait ajouté une.

Le vocabulaire retenu est celui de The Odds API, parce que la ligne fait
partie de la sélection : ``over_2.5`` et ``over_3.5`` sont deux marchés
distincts, ``OU25/over`` ne le savait dire que par le nom du marché.
"""

from __future__ import annotations

MARCHE_1X2 = "1X2"
MARCHE_TOTAUX = "totals"

_SELECTION_1X2 = {"1": "home", "N": "draw", "2": "away"}
_CODE_1X2 = {v: k for k, v in _SELECTION_1X2.items()}


def selection_collectee(code: str) -> tuple[str, str] | None:
    """``(market, selection)`` sous lequel la collecte range ce code de pari.

    ``None`` pour les marchés qu'aucune source accessible ne cote — totaux
    par équipe, les deux équipes marquent. Ces paris n'auront pas de CLV, et
    c'est une limite à afficher, pas à contourner.
    """
    if code in _SELECTION_1X2:
        return MARCHE_1X2, _SELECTION_1X2[code]
    morceaux = code.split("_")
    if len(morceaux) == 3 and morceaux[0] == "total" and morceaux[1] in ("over", "under"):
        return MARCHE_TOTAUX, f"{morceaux[1]}_{morceaux[2]}"
    return None


def code_collecte(market: str, selection: str) -> str | None:
    """Inverse de ``selection_collectee`` : le code de pari d'une ligne collectée."""
    if market == MARCHE_1X2:
        return _CODE_1X2.get(selection)
    if market == MARCHE_TOTAUX:
        sens, _, ligne = selection.partition("_")
        if sens in ("over", "under") and ligne:
            return f"total_{sens}_{ligne}"
    return None


def selection_totaux(ligne: float, sens: str) -> str:
    """``(2.5, "over") -> "over_2.5"`` — la graphie de la collecte."""
    return f"{sens}_{ligne}"
