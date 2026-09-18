"""Noyau d'analyse — partagé par la CLI et le tableau de bord.

Périmètre, révisé le 2026-09-18 (prereg 0003 §1) : outil personnel à usage
éducatif. Il affiche des probabilités et permet un suivi de paris **en
papier**. Il n'affirme pas pour autant détenir un avantage, et deux
résultats mesurés encadrent tout ce qu'il montre :

- **RESULTS R8** — un modèle de comptage sur données publiques ne bat ni la
  clôture ni le prix précoce, dans aucun des 23 championnats testés ;
- **RESULTS R9** — sur les marchés de buts non plus, y compris là où le
  marché ne cote rien. La meilleure information disponible reste le prix.

Ce que l'outil fait donc, et qui est vérifié :

- retirer correctement la marge d'un livre de cotes (ce que 1/cote ne fait
  pas, et ce que la normalisation proportionnelle fait mal) ;
- mesurer la calibration réelle du marché, et l'afficher avec son n ;
- dériver les marchés de buts du prix, en disant quand la dérivation tient
  et de combien elle se trompe quand elle ne tient plus ;
- cartographier marge et information tardive par championnat.
"""

from odds.analysis import base, consensus, fiabilite, sources  # noqa: F401
from odds.analysis.base import (ISSUES_1X2, analyser_livre, avec_cloture,  # noqa: F401
                                avec_precoce, carte_information_tardive,
                                carte_marges, charger, cible, comparer_methodes,
                                courbe_calibration, ece, probabilites_marche)
from odds.analysis.consensus import (N_BOOKS_MINI, SEUIL_EV_MINI,  # noqa: F401
                                     SEUIL_PRIME_ISOLEE, SOUTIEN_MINI,
                                     MatchsDuJour, _verdict, matchs_a_la_date)
from odds.analysis.fiabilite import (BORNES_CONFIANCE, NIVEAUX,  # noqa: F401
                                     _niveau, annoter_confiance,
                                     fiabilite_buts, fiabilite_historique,
                                     tranche_fiabilite, tranche_fiabilite_buts)
from odds.analysis.sources import (AGREGATS, AUTRE_INSTANT, BENCHMARKS,  # noqa: F401
                                   HORS_CONSENSUS, PREFERENCE_SOURCES,
                                   dates_disponibles)
