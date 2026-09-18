"""Matchs à une date donnée : consensus, price shopping, verdict, totaux.

C'est le point d'entrée du tableau de bord. Il renvoie un ``MatchsDuJour``
typé plutôt qu'un dictionnaire : les colonnes que l'interface lit
(``p_1``, ``n_books_ou``, ``p_over25``…) sont un contrat, et un contrat
s'écrit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from odds.analysis import fiabilite, sources
from odds.analysis.sources import AUTRE_INSTANT, HORS_CONSENSUS
from odds.market.devig import devig_matrix
from odds.market.vocabulaire import selection_totaux


@dataclass
class MatchsDuJour:
    """Résultat de ``matchs_a_la_date``.

    ``source`` vaut ``"collecte"``, ``"historique"`` ou ``None`` quand la
    date n'a aucun match. ``fournisseur`` précise l'origine des cotes
    (``odds-api``, ``football-data``, ``pinnacle-closing``).

    ``resume`` : une ligne par match, consensus et verdict. ``detail`` : une
    ligne par (match, bookmaker). ``totaux`` : cotes over/under 2,5 au format
    long, pour le meilleur prix et le formulaire de pari.
    """
    source: str | None = None
    fournisseur: str | None = None
    resume: pd.DataFrame = field(default_factory=pd.DataFrame)
    detail: pd.DataFrame = field(default_factory=pd.DataFrame)
    totaux: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def vide(self) -> bool:
        return self.source is None


# --------------------------------------------------------------------------
# Marché des totaux (over/under 2,5)
# --------------------------------------------------------------------------
# Le seul marché de buts réellement coté qu'on puisse obtenir : les totaux
# par équipe sont un marché additionnel réservé aux offres payantes.
#
# Il vaut pourtant bien plus que lui-même. Une matrice de score calée sur le
# 1X2 SEUL sous-estime les buts de façon systématique (research/RESULTS.md
# R9) ; contrainte en plus par ce prix, elle rejoint la calibration du
# marché — y compris sur les totaux par équipe, que personne ne cote. Un
# crédit dépensé ici améliore donc des marchés qu'on ne peut pas observer.

OVER25, UNDER25 = selection_totaux(2.5, "over"), selection_totaux(2.5, "under")

_VIDE_TOTAUX = pd.DataFrame(columns=["fixture_key", "p_over25", "n_books_ou"])


def _consensus_totaux(long: pd.DataFrame, methode: str) -> pd.DataFrame:
    """Probabilité dévigée de « 3 buts ou plus », médiane des books réels."""
    if len(long) == 0:
        return _VIDE_TOTAUX.copy()
    long = long[long.selection.isin((OVER25, UNDER25))
                & ~long.bookmaker.isin(HORS_CONSENSUS)]
    if len(long) == 0:
        return _VIDE_TOTAUX.copy()
    large = long.pivot_table(index=["fixture_key", "bookmaker"],
                             columns="selection", values="odds", aggfunc="first")
    if not {OVER25, UNDER25} <= set(large.columns):
        return _VIDE_TOTAUX.copy()
    large = large.dropna(subset=[OVER25, UNDER25])
    large = large[(large[[OVER25, UNDER25]] > 1.0).all(axis=1)]
    if len(large) == 0:
        return _VIDE_TOTAUX.copy()

    p = devig_matrix(large[[OVER25, UNDER25]].to_numpy(float), methode)
    t = large.reset_index()[["fixture_key", "bookmaker"]].assign(p_over=p[:, 0])
    return (t.groupby("fixture_key")
             .agg(p_over25=("p_over", "median"), n_books_ou=("bookmaker", "nunique"))
             .reset_index())



def matchs_a_la_date(jour, methode: str = "shin") -> MatchsDuJour:
    """Tous les matchs d'une date, avec l'analyse calculée automatiquement.

    Renvoie ``source``, ``resume`` (une ligne par match) et ``detail``
    (une ligne par match x bookmaker).
    """
    jour = pd.Timestamp(jour)

    long = sources._long_depuis_collecte(jour)
    source, fournisseur = "collecte", None
    if len(long):
        fournisseur = (str(long.source.iloc[0]) if "source" in long.columns
                       and pd.notna(long.source.iloc[0]) else "football-data")
    else:
        long = sources._long_depuis_historique(jour)
        source, fournisseur = "historique", "pinnacle-closing"
    if len(long) == 0:
        return MatchsDuJour()

    # --- dévig, un livre à la fois ----------------------------------------
    large = long.pivot_table(
        index=["fixture_key", "bookmaker"], columns="selection",
        values="odds", aggfunc="first")
    large = large.dropna(subset=["home", "draw", "away"])
    large = large[(large[["home", "draw", "away"]] > 1.0).all(axis=1)]
    if len(large) == 0:
        return MatchsDuJour(source, fournisseur)

    cotes = large[["home", "draw", "away"]].to_numpy(float)
    p = devig_matrix(cotes, methode)

    detail = large.reset_index()[["fixture_key", "bookmaker"]].copy()
    detail[["cote_1", "cote_N", "cote_2"]] = cotes
    detail[["p_1", "p_N", "p_2"]] = p
    detail["marge"] = 100.0 * ((1.0 / cotes).sum(axis=1) - 1.0)

    meta_cols = ["fixture_key", "country", "league", "kickoff", "home_team", "away_team"]
    for c in ("resultat", "score", "observed_at"):
        if c in long.columns:
            meta_cols.append(c)
    meta = long[meta_cols].drop_duplicates("fixture_key")
    detail = detail.merge(meta, on="fixture_key", how="left")

    # --- consensus : médiane des bookmakers RÉELS -------------------------
    reels = detail[~detail.bookmaker.isin(HORS_CONSENSUS)]
    cons = (reels.groupby("fixture_key")
                 .agg(n_books=("bookmaker", "nunique"),
                      p_1=("p_1", "median"), p_N=("p_N", "median"), p_2=("p_2", "median"),
                      marge=("marge", "median"),
                      dispersion=("p_1", "std"))
                 .reset_index())
    s = cons[["p_1", "p_N", "p_2"]].sum(axis=1)
    cons[["p_1", "p_N", "p_2"]] = cons[["p_1", "p_N", "p_2"]].div(s, axis=0)
    cons["dispersion"] = 100.0 * cons.dispersion.fillna(0.0)

    # --- price shopping : meilleur prix disponible vs consensus -----------
    dispo = detail[~detail.bookmaker.isin(AUTRE_INSTANT)]
    for sel, col in (("1", "cote_1"), ("N", "cote_N"), ("2", "cote_2")):
        idx = dispo.groupby("fixture_key")[col].idxmax()
        b = dispo.loc[idx, ["fixture_key", col, "bookmaker"]].rename(
            columns={col: f"best_{sel}", "bookmaker": f"book_{sel}"})
        cons = cons.merge(b, on="fixture_key", how="left")
    cons = cons.merge(meta, on="fixture_key", how="left")

    # --- EV « leave-one-out » et soutien du meilleur prix ------------------
    #
    # Deux corrections indispensables pour que le chiffre veuille dire
    # quelque chose :
    #
    # 1) LEAVE-ONE-OUT. Comparer le meilleur prix à un consensus qui
    #    l'inclut est circulaire : le book généreux tire la médiane vers
    #    lui et masque son propre écart. On recalcule donc le consensus
    #    SANS le bookmaker qui offre ce prix.
    #
    # 2) SOUTIEN. Un prix isolé de 3 % au-dessus du deuxième meilleur n'est
    #    presque jamais une opportunité : c'est une cote périmée, une erreur,
    #    ou une limite de mise dérisoire. On mesure donc l'écart au deuxième
    #    meilleur prix, qui sépare l'anomalie isolée du désaccord réel.
    for sel, col in (("1", "cote_1"), ("N", "cote_N"), ("2", "cote_2")):
        p_loo, second, n_soutien = [], [], []
        for fk, best_book, best_cote in zip(cons.fixture_key, cons[f"book_{sel}"],
                                            cons[f"best_{sel}"]):
            g = dispo[dispo.fixture_key == fk]
            autres = g[g.bookmaker != best_book]
            reels = autres[~autres.bookmaker.isin(HORS_CONSENSUS)]
            src = reels if len(reels) else autres
            p_loo.append(float(np.median(src[f"p_{sel}"])) if len(src) else np.nan)
            second.append(float(autres[col].max()) if len(autres) else np.nan)
            n_soutien.append(int((g[col] >= best_cote * 0.99).sum()))
        cons[f"p_loo_{sel}"] = p_loo
        cons[f"second_{sel}"] = second
        cons[f"soutien_{sel}"] = n_soutien
        cons[f"ecart_{sel}"] = 100.0 * (np.array(p_loo) * cons[f"best_{sel}"] - 1.0)
        cons[f"prime_{sel}"] = 100.0 * (cons[f"best_{sel}"] / np.array(second) - 1.0)

    cons["meilleur_ecart"] = cons[["ecart_1", "ecart_N", "ecart_2"]].max(axis=1)

    # --- deux lectures distinctes, à ne jamais confondre -------------------
    #
    # 1) issue_probable : ce que le marché juge le plus probable.
    #    Lecture factuelle, PAS une recommandation. Au prix juste, miser sur
    #    le favori a une espérance nulle : le marché l'a déjà intégré.
    #
    # 2) issue_prix : l'issue dont le meilleur prix disponible s'écarte le
    #    plus du consensus. C'est du price shopping — une observation sur la
    #    dispersion des prix, pas une prédiction — et l'indicateur est biaisé
    #    à la hausse (le maximum sur N books retient la cote périmée).
    #
    # Les deux coïncident rarement.
    labels = np.array(["1", "N", "2"])
    probas = cons[["p_1", "p_N", "p_2"]].to_numpy()
    cons["issue_probable"] = labels[probas.argmax(axis=1)]
    cons["p_probable"] = probas.max(axis=1)

    ecarts = cons[["ecart_1", "ecart_N", "ecart_2"]].to_numpy()
    j = ecarts.argmax(axis=1)
    lig = np.arange(len(cons))
    cons["issue_prix"] = labels[j]
    cons["ecart_prix"] = ecarts[lig, j]
    cons["cote_prix"] = cons[["best_1", "best_N", "best_2"]].to_numpy()[lig, j]
    cons["book_prix"] = cons[["book_1", "book_N", "book_2"]].to_numpy()[lig, j]
    cons["prime_prix"] = cons[["prime_1", "prime_N", "prime_2"]].to_numpy()[lig, j]
    cons["soutien_prix"] = cons[["soutien_1", "soutien_N", "soutien_2"]].to_numpy()[lig, j]
    cons["p_prix"] = cons[["p_loo_1", "p_loo_N", "p_loo_2"]].to_numpy()[lig, j]
    cons["accord"] = cons.issue_probable == cons.issue_prix

    # --- robustesse de l'EV à la méthode de dévig --------------------------
    #
    # R3 a mesuré que sous 5 % de probabilité, les méthodes de dévig
    # divergent de 16,6 % EN RELATIF. Un écart de +7 % d'EV sur un outsider
    # est donc entièrement à l'intérieur du bruit de la méthode : il change
    # de signe selon qu'on retient Shin, power ou odds ratio.
    #
    # On recalcule donc l'EV sous les QUATRE méthodes. Si le signe ne tient
    # pas, le chiffre ne veut rien dire, quel que soit son niveau.
    cons[["ev_min", "ev_max"]] = _ev_toutes_methodes(cons, large, dispo)
    cons["ev_robuste"] = cons.ev_min > 0

    # --- marché des totaux, s'il a été collecté ----------------------------
    totaux = (sources._totaux_depuis_collecte(jour) if source == "collecte"
              else sources._totaux_depuis_historique(jour))
    tot = _consensus_totaux(totaux, methode)
    cons = cons.merge(tot, on="fixture_key", how="left") if len(tot) else \
        cons.assign(p_over25=np.nan, n_books_ou=0)
    cons["n_books_ou"] = cons.n_books_ou.fillna(0).astype(int)

    cons["verdict"] = [_verdict(r) for _, r in cons.iterrows()]

    cons = cons.sort_values("kickoff").reset_index(drop=True)
    try:
        cons = fiabilite.annoter_confiance(cons, methode)
    except FileNotFoundError:
        # L'historique peut légitimement manquer (installation neuve). Toute
        # AUTRE erreur doit remonter : un except nu masquerait un bug.
        pass
    return MatchsDuJour(source, fournisseur, cons, detail, totaux)


def _ev_toutes_methodes(cons: pd.DataFrame, large: pd.DataFrame,
                        dispo: pd.DataFrame) -> pd.DataFrame:
    """EV minimale et maximale de la sélection retenue, sur les 4 méthodes."""
    idx_sel = {"1": 0, "N": 1, "2": 2}
    cotes = large[["home", "draw", "away"]].to_numpy(float)
    cles = large.reset_index()[["fixture_key", "bookmaker"]]

    par_methode = {}
    for m in ("shin", "power", "odds_ratio", "proportional"):
        p = devig_matrix(cotes, m)
        t = cles.copy()
        t[["p_1", "p_N", "p_2"]] = p
        par_methode[m] = t

    bornes = []
    for fk, sel, best_book, best_cote in zip(
            cons.fixture_key, cons.issue_prix, cons.book_prix, cons.cote_prix):
        col = ["p_1", "p_N", "p_2"][idx_sel[sel]]
        evs = []
        for t in par_methode.values():
            g = t[(t.fixture_key == fk) & (t.bookmaker != best_book)]
            g = g[~g.bookmaker.isin(HORS_CONSENSUS)]
            if len(g) == 0:
                continue
            evs.append(100.0 * (float(np.median(g[col])) * best_cote - 1.0))
        bornes.append((min(evs), max(evs)) if evs else (np.nan, np.nan))
    return pd.DataFrame(bornes, columns=["ev_min", "ev_max"], index=cons.index)


# Seuils du verdict. Fixés ici, pas au fil de l'affichage, pour être
# discutables et modifiables en un seul endroit.
SEUIL_EV_MINI = 1.0        # en % — en deçà, le bruit domine
SEUIL_PRIME_ISOLEE = 2.0   # en % au-dessus du 2e meilleur prix = anomalie isolée
SOUTIEN_MINI = 2           # nombre de books à 1 % du meilleur prix
N_BOOKS_MINI = 6           # consensus indigent en dessous


def _verdict(r) -> str:
    """Traduit les chiffres en une conclusion unique et lisible.

    Rappel de cadrage : ce verdict ne prédit RIEN. Il dit seulement si le
    meilleur prix disponible s'écarte du consensus des autres bookmakers
    d'assez pour ne pas être du bruit, et si cet écart est soutenu par
    plusieurs opérateurs ou porté par un seul.
    """
    if r.n_books < N_BOOKS_MINI:
        return "Trop peu de books"
    if not np.isfinite(r.ecart_prix) or r.ecart_prix < SEUIL_EV_MINI:
        return "Rien à signaler"
    if r.prime_prix > SEUIL_PRIME_ISOLEE or r.soutien_prix < SOUTIEN_MINI:
        return "Écart isolé — prudence"
    if not r.get("ev_robuste", True):
        return "Fragile — dépend de la méthode"
    return "Écart soutenu"
