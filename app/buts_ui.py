"""Marchés de buts à l'écran — « 3 buts ou plus », « telle équipe en met 2 ».

La logique vit dans ``odds.models.football.buts`` ; ce module l'affiche, et
surtout il affiche **d'où vient chaque probabilité**. C'est la distinction
que l'utilisateur doit voir en premier, parce que les deux cas ne valent pas
la même chose (research/RESULTS.md R9) :

- **calée sur le marché** — une cote over/under existe pour ce match, la
  matrice de score est contrainte de la reproduire. Sa calibration mesurée
  rejoint celle du marché lui-même : 0,7 point d'écart moyen ;
- **dérivée du 1X2 seul** — aucun prix de totaux disponible. La matrice
  reproduit le 1X2 et rien d'autre ; l'écart mesuré monte à 2-3 points, avec
  un biais résiduel.

Aucune de ces probabilités n'est cotée par un bookmaker accessible pour les
totaux PAR ÉQUIPE : c'est un marché additionnel, réservé aux offres
payantes. On les dérive donc toujours, et l'absence de prix a une
conséquence concrète qu'il faut dire — ces paris n'auront pas de CLV.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import theme
from odds.analysis import fiabilite_buts, tranche_fiabilite_buts
from odds.models.football import buts

# Familles affichées, dans l'ordre de lecture.
FAMILLES = [
    ("total", "Total du match", "Nombre de buts, les deux équipes réunies."),
    ("total_dom", "Total du domicile", None),
    ("total_ext", "Total de l'extérieur", None),
    ("btts", "Les deux équipes marquent", None),
]


def matrice_du_match(ligne) -> tuple[buts.Implicite, bool]:
    """Matrice de score du match, et si elle est calée sur un prix de totaux.

    Le second élément n'est pas cosmétique : il commande tout l'affichage.
    """
    p_over = getattr(ligne, "p_over25", None)
    contraint = p_over is not None and pd.notna(p_over) and 0.0 < float(p_over) < 1.0
    imp = buts.matrice_implicite(
        float(ligne.p_1), float(ligne.p_N), float(ligne.p_2),
        p_over=float(p_over) if contraint else None)
    return imp, contraint


def _meilleur_prix(totaux: pd.DataFrame, fixture_key: str) -> dict:
    """Meilleure cote over / under relevée chez un bookmaker réel."""
    if totaux is None or len(totaux) == 0:
        return {}
    d = totaux[(totaux.fixture_key == fixture_key)
               & ~totaux.bookmaker.astype(str).str.startswith("_")]
    out = {}
    for sens in ("over", "under"):
        g = d[d.selection == sens]
        if len(g):
            i = g.odds.idxmax()
            out[sens] = (float(g.loc[i, "odds"]), str(g.loc[i, "bookmaker"]))
    return out


def bandeau_source(imp: buts.Implicite, contraint: bool, n_books_ou: int = 0,
                   p_max: float | None = None) -> None:
    if not imp.fiable:
        st.error(
            "La matrice de score ne reproduit pas les probabilités 1X2 de ce "
            f"match (écart {100 * imp.ecart_max:.2f} pts). La famille de "
            "Poisson ne sait pas représenter cette configuration : **rien de "
            "ce qui suit n'est exploitable.**")
        return
    if contraint:
        st.success(
            f"**Calé sur le marché.** La cote over/under 2,5 de {n_books_ou} "
            "bookmaker(s) contraint la matrice, qui reproduit donc à la fois "
            "le 1X2 et le total du match. Calibration mesurée sur 43 204 "
            "matchs : **0,7 point** d'écart moyen entre probabilité annoncée "
            "et fréquence observée — celle du marché lui-même.")
    else:
        biais, niveau = buts.fiabilite_derivee(float(p_max or 0.5))
        commun = ("**Dérivé du 1X2 seul.** Aucune cote de totaux n'a été "
                  "relevée pour ce match : la matrice reproduit le 1X2 et "
                  "rien d'autre. Le 1X2 ne dit rien du nombre de buts — "
                  "c'est l'hypothèse de Poisson qui comble ce silence.")
        chiffre = (f" Sur des matchs aussi déséquilibrés que celui-ci "
                   f"(favori à {100 * (p_max or 0):.0f} %), l'écart mesuré "
                   f"entre probabilité annoncée et fréquence observée est de "
                   f"**{biais:.1f} points** (research/RESULTS.md R9).")
        if niveau == "inexploitable":
            st.error(commun + chiffre + " **À ce niveau, ces chiffres ne sont "
                     "pas exploitables** : la dérivation surestime lourdement "
                     "les buts.")
        elif niveau == "dégradé":
            st.error(commun + chiffre + " Le biais va toujours dans le même "
                     "sens : **les buts sont surestimés**.")
        else:
            st.warning(commun + chiffre + " À lire comme un ordre de grandeur, "
                       "pas comme un prix.")


def bloc_buts(ligne, totaux: pd.DataFrame | None = None) -> None:
    """Carte « Marchés de buts » du détail d'un match."""
    with st.container(border=True):
        theme.titre_section("Marchés de buts")
        imp, contraint = matrice_du_match(ligne)
        p_max = max(float(ligne.p_1), float(ligne.p_N), float(ligne.p_2))
        bandeau_source(imp, contraint, int(getattr(ligne, "n_books_ou", 0) or 0),
                       p_max=p_max)
        if not imp.fiable:
            return

        c1, c2, c3 = st.columns(3)
        c1.metric("Buts attendus", f"{imp.buts_attendus:.2f}",
                  f"{imp.lam:.2f} – {imp.mu:.2f}", delta_color="off")
        c2.metric("3 buts ou plus",
                  f"{100 * buts.probabilite(imp.matrice, 'total_over_2.5'):.1f} %",
                  "cote juste "
                  f"{1 / buts.probabilite(imp.matrice, 'total_over_2.5'):.2f}",
                  delta_color="off")
        c3.metric("Les deux marquent",
                  f"{100 * buts.probabilite(imp.matrice, 'btts_oui'):.1f} %",
                  "calé sur le marché" if contraint else "dérivé du 1X2",
                  delta_color="off")

        if len(fiabilite_buts()) == 0:
            st.caption("La colonne « réussite historique » est vide : lancez "
                       "`uv run python research/fiabilite_buts.py` pour la "
                       "calculer une fois pour toutes.")

        prix = _meilleur_prix(totaux, ligne.fixture_key)
        t = buts.marches_buts(imp.matrice, familles=[f for f, _, _ in FAMILLES],
                              dom=ligne.home_team, ext=ligne.away_team)

        for famille, titre, aide in FAMILLES:
            sous = t[t.famille == famille]
            if len(sous) == 0:
                continue
            sous = sous[sous.code.str.contains("_over_|btts_oui")]
            st.markdown(f"**{titre}**" + (f" — {aide}" if aide else ""))

            # La réussite historique est la signature de cet outil : une
            # probabilité annoncée ne vaut que par la fréquence à laquelle
            # elle s'est vérifiée, avec la taille d'échantillon derrière.
            tranches = [tranche_fiabilite_buts(c, pr, contraint)
                        for c, pr in zip(sous.code, sous.p)]
            vue = pd.DataFrame({
                "Pari": sous.libelle,
                "Probabilité": (100 * sous.p).map("{:.1f} %".format),
                "Cote juste": sous.cote_juste.map("{:.2f}".format),
                "Réussite hist.": [
                    "—" if t is None else f"{100 * float(t.reussite):.1f} %"
                    for t in tranches],
                "n hist.": [
                    "—" if t is None else f"{int(t.n):,}".replace(",", " ")
                    for t in tranches],
            })
            droite = ["Probabilité", "Cote juste", "Réussite hist.", "n hist."]
            # Le prix réel n'existe que sur la ligne 2,5 du total du match :
            # afficher une colonne vide ailleurs ferait croire à un manque
            # de collecte plutôt qu'à un marché inaccessible.
            if famille == "total" and "over" in prix:
                cote, book = prix["over"]
                p25 = float(sous.loc[sous.code == "total_over_2.5", "p"].iloc[0])
                vue["Meilleur prix"] = [
                    f"{cote:.2f} ({book})" if c == "total_over_2.5" else "—"
                    for c in sous.code]
                vue["Écart"] = [
                    theme.badge(f"{100 * (p25 * cote - 1):+.1f} %",
                                "pos" if p25 * cote > 1 else "neg")
                    if c == "total_over_2.5" else "" for c in sous.code]
                theme.tableau(vue, html=["Écart"], aligne_droite=droite + ["Écart"])
                if int(getattr(ligne, "n_books_ou", 0) or 0) < 2:
                    st.caption(
                        "⚠️ Un seul bookmaker cote ce total. L'écart affiché "
                        "compare son prix à une probabilité dérivée de ce même "
                        "prix : il ne mesure que **sa propre marge**, pas un "
                        "désaccord de marché. Il faut au moins deux opérateurs "
                        "pour que ce chiffre veuille dire quelque chose.")
            else:
                theme.tableau(vue, aligne_droite=droite)

        with st.expander("Comment ces probabilités sont obtenues"):
            st.markdown(f"""
Le marché ne cote que le 1X2 et, parfois, l'over/under 2,5. « Telle équipe marque 2 buts » n'est
coté par aucune source accessible — c'est un marché additionnel réservé aux offres payantes.

On ajuste donc une **matrice de score** (Dixon-Coles) pour qu'elle reproduise exactement les prix
que le marché affiche. Tous les marchés de buts se lisent ensuite dessus, par simple somme des
cases : « 3 buts ou plus » est la somme des scores dont le total dépasse 2,5.

| | ce match |
|---|---|
| buts attendus domicile (λ) | {imp.lam:.3f} |
| buts attendus extérieur (μ) | {imp.mu:.3f} |
| ρ (dépendance des scores faibles) | {imp.rho:+.3f} |
| contraintes reproduites | {", ".join(imp.contraintes)} |
| écart maximal aux prix imposés | {100 * imp.ecart_max:.4f} pt |

**Ce que la mesure dit de cette méthode** (research/RESULTS.md R9, 150 626 matchs) :

- contrainte par une cote de totaux, elle atteint la calibration du marché (0,7 pt d'écart) ;
- dérivée du 1X2 seul, elle tient sur les matchs équilibrés (moins d'un point d'écart sous 60 %
  de favori) et se dégrade à mesure que le match penche : +2,8 points à 80 %, +5 points au-delà,
  toujours en **surestimant** les buts ;
- **Dixon-Coles ajusté sur l'historique fait moins bien que les deux**, sur tous les marchés de
  buts et dans tous les championnats testés, petits compris. Le modèle n'est donc pas proposé
  ici comme source : le marché reste la meilleure information disponible.
""")
